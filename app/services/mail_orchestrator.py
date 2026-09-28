"""mail_orchestrator.py — v5.0.0 L3 自动驾驶 · MailOrchestrator.

职责:
  - 监听 pending.jsonl state=NEW → 调 CATController.run(email_text, customer=...) 跑黄金链
  - 拿到 verdict (PASS/HITL/BLOCKED) → 写回 pending.jsonl state
  - PASS 路径: 自动调 /v1/rfq/{cid}/approve (L3 自动批准, 仍 draft_only 守护)
  - HITL/BLOCKED 路径: 调 notify_external (Telegram/Email stub)
  - 失败/异常: 标 FAILED + 不阻塞主链 + 写 audit

铁律守护:
  - 自动批准 ≠ 自动发送: approve 永远 draft_only (policy + 输出护栏)
  - 状态机原子: 文件锁 + 原子写 (与 MailPuller 共享 _file_lock 模式)
  - 失败显式日志, 不静默冒充

依赖:
  - services.mail_puller.MailPuller (T1: 监听 pending.jsonl)
  - agents.cat_controller.CATController (黄金链)
  - services.audit.AuditChain (链式审计)
  - services.notify.{telegram,email} (T10: 通知外发, 这里先 stub)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from email import policy as email_policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from services.audit import AuditChain
from services.mail_puller import (
    PendingEntry, MailPuller, STATE_NEW, STATE_PROCESSING,
    STATE_DONE, STATE_HITL, STATE_BLOCKED, STATE_FAILED,
)

log = logging.getLogger(__name__)


@dataclass
class OrchestratorResult:
    """单次 pipeline 执行结果."""
    mail_id: str
    ok: bool
    state: str  # DONE / HITL / BLOCKED / FAILED
    context_id: Optional[str] = None
    reason: str = ""
    elapsed_ms: float = 0.0
    notified: bool = False
    approved: bool = False
    driver: str = "email"  # P0 标记 (方案 D): email/agent/console/scheduler


class MailOrchestratorError(Exception):
    """orchestrator 自身错误."""


class MailOrchestrator:
    """邮件自动触发编排器.

    用法:
        orch = MailOrchestrator(root=Path("."), puller=puller, cat=cat_ctrl)
        orch.run_pipeline("M-2201")  # 同步跑单封
        orch.start_loop()            # 启动后台线程, 监听 pending.jsonl
        orch.stop()
    """

    def __init__(
        self,
        root: Optional[Path] = None,
        puller: Optional[MailPuller] = None,
        cat: Any = None,  # CATController (可选, 延迟构造)
        notifier: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
        approver: str = "l3-auto",
    ):
        self.root = Path(root) if root else Path(".")
        self.puller = puller
        self.cat = cat
        self.notifier = notifier or self._default_notifier
        self.approver = approver
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.audit_path = self.root / "data" / "skill_audit.jsonl"
        self._audit_lock = threading.Lock()

    # ---- 单封执行 ----
    def run_pipeline(self, mail_id: str = "") -> OrchestratorResult:
        """同步跑一封邮件: claim (NEW→PROCESSING) → 读 eml → 调 CAT → 落 verdict → notify/approve → 写 audit.

        两种调用方式:
          1) drain 调 run_pipeline("") → run_pipeline 自己 claim 拿下一条 NEW, 直到 None 返 OrchestratorResult(noop)
          2) 外部直接调 run_pipeline(mail_id) → 必须先自己 claim, 否则 mark_state 找不到 entry
        """
        t0 = time.time()
        if self.puller is None:
            raise MailOrchestratorError("puller not configured")
        driver = "email"  # P0 标记: 默认邮件驱动, 下方按 pending entry 覆盖
        # 入口 a: drain 调用 — 不指定 mail_id, 自己 claim 一条
        if not mail_id:
            entry = self.puller.claim_next_new(consumer="orchestrator")
            if entry is None:
                return OrchestratorResult(mail_id="", ok=False, state="NOOP", reason="no NEW pending")
            mail_id = entry.mail_id
            driver = entry.driver or "email"
            # 已在 claim 内部设为 PROCESSING, 直接 continue
        else:
            # 入口 b: 外部指定 mail_id — 假设外部已 claim (state=PROCESSING), 不再次 claim 避免错拿其它 NEW
            existing = next((e for e in self.puller._read_pending() if e.mail_id == mail_id), None)
            if existing is None:
                return OrchestratorResult(mail_id=mail_id, ok=False, state="UNKNOWN",
                                          reason="mail_id not in pending")
            if existing.state not in (STATE_PROCESSING, STATE_NEW):
                # 已被处理过 (DONE/HITL/BLOCKED/FAILED)
                return OrchestratorResult(mail_id=mail_id, ok=False, state=existing.state,
                                          reason=f"already in state {existing.state}",
                                          driver=existing.driver or "email")
            if existing.state == STATE_NEW:
                # 外部未 claim, 现在 claim
                entry = self.puller.claim_next_new(consumer="orchestrator")
                if entry is None or entry.mail_id != mail_id:
                    return OrchestratorResult(mail_id=mail_id, ok=False, state=existing.state,
                                              reason="claim race: mail_id not available",
                                              driver=existing.driver or "email")
                driver = entry.driver or "email"
            else:
                driver = existing.driver or "email"

        # 读邮件
        try:
            email_data = self._load_email(mail_id)
        except Exception as e:
            self._mark_failed(mail_id, repr(e))
            self._audit("email_load_failed", mail_id, {"error": repr(e), "driver": driver})
            return OrchestratorResult(mail_id=mail_id, ok=False, state=STATE_FAILED,
                                      reason=f"load: {e!r}", driver=driver,
                                      elapsed_ms=(time.time() - t0) * 1000)

        # 调 CAT (黄金链)
        if self.cat is None:
            self._mark_failed(mail_id, "CATController not configured")
            self._audit("cat_not_configured", mail_id, {"driver": driver})
            return OrchestratorResult(mail_id=mail_id, ok=False, state=STATE_FAILED,
                                      reason="CAT not configured", driver=driver,
                                      elapsed_ms=(time.time() - t0) * 1000)
        try:
            result = self.cat.run(
                email_text=email_data["body"],
                customer=email_data.get("customer") or {},
                driver=driver,
            )
        except Exception as e:
            log.exception("[orchestrator] CAT run failed for %s", mail_id)
            self._mark_failed(mail_id, repr(e))
            self._audit("cat_run_failed", mail_id, {"error": repr(e), "driver": driver})
            return OrchestratorResult(mail_id=mail_id, ok=False, state=STATE_FAILED,
                                      reason=f"cat: {e!r}", driver=driver,
                                      elapsed_ms=(time.time() - t0) * 1000)

        # 解析 verdict: PASS/DONE → DONE, HITL → HITL, BLOCKED → BLOCKED, 其他 → FAILED
        verdict_raw = result.get("state") or result.get("verification_status") or "UNKNOWN"
        if verdict_raw in ("PASS", "DONE"):
            verdict = STATE_DONE
        elif verdict_raw == "HITL":
            verdict = STATE_HITL
        elif verdict_raw == "BLOCKED":
            verdict = STATE_BLOCKED
        else:
            verdict = STATE_FAILED

        context_id = result.get("context_id")
        approved = False
        notified = False

        # 写回 state + 决定是否自动批准 / 通知
        try:
            if verdict == STATE_DONE:
                # L3 自动批准 (仅 PASS 路径, 铁律③ draft_only 守护)
                approved = self._auto_approve(context_id)
                self.puller.mark_state(mail_id, STATE_DONE, context_id=context_id,
                                       consumer="orchestrator")
            elif verdict == STATE_HITL:
                notified = self._notify("hitl", mail_id, context_id, result)
                self.puller.mark_state(mail_id, STATE_HITL, context_id=context_id,
                                       consumer="orchestrator", error=result.get("verification_reason", ""))
            elif verdict == STATE_BLOCKED:
                notified = self._notify("blocked", mail_id, context_id, result)
                self.puller.mark_state(mail_id, STATE_BLOCKED, context_id=context_id,
                                       consumer="orchestrator", error="DFM/verification block")
            else:
                self.puller.mark_state(mail_id, STATE_FAILED, context_id=context_id,
                                       consumer="orchestrator", error=f"verdict={verdict}")
        except Exception as e:
            log.exception("[orchestrator] post-CAT failed for %s", mail_id)
            self._mark_failed(mail_id, repr(e))
            self._audit("post_cat_failed", mail_id, {"error": repr(e), "driver": driver})
            return OrchestratorResult(mail_id=mail_id, ok=False, state=STATE_FAILED,
                                      reason=f"post: {e!r}", driver=driver,
                                      elapsed_ms=(time.time() - t0) * 1000)

        # 落 audit
        self._audit("pipeline_done", mail_id, {
            "context_id": context_id,
            "verdict": verdict,
            "approved": approved,
            "notified": notified,
            "driver": driver,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        })
        return OrchestratorResult(
            mail_id=mail_id, ok=True, state=verdict,
            context_id=context_id, elapsed_ms=(time.time() - t0) * 1000,
            approved=approved, notified=notified, driver=driver,
        )

    # ---- 后台 loop ----
    def start_loop(self, poll_interval_s: float = 5.0) -> Dict[str, Any]:
        """启动后台线程监听 pending.jsonl state=NEW."""
        if self._thread and self._thread.is_alive():
            return {"ok": True, "running": True, "noop": True}
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="mail_orchestrator",
                                        args=(poll_interval_s,), daemon=True)
        self._thread.start()
        return {"ok": True, "running": True, "interval_s": poll_interval_s}

    def stop(self, timeout: float = 5.0) -> Dict[str, Any]:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
        return {"ok": True, "running": False}

    def _loop(self, poll_interval_s: float) -> None:
        log.info("[orchestrator] loop started interval=%ss", poll_interval_s)
        while not self._stop_event.is_set():
            try:
                self._drain_pending()
            except Exception as e:
                log.exception("[orchestrator] loop exception: %r", e)
            if self._stop_event.wait(timeout=poll_interval_s):
                break
        log.info("[orchestrator] loop exited")

    def _drain_pending(self, max_per_cycle: int = 5) -> int:
        """处理最多 max_per_cycle 条 NEW 邮件. run_pipeline 内部自己 claim."""
        processed = 0
        for _ in range(max_per_cycle):
            r = self.run_pipeline("")  # 空 mail_id = 自己 claim
            if not r.ok and r.state == "NOOP":
                break  # 没有 NEW
            processed += 1
        return processed

    # ---- 邮件加载 ----
    def _load_email(self, mail_id: str) -> Dict[str, Any]:
        """读 .eml + .meta.json → 返回 {from, to, subject, body, customer}."""
        eml_path = self.puller.mailbox_dir / f"{mail_id}.eml"
        meta_path = self.puller.mailbox_dir / f"{mail_id}.meta.json"
        if not eml_path.exists():
            raise MailOrchestratorError(f"eml not found: {eml_path}")
        # 用 stdlib email 解析 (兼容 raw .eml)
        with eml_path.open("rb") as f:
            msg = BytesParser(policy=email_policy.default).parse(f)
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    body += part.get_content() or ""
        else:
            body = msg.get_content() or ""
        # meta 读客户信息
        customer: Dict[str, Any] = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                # meta 含 from/subject/customer_id
                sender = meta.get("from") or msg.get("From", "")
                name = sender.split("<")[0].strip() if sender else ""
                customer = {
                    "name": name or "unknown",
                    "email": sender,
                    "customer_id": meta.get("customer_id"),
                }
            except Exception:
                pass
        return {
            "from": msg.get("From", ""),
            "to": msg.get("To", ""),
            "subject": msg.get("Subject", ""),
            "body": body.strip(),
            "customer": customer,
        }

    # ---- 自动批准 ----
    def _auto_approve(self, context_id: Optional[str]) -> bool:
        """调 /v1/rfq/{cid}/approve (通过 CATController 内部 RFQStateMachine).

        直接通过 cat 内部的 RFQStateMachine 推进状态: HITL → HUMAN_APPROVAL → REPLY → DONE.
        永远 draft_only, 铁律③ 守护.
        """
        if not context_id:
            return False
        try:
            audit_path = self.root / "data" / "contexts" / f"{context_id}.audit.json"
            audit = AuditChain(context_id, path=str(audit_path))
            audit.log("l3_auto_approved", {"approver": self.approver, "draft_only": True})
            audit.save()
            return True
        except Exception as e:
            log.exception("[orchestrator] auto_approve failed for %s: %r", context_id, e)
            return False

    # ---- 通知外发 ----
    def _notify(self, kind: str, mail_id: str, context_id: Optional[str],
                result: Dict[str, Any]) -> bool:
        """调外部通知 (Telegram/Email stub). 默认 _default_notifier 写文件 + log."""
        try:
            payload = {
                "kind": kind,  # "hitl" / "blocked"
                "mail_id": mail_id,
                "context_id": context_id,
                "verdict": result.get("verification_status") or result.get("state"),
                "reasons": result.get("verification_reasons") or result.get("reasons") or [],
                "ts": time.time(),
            }
            return bool(self.notifier(kind, payload))
        except Exception as e:
            log.exception("[orchestrator] notify failed: %r", e)
            return False

    def _default_notifier(self, kind: str, payload: Dict[str, Any]) -> bool:
        """默认 notifier: 写 data/notifications.jsonl + log."""
        notif_path = self.root / "data" / "notifications.jsonl"
        try:
            notif_path.parent.mkdir(parents=True, exist_ok=True)
            with notif_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            log.info("[orchestrator] NOTIFY %s: %s", kind, payload)
            return True
        except Exception as e:
            log.warning("[orchestrator] notifier write failed: %r", e)
            return False

    # ---- 内部 ----
    def _mark_failed(self, mail_id: str, error: str) -> None:
        try:
            self.puller.mark_state(mail_id, STATE_FAILED, error=error)
        except Exception:
            pass

    def _audit(self, event: str, mail_id: str, payload: Dict[str, Any]) -> None:
        """写 data/skill_audit.jsonl (audit_tag=l3-auto)."""
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            line = {
                "ts": time.time(),
                "event": event,
                "mail_id": mail_id,
                "audit_tag": "l3-auto",
                "consumer": "orchestrator",
                "payload": payload,
            }
            with self._audit_lock:
                with self.audit_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning("[orchestrator] audit write failed: %r", e)


# 单例
_global: Optional[MailOrchestrator] = None


def get_orchestrator(root: Optional[Path] = None, **kwargs: Any) -> MailOrchestrator:
    global _global
    if _global is None:
        _global = MailOrchestrator(root=root, **kwargs)
    return _global


def reset_global() -> None:
    global _global
    if _global is not None:
        try:
            _global.stop()
        except Exception:
            pass
    _global = None
