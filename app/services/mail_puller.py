"""mail_puller.py — v5.0.0 L3 自动驾驶 · 邮件轮询 puller.

职责:
  - 后台 30s 轮询 Gmail IMAP (imap_tools, 默认禁 → 显式 enabled 才启动)
  - 每封新邮件: 落 .eml + .meta.json + 追加 pending.jsonl state=NEW
  - 失败退避: 30s → 2min → 5min (封顶 5min)
  - MailOrchestrator (T2) 订阅 pending.jsonl state=NEW 行 → 触发 CATController.run

铁律守护:
  - 凭据从 services.credentials 读 (Fernet 解密), 不存 plaintext, 不外发
  - 默认禁用: 必须 settings.gmail.enabled=true AND credentials.json 存在 才启动
  - 失败显式日志, 不静默冒充
  - 状态机原子写: 文件锁 + 临时文件 + rename

数据流:
  IMAP sync → .eml + .meta.json (已有, gmail_imap.sync)
            → append pending.jsonl {mail_id, state=NEW, queued_at}
  MailOrchestrator (T2) 监听 pending.jsonl → 改 state=PROCESSING → 跑完后改 DONE/HITL/BLOCKED/FAILED
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .credentials import load_credentials, status as cred_status, CRED_FILE as DEFAULT_CRED_FILE
from .gmail_imap import GmailMailbox

log = logging.getLogger(__name__)

# 状态机
STATE_NEW = "NEW"
STATE_PROCESSING = "PROCESSING"
STATE_DONE = "DONE"
STATE_HITL = "HITL"
STATE_BLOCKED = "BLOCKED"
STATE_FAILED = "FAILED"
STATE_DEAD = "DEAD"  # 死信: 重试超限, 不再自动重回队列
ALL_STATES = {STATE_NEW, STATE_PROCESSING, STATE_DONE, STATE_HITL, STATE_BLOCKED, STATE_FAILED, STATE_DEAD}

# 默认重试上限 (D-P0.4)
DEFAULT_MAX_ATTEMPTS = 3
# 默认 PROCESSING 租约超时 (秒): 超时视为卡死, 可被 reclaim
DEFAULT_LEASE_TIMEOUT_S = 300
# 默认单周期最多认领条数
DEFAULT_MAX_PER_CYCLE = 20

# 退避表 (秒): 第 1/2/3/4+ 次连续失败
BACKOFF_TABLE = [30, 120, 300]  # 30s, 2min, 5min (封顶 5min)

# 默认轮询间隔
DEFAULT_INTERVAL_S = 30
DEFAULT_LIMIT = 20


@dataclass
class PullerState:
    """puller 自身的运行状态 (持久化到 data/mail_puller/state.json)."""
    enabled: bool = False
    running: bool = False
    last_pull_at: Optional[float] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    next_pull_at: Optional[float] = None
    total_pulled: int = 0
    total_pending: int = 0
    started_at: Optional[float] = None
    pid: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PendingEntry:
    """pending.jsonl 单行结构."""
    mail_id: str
    state: str = STATE_NEW
    queued_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    context_id: Optional[str] = None
    error: Optional[str] = None
    consumer: Optional[str] = None  # 哪个消费者在处理 (T2 MailOrchestrator)
    attempts: int = 0  # D-P0.4: 失败重试计数
    # P0 标记体系 (方案 D): driver=驱动来源 (email/agent/console/scheduler);
    # source_ref=上游引用 (邮件 message-id / agent 任务 id); 旧行缺省 email/"" 向后兼容
    driver: str = "email"
    source_ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PendingEntry":
        return cls(
            mail_id=d["mail_id"],
            state=d.get("state", STATE_NEW),
            queued_at=d.get("queued_at", time.time()),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
            context_id=d.get("context_id"),
            error=d.get("error"),
            consumer=d.get("consumer"),
            attempts=d.get("attempts", 0),
            driver=d.get("driver") or "email",
            source_ref=d.get("source_ref") or "",
        )


class MailPullerError(Exception):
    """puller 自身错误 (区别于 IMAP/Gmail 返回的 ok=False)."""


class MailPuller:
    """邮件轮询 puller (单例).

    用法:
        puller = MailPuller(root=Path("."))
        puller.start()      # 启动后台线程 (默认 disabled, 仅当配置 enabled 才真跑)
        puller.stop()       # 停止
        puller.poll_once()  # 同步跑一次 (测试用)
    """

    def __init__(
        self,
        root: Optional[Path] = None,
        interval_s: float = DEFAULT_INTERVAL_S,
        limit: int = DEFAULT_LIMIT,
        gmail_settings_path: Optional[Path] = None,
        cred_file_path: Optional[Path] = None,
        mailbox_factory: Optional[Callable[[str, int], Any]] = None,
        max_per_cycle: int = DEFAULT_MAX_PER_CYCLE,
    ):
        self.root = Path(root) if root else Path(".")
        self.interval_s = float(interval_s)
        self.limit = int(limit)
        self.max_per_cycle = int(max_per_cycle)
        self.gmail_settings_path = gmail_settings_path or (self.root / "data" / "gmail_settings.json")
        # 凭据文件路径可注入 (默认走 services.credentials 全局 CRED_FILE)
        self.cred_file_path = cred_file_path or DEFAULT_CRED_FILE
        self.mailbox_dir = self.root / "data" / "mailbox"
        self.puller_dir = self.root / "data" / "mail_puller"
        self.pending_path = self.puller_dir / "pending.jsonl"
        self.state_path = self.puller_dir / "state.json"
        self.lock_path = self.puller_dir / "pending.lock"
        self._factory = mailbox_factory
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()

    # ---- 启停 ----
    def is_enabled(self) -> bool:
        """判断 puller 是否应启用: settings.enabled=true AND 对应 service 凭据存在.

        service 由 gmail_settings.json 的 "service" 决定 (默认 gmail; qq=QQ 邮箱).
        注意: load_credentials 读全局 CRED_FILE; 测试场景可通过 cred_file_path 注入隔离路径.
        """
        if not self.gmail_settings_path.exists():
            return False
        try:
            cfg = json.loads(self.gmail_settings_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not cfg.get("enabled"):
            return False
        # 凭据必须存在 — 支持注入路径 (多账户/测试隔离场景)
        if self._load_cred_for_test(cfg.get("service") or "gmail") is None:
            return False
        return True

    def _load_cred_for_test(self, service: str = "gmail") -> Optional[Dict[str, Any]]:
        """读 service 凭据. 优先用注入的 cred_file_path, 否则走全局 credentials 模块."""
        if self.cred_file_path != DEFAULT_CRED_FILE:
            # 注入路径: 直接读 JSON (与 credentials._load_all 一致)
            if not self.cred_file_path.exists():
                return None
            try:
                data = json.loads(self.cred_file_path.read_text(encoding="utf-8"))
            except Exception:
                return None
            entry = data.get("services", {}).get(service)
            if not entry:
                return None
            return {"service": service, "account": entry.get("account"), "password": "INJECTED", "extra": entry.get("extra", {})}
        return load_credentials(service)

    def start(self) -> Dict[str, Any]:
        """启动后台线程. 已运行则 noop."""
        if self._thread and self._thread.is_alive():
            return {"ok": True, "running": True, "noop": True}
        enabled = self.is_enabled()
        with self._state_lock:
            self._update_state(enabled=enabled, running=True, started_at=time.time(), pid=os.getpid())
        if not enabled:
            log.info("[mail_puller] disabled (settings.enabled=false 或 credentials 缺失); 后台线程 noop")
            self._stop_event.set()  # 立即退
            return {"ok": True, "running": False, "enabled": False, "noop": True}
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="mail_puller", daemon=True)
        self._thread.start()
        return {"ok": True, "running": True, "enabled": True, "interval_s": self.interval_s}

    def stop(self, timeout: float = 5.0) -> Dict[str, Any]:
        """停止后台线程."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
        with self._state_lock:
            self._update_state(running=False)
        return {"ok": True, "running": False}

    def status(self) -> Dict[str, Any]:
        """返回 puller 状态 + pending.jsonl 概览."""
        st = self._read_state()
        pending = self._read_pending()
        by_state: Dict[str, int] = {s: 0 for s in ALL_STATES}
        for e in pending:
            by_state[e.state] = by_state.get(e.state, 0) + 1
        return {
            "state": st.to_dict(),
            "pending": {"total": len(pending), "by_state": by_state},
            "enabled": self.is_enabled(),
        }

    def pending_index(self) -> Dict[str, Dict[str, Any]]:
        """pending.jsonl → {mail_id: 摘要} (P0 控制台徽标, 方案 D driver 标记)."""
        index: Dict[str, Dict[str, Any]] = {}
        for e in self._read_pending():
            index[e.mail_id] = {
                "state": e.state,
                "driver": e.driver,
                "source_ref": e.source_ref,
                "attempts": e.attempts,
                "consumer": e.consumer,
                "context_id": e.context_id,
                "error": e.error,
                "queued_at": e.queued_at,
                "started_at": e.started_at,
                "finished_at": e.finished_at,
            }
        return index

    # ---- 单次拉取 ----
    def poll_once(self) -> Dict[str, Any]:
        """同步跑一次 pull. 成功返回 ok; 失败抛 MailPullerError (含退避计数)."""
        if not self.is_enabled():
            return {"ok": False, "error": "disabled", "noop": True}
        service, host, port = self._read_conn_cfg()
        if self._factory:
            mb = GmailMailbox(mailbox_dir=self.mailbox_dir, host=host, port=port,
                              mailbox_factory=self._factory, service=service)
        else:
            mb = GmailMailbox(mailbox_dir=self.mailbox_dir, host=host, port=port,
                              service=service)
        # connect + sync: GmailMailbox.connect 内部读全局 credentials; 测试用 mock 工厂
        conn = mb.connect()
        if not conn.get("ok"):
            self._on_failure(conn.get("error", "connect failed"))
            return {"ok": False, "error": conn.get("error"), "stage": "connect"}
        try:
            res = mb.sync(limit=self.limit)
        finally:
            mb.disconnect()
        if not res.get("ok"):
            self._on_failure(res.get("error", "sync failed"))
            return {"ok": False, "error": res.get("error"), "stage": "sync"}
        fetched = res.get("fetched", 0)
        # 同步扫描 mailbox dir 找 NEW eml + 追加 pending
        new_entries = 0
        if fetched > 0:
            new_entries = self._enqueue_pending_from_mailbox()
        self._on_success(fetched, new_entries)
        return {
            "ok": True,
            "fetched": fetched,
            "skipped": res.get("skipped", 0),
            "enqueued": new_entries,
            "next_pull_in_s": self.interval_s,
        }

    # ---- 后台 loop ----
    def _loop(self) -> None:
        log.info("[mail_puller] loop started interval=%ss", self.interval_s)
        while not self._stop_event.is_set():
            try:
                reclaimed = self.reclaim_stale()
                if reclaimed:
                    log.info("[mail_puller] reclaimed %d stale lease(s): %s",
                             len(reclaimed), reclaimed)
                self.poll_once()
            except Exception as e:
                log.exception("[mail_puller] poll_once exception: %r", e)
                self._on_failure(repr(e))
            # 等待 (可被 stop 中断)
            wait_s = self._next_wait_seconds()
            log.debug("[mail_puller] sleep %ss", wait_s)
            if self._stop_event.wait(timeout=wait_s):
                break
        log.info("[mail_puller] loop exited")

    def _next_wait_seconds(self) -> float:
        st = self._read_state()
        if st.consecutive_failures <= 0:
            return self.interval_s
        idx = min(st.consecutive_failures - 1, len(BACKOFF_TABLE) - 1)
        return float(BACKOFF_TABLE[idx])

    # ---- pending.jsonl 状态机 ----
    def _enqueue_pending_from_mailbox(self) -> int:
        """扫 mailbox dir 找无 pending 记录的 .eml → 追加 NEW."""
        existing = {e.mail_id for e in self._read_pending()}
        added = 0
        # 文件锁防并发
        with self._file_lock(timeout=5.0):
            new_entries: List[PendingEntry] = []
            for p in sorted(self.mailbox_dir.glob("*.eml")):
                mid = p.stem
                if mid in existing:
                    continue
                # 元数据从 .meta.json 读
                meta_path = p.with_suffix(".meta.json") if p.suffix == ".eml" else self.mailbox_dir / f"{mid}.meta.json"
                meta: Dict[str, Any] = {}
                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                # 跳过历史非 NEW 邮件 (mock 上传或预置 .eml)
                badges = meta.get("badges", []) or []
                if "NEW" not in badges and "GMAIL_PULLED" not in badges:
                    continue
                new_entries.append(PendingEntry(mail_id=mid, state=STATE_NEW,
                                                 driver="email",
                                                 source_ref=str(meta.get("message_id") or "")))
            if new_entries:
                self._append_pending(new_entries)
                added = len(new_entries)
        return added

    def mark_state(self, mail_id: str, new_state: str, **kwargs: Any) -> bool:
        """原子更新 pending.jsonl 中某行的 state. 非法 state 拒绝."""
        if new_state not in ALL_STATES:
            raise MailPullerError(f"invalid state: {new_state}")
        with self._file_lock(timeout=5.0):
            entries = self._read_pending()
            found = False
            for e in entries:
                if e.mail_id == mail_id:
                    e.state = new_state
                    if "context_id" in kwargs:
                        e.context_id = kwargs["context_id"]
                    if "error" in kwargs:
                        e.error = kwargs["error"]
                    if "consumer" in kwargs:
                        e.consumer = kwargs["consumer"]
                    if new_state in (STATE_PROCESSING,) and not e.started_at:
                        e.started_at = time.time()
                    if new_state in (STATE_DONE, STATE_HITL, STATE_BLOCKED, STATE_FAILED, STATE_DEAD):
                        e.finished_at = time.time()
                    found = True
                    break
            if not found:
                return False
            self._write_pending(entries)
            return True

    def claim_next_new(self, consumer: str = "orchestrator") -> Optional[PendingEntry]:
        """原子获取一个 state=NEW 条目 → 改 PROCESSING → 返回; 无则 None."""
        with self._file_lock(timeout=5.0):
            entries = self._read_pending()
            for e in entries:
                if e.state == STATE_NEW:
                    e.state = STATE_PROCESSING
                    e.started_at = time.time()
                    e.consumer = consumer
                    self._write_pending(entries)
                    return e
            return None

    def claim_batch(self, consumer: str = "orchestrator", n: Optional[int] = None) -> List[PendingEntry]:
        """原子认领最多 n (默认 max_per_cycle) 个 NEW → PROCESSING. 返回认领列表."""
        cap = self.max_per_cycle if n is None else int(n)
        if cap <= 0:
            return []
        with self._file_lock(timeout=5.0):
            entries = self._read_pending()
            claimed: List[PendingEntry] = []
            now = time.time()
            for e in entries:
                if len(claimed) >= cap:
                    break
                if e.state == STATE_NEW:
                    e.state = STATE_PROCESSING
                    e.started_at = now
                    e.consumer = consumer
                    claimed.append(e)
            if claimed:
                self._write_pending(entries)
            return claimed

    def fail_with_retry(self, mail_id: str, error: str,
                        max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> str:
        """记一次失败: attempts+1; 未超限 → 重回 NEW (可重试), 超限 → DEAD (死信).

        返回新 state (STATE_NEW / STATE_DEAD); mail_id 不存在返回 STATE_FAILED 之外无意义, 抛错.
        """
        with self._file_lock(timeout=5.0):
            entries = self._read_pending()
            for e in entries:
                if e.mail_id == mail_id:
                    e.attempts = (e.attempts or 0) + 1
                    e.error = error
                    if e.attempts >= max_attempts:
                        e.state = STATE_DEAD
                        e.finished_at = time.time()
                    else:
                        e.state = STATE_NEW
                        e.started_at = None
                        e.finished_at = None
                    self._write_pending(entries)
                    return e.state
            raise MailPullerError(f"mail_id not found in pending: {mail_id}")

    def reclaim_stale(self, lease_timeout_s: float = DEFAULT_LEASE_TIMEOUT_S) -> List[str]:
        """回收卡死租约: PROCESSING 且 started_at 超过 lease_timeout_s → 重回 NEW.

        返回被回收的 mail_id 列表. 用于消费者崩溃后释放未完成的租约.
        """
        with self._file_lock(timeout=5.0):
            entries = self._read_pending()
            now = time.time()
            reclaimed: List[str] = []
            for e in entries:
                if e.state != STATE_PROCESSING:
                    continue
                started = e.started_at or 0
                if now - started > lease_timeout_s:
                    e.state = STATE_NEW
                    e.started_at = None
                    e.consumer = None
                    reclaimed.append(e.mail_id)
            if reclaimed:
                self._write_pending(entries)
            return reclaimed

    def list_by_state(self, state: str) -> List[PendingEntry]:
        return [e for e in self._read_pending() if e.state == state]
    def _read_pending(self) -> List[PendingEntry]:
        if not self.pending_path.exists():
            return []
        out: List[PendingEntry] = []
        try:
            for line in self.pending_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(PendingEntry.from_dict(json.loads(line)))
                except Exception:
                    continue
        except Exception:
            return []
        return out

    def _append_pending(self, entries: List[PendingEntry]) -> None:
        self.puller_dir.mkdir(parents=True, exist_ok=True)
        with self.pending_path.open("a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")

    def _write_pending(self, entries: List[PendingEntry]) -> None:
        """原子写: 临时文件 + rename."""
        self.puller_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.pending_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        os.replace(tmp, self.pending_path)

    def _file_lock(self, timeout: float = 5.0):
        """简单的跨进程文件锁 (flock 不跨 Windows, 用 try/except + sleep fallback)."""
        # Windows 下 fcntl 不可用, 用 try-open-write 实现 best-effort 互斥
        class _Lock:
            def __init__(self, path: Path, timeout: float):
                self.path = path
                self.timeout = timeout
                self.fd: Optional[int] = None

            def __enter__(self):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                deadline = time.time() + self.timeout
                while True:
                    try:
                        self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                        os.write(self.fd, b"locked")
                        return self
                    except FileExistsError:
                        if time.time() > deadline:
                            raise MailPullerError(f"file lock timeout: {self.path}")
                        time.sleep(0.05)

            def __exit__(self, *exc):
                try:
                    if self.fd is not None:
                        os.close(self.fd)
                except Exception:
                    pass
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass

        return _Lock(self.lock_path, timeout)

    # ---- state.json ----
    def _read_state(self) -> PullerState:
        if not self.state_path.exists():
            return PullerState()
        try:
            return PullerState(**json.loads(self.state_path.read_text(encoding="utf-8")))
        except Exception:
            return PullerState()

    def _update_state(self, **kwargs: Any) -> None:
        st = self._read_state()
        for k, v in kwargs.items():
            setattr(st, k, v)
        self.puller_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    # ---- 成功 / 失败计数 ----
    def _on_success(self, fetched: int, enqueued: int) -> None:
        st = self._read_state()
        with self._state_lock:
            self._update_state(
                last_pull_at=time.time(),
                last_error=None,
                consecutive_failures=0,
                next_pull_at=time.time() + self.interval_s,
                total_pulled=st.total_pulled + fetched,
                total_pending=st.total_pending + enqueued,
            )

    def _on_failure(self, err: str) -> None:
        st = self._read_state()
        new_failures = st.consecutive_failures + 1
        idx = min(new_failures - 1, len(BACKOFF_TABLE) - 1)
        next_wait = BACKOFF_TABLE[idx]
        with self._state_lock:
            self._update_state(
                last_pull_at=time.time(),
                last_error=err,
                consecutive_failures=new_failures,
                next_pull_at=time.time() + next_wait,
            )
        log.warning("[mail_puller] failure #%d, next in %ss: %s", new_failures, next_wait, err)

    # ---- 内部 ----
    def _read_conn_cfg(self) -> tuple[str, str, int]:
        """读 (service, host, port). service 默认 gmail; qq 默认 imap.qq.com."""
        service = "gmail"
        host = "imap.gmail.com"
        port = 993
        if self.gmail_settings_path.exists():
            try:
                cfg = json.loads(self.gmail_settings_path.read_text(encoding="utf-8"))
                service = cfg.get("service") or "gmail"
                host = cfg.get("host", host) or host
                port = int(cfg.get("port", port) or port)
            except Exception:
                pass
        if service == "qq" and host == "imap.gmail.com":
            host = "imap.qq.com"
        return service, host, port


# 单例
_global: Optional[MailPuller] = None


def get_puller(root: Optional[Path] = None, **kwargs: Any) -> MailPuller:
    global _global
    if _global is None:
        _global = MailPuller(root=root, **kwargs)
    return _global


def reset_global() -> None:
    global _global
    if _global is not None:
        try:
            _global.stop()
        except Exception:
            pass
    _global = None
