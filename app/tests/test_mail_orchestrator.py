"""tests/test_mail_orchestrator.py — T2: 自动触发链路 (pull → CATController) 12 用例.

覆盖:
  1. PASS 路径: mock CAT verdict=PASS → DONE + 自动 approve + audit +1
  2. HITL 路径: mock CAT verdict=HITL → HITL + notify 调通
  3. BLOCKED 路径: mock CAT verdict=BLOCKED → BLOCKED + notify
  4. FAILED 路径: CAT 抛异常 → FAILED + 不阻塞主链
  5. 重复触发幂等: 同一 mail_id claim 后 state=PROCESSING, 再次 run_pipeline 返 already-processing
  6. 启动/停止后台 loop + 监听 NEW 自动跑
  7. notifier 失败不阻塞主链 (返 notified=False, state 仍正常)
  8. pending.jsonl 持久化 + audit jsonl 含 audit_tag=l3-auto
  9. P0 driver 标记: email 入口 → result.driver + audit payload.driver
  10. P0 driver 标记: agent 驱动 entry 同样透传
  11. P0 driver 标记: CAT 调用收到 driver kwarg
  12. audit jsonl + pending 持久化
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from services.mail_puller import MailPuller, PendingEntry, STATE_NEW, STATE_PROCESSING


# ---------- 工具 ----------
def _write_eml(tmp_root: Path, mail_id: str, *, from_: str = "alice@northwind.com",
               subject: str = "RFQ 6061 brackets", body: str = "Need quote 50 pcs 6061") -> Path:
    """写一个真实可被 stdlib email 解析的 .eml 文件."""
    eml_path = tmp_root / "data" / "mailbox" / f"{mail_id}.eml"
    eml_path.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        f"From: {from_}\r\n"
        f"To: sales@union-mfg.com\r\n"
        f"Subject: {subject}\r\n"
        f"Date: Mon, 19 Sep 2026 10:00:00 +0800\r\n"
        f"\r\n"
        f"{body}\r\n"
    ).encode("utf-8")
    eml_path.write_bytes(raw)
    meta_path = eml_path.with_suffix(".meta.json") if eml_path.suffix == ".eml" else eml_path.parent / f"{mail_id}.meta.json"
    meta_path.write_text(json.dumps({
        "from": from_, "subject": subject, "received_at": time.time(),
        "badges": ["NEW", "GMAIL_PULLED"], "source": "test"
    }), encoding="utf-8")
    return eml_path


def _make_puller(tmp_root: Path) -> MailPuller:
    return MailPuller(root=tmp_root, interval_s=0.5, limit=10, mailbox_factory=None)


class MockCAT:
    """Mock CATController: 返固定 verdict."""

    def __init__(self, verdict: str = "PASS", *, raise_exc: Optional[Exception] = None,
                 context_id: str = "RFQ-MOCK-001"):
        self.verdict = verdict
        self.raise_exc = raise_exc
        self.context_id = context_id
        self.call_count = 0
        self.last_email_text = ""
        self.last_customer: Dict[str, Any] = {}

    def run(self, email_text: str, customer: Optional[Dict[str, Any]] = None,
            **kwargs: Any) -> Dict[str, Any]:
        self.call_count += 1
        self.last_email_text = email_text
        self.last_customer = customer or {}
        if self.raise_exc:
            raise self.raise_exc
        return {
            "state": self.verdict,
            "context_id": self.context_id,
            "verification_status": self.verdict,
            "reasons": ["mock reason"] if self.verdict != "PASS" else [],
        }


def _make_orch(tmp_root: Path, cat: Any, notifier=None) -> Any:
    from services.mail_orchestrator import MailOrchestrator
    puller = _make_puller(tmp_root)
    return MailOrchestrator(root=tmp_root, puller=puller, cat=cat, notifier=notifier), puller, cat


# ---- 1. PASS 路径 ----
def test_pass_path_done_and_audit(tmp_root: Path) -> None:
    _write_eml(tmp_root, "M-PASS-1")
    orch, puller, cat = _make_orch(tmp_root, MockCAT(verdict="PASS"))
    # 先把邮件挂到 pending (模拟 puller 已 enqueue)
    puller._append_pending([PendingEntry(mail_id="M-PASS-1", state=STATE_NEW)])
    r = orch.run_pipeline("M-PASS-1")
    assert r.ok is True
    assert r.state == "DONE"
    assert r.context_id == "RFQ-MOCK-001"
    assert r.approved is True
    assert cat.call_count == 1
    # pending 状态更新
    assert puller.list_by_state("DONE")[0].mail_id == "M-PASS-1"
    # audit 落库
    audit_path = tmp_root / "data" / "skill_audit.jsonl"
    assert audit_path.exists()
    lines = [json.loads(l) for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(l.get("event") == "pipeline_done" and l.get("audit_tag") == "l3-auto" for l in lines)


# ---- 2. HITL 路径 ----
def test_hitl_path_notified(tmp_root: Path) -> None:
    _write_eml(tmp_root, "M-HITL-1")
    notif = []
    def n(kind, payload):
        notif.append((kind, payload))
        return True
    orch, puller, cat = _make_orch(tmp_root, MockCAT(verdict="HITL"), notifier=n)
    puller._append_pending([PendingEntry(mail_id="M-HITL-1", state=STATE_NEW)])
    r = orch.run_pipeline("M-HITL-1")
    assert r.ok is True
    assert r.state == "HITL"
    assert r.notified is True
    assert r.approved is False
    assert len(notif) == 1
    assert notif[0][0] == "hitl"
    assert notif[0][1]["context_id"] == "RFQ-MOCK-001"
    assert puller.list_by_state("HITL")[0].mail_id == "M-HITL-1"


# ---- 3. BLOCKED 路径 ----
def test_blocked_path_notified(tmp_root: Path) -> None:
    _write_eml(tmp_root, "M-BLK-1")
    notif = []
    def n(kind, payload):
        notif.append((kind, payload))
        return True
    orch, puller, cat = _make_orch(tmp_root, MockCAT(verdict="BLOCKED"), notifier=n)
    puller._append_pending([PendingEntry(mail_id="M-BLK-1", state=STATE_NEW)])
    r = orch.run_pipeline("M-BLK-1")
    assert r.ok is True
    assert r.state == "BLOCKED"
    assert r.notified is True
    assert notif[0][0] == "blocked"
    assert puller.list_by_state("BLOCKED")[0].mail_id == "M-BLK-1"


# ---- 4. FAILED 路径 ----
def test_failed_path_cat_exception(tmp_root: Path) -> None:
    _write_eml(tmp_root, "M-FAIL-1")
    orch, puller, _ = _make_orch(tmp_root, MockCAT(raise_exc=RuntimeError("cat boom")))
    puller._append_pending([PendingEntry(mail_id="M-FAIL-1", state=STATE_NEW)])
    r = orch.run_pipeline("M-FAIL-1")
    assert r.ok is False
    assert r.state == "FAILED"
    assert "cat boom" in r.reason
    assert puller.list_by_state("FAILED")[0].mail_id == "M-FAIL-1"
    assert puller.list_by_state("DONE") == []
    assert puller.list_by_state("HITL") == []
    # 主链不阻塞: orchestrator 本身仍可继续处理下一封
    _write_eml(tmp_root, "M-PASS-2")
    puller._append_pending([PendingEntry(mail_id="M-PASS-2", state=STATE_NEW)])
    # 新建 PASS cat
    from services.mail_orchestrator import MailOrchestrator
    orch2 = MailOrchestrator(root=tmp_root, puller=puller,
                              cat=MockCAT(verdict="PASS", context_id="RFQ-002"))
    r2 = orch2.run_pipeline("M-PASS-2")
    assert r2.ok is True
    assert r2.state == "DONE"


# ---- 5. 重复触发幂等 ----
def test_repeat_run_idempotent(tmp_root: Path) -> None:
    _write_eml(tmp_root, "M-IDEMP-1")
    orch, puller, cat = _make_orch(tmp_root, MockCAT(verdict="PASS"))
    puller._append_pending([PendingEntry(mail_id="M-IDEMP-1", state=STATE_NEW)])
    # 1st run: claim + DONE
    r1 = orch.run_pipeline("M-IDEMP-1")
    assert r1.ok is True
    assert r1.state == "DONE"
    assert cat.call_count == 1
    # 2nd run: 已 DONE, 不再调 CAT
    r2 = orch.run_pipeline("M-IDEMP-1")
    assert r2.ok is False
    assert r2.state == "DONE"
    assert r2.reason.startswith("already in state")
    assert cat.call_count == 1  # 没再调


# ---- 6. 后台 loop 自动跑 ----
def test_loop_drains_pending(tmp_root: Path) -> None:
    _write_eml(tmp_root, "M-LOOP-1")
    _write_eml(tmp_root, "M-LOOP-2")
    orch, puller, cat = _make_orch(tmp_root, MockCAT(verdict="PASS", context_id="RFQ-LOOP"))
    puller._append_pending([
        PendingEntry(mail_id="M-LOOP-1", state=STATE_NEW),
        PendingEntry(mail_id="M-LOOP-2", state=STATE_NEW),
    ])
    orch.start_loop(poll_interval_s=0.3)
    # 等后台处理 2 封
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if len(puller.list_by_state("DONE")) >= 2:
            break
        time.sleep(0.2)
    orch.stop(timeout=3.0)
    assert len(puller.list_by_state("DONE")) == 2
    assert cat.call_count == 2


# ---- 7. notifier 失败不阻塞 ----
def test_notifier_failure_does_not_block(tmp_root: Path) -> None:
    _write_eml(tmp_root, "M-NFAIL-1")
    def n(kind, payload):
        raise ConnectionError("telegram down")
    orch, puller, _ = _make_orch(tmp_root, MockCAT(verdict="HITL"), notifier=n)
    puller._append_pending([PendingEntry(mail_id="M-NFAIL-1", state=STATE_NEW)])
    r = orch.run_pipeline("M-NFAIL-1")
    assert r.ok is True
    assert r.state == "HITL"
    assert r.notified is False  # 通知失败但状态正常
    assert puller.list_by_state("HITL")[0].mail_id == "M-NFAIL-1"


# ---- 9. P0 driver 标记: email 入口透传到 result + audit ----
def test_driver_marker_email_flows_to_result_and_audit(tmp_root: Path) -> None:
    _write_eml(tmp_root, "M-DRV-1")
    orch, puller, cat = _make_orch(tmp_root, MockCAT(verdict="PASS"))
    puller._append_pending([PendingEntry(mail_id="M-DRV-1", state=STATE_NEW,
                                         driver="email", source_ref="<m1>")])
    r = orch.run_pipeline("M-DRV-1")
    assert r.ok is True
    assert r.driver == "email"
    audit_path = tmp_root / "data" / "skill_audit.jsonl"
    lines = [json.loads(l) for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    done = [l for l in lines if l.get("event") == "pipeline_done"]
    assert done and done[-1]["payload"]["driver"] == "email"


# ---- 10. P0 driver 标记: agent 驱动 entry 同样透传 ----
def test_driver_marker_agent_entry(tmp_root: Path) -> None:
    _write_eml(tmp_root, "M-DRV-2")
    orch, puller, cat = _make_orch(tmp_root, MockCAT(verdict="PASS"))
    puller._append_pending([PendingEntry(mail_id="M-DRV-2", state=STATE_NEW,
                                         driver="agent", source_ref="flywheel:retention")])
    r = orch.run_pipeline("M-DRV-2")
    assert r.ok is True
    assert r.driver == "agent"
    audit_path = tmp_root / "data" / "skill_audit.jsonl"
    lines = [json.loads(l) for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    done = [l for l in lines if l.get("event") == "pipeline_done"]
    assert done[-1]["payload"]["driver"] == "agent"


# ---- 11. P0 driver 标记: CAT 调用收到 driver ----
def test_driver_marker_passed_to_cat(tmp_root: Path) -> None:
    _write_eml(tmp_root, "M-DRV-3")
    cat = MockCAT(verdict="PASS")
    cat.last_driver = None
    orig_run = cat.run

    def run_spy(email_text, customer=None, **kw):
        cat.last_driver = kw.get("driver")
        return orig_run(email_text, customer, **kw)

    cat.run = run_spy
    orch, puller, _ = _make_orch(tmp_root, cat)
    puller._append_pending([PendingEntry(mail_id="M-DRV-3", state=STATE_NEW,
                                         driver="email", source_ref="<m3>")])
    r = orch.run_pipeline("M-DRV-3")
    assert r.ok is True
    assert cat.last_driver == "email"


# ---- 12. audit jsonl + pending 持久化 ----
def test_audit_and_persistence(tmp_root: Path) -> None:
    _write_eml(tmp_root, "M-PERS-1")
    orch, puller, _ = _make_orch(tmp_root, MockCAT(verdict="DONE", context_id="RFQ-PERS"))
    puller._append_pending([PendingEntry(mail_id="M-PERS-1", state=STATE_NEW)])
    orch.run_pipeline("M-PERS-1")
    # audit 含 l3-auto tag
    audit_path = tmp_root / "data" / "skill_audit.jsonl"
    lines = [json.loads(l) for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    events = [l["event"] for l in lines]
    assert "pipeline_done" in events
    assert all(l.get("audit_tag") == "l3-auto" for l in lines)
    # 新建 orchestrator 读同一目录 → pending 状态保持
    from services.mail_orchestrator import MailOrchestrator
    puller2 = _make_puller(tmp_root)
    orch2 = MailOrchestrator(root=tmp_root, puller=puller2, cat=MockCAT(verdict="DONE"))
    entries = puller2._read_pending()
    assert any(e.mail_id == "M-PERS-1" and e.state == "DONE" for e in entries)
