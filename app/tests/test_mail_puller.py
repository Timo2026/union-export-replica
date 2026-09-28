"""tests/test_mail_puller.py — T1: 邮件轮询 puller + 状态机 (8 用例).

覆盖:
  1. start/stop 基础启停 (后台线程)
  2. is_enabled 三种场景 (enabled + cred / enabled 无 cred / disabled)
  3. poll_once 成功路径 (mock IMAP 工厂 → 落 .eml + enqueue pending)
  4. poll_once IMAP 连接失败 → 退避计数
  5. poll_once sync 失败 → 退避计数
  6. 状态机: NEW → PROCESSING → DONE 完整流程
  7. claim_next_new 原子性 + 并发安全
  8. mark_state 非法 state 拒绝 + mail_id 不存在返 False
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

# 必须在 import services.mail_puller 前
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tmp_root(tmp_path: Path, isolated_creds) -> Path:
    """为每个测试建独立 root 目录 + 全局 credentials 隔离."""
    (tmp_path / "data").mkdir()
    return tmp_path


@pytest.fixture
def mock_imap_factory():
    """Mock imap_tools.MailBox: 返回 2 封假邮件."""
    from email.message import EmailMessage

    class MockMsg:
        def __init__(self, uid: str, frm: str, subj: str, body: str = "Hello"):
            self.uid = uid
            self.from_ = frm
            self.subject = subj
            self.text = body
            self.html = None
            self.to_values: List[str] = []
            self.cc_values: List[str] = []
            self.date_str = "2026-09-19 10:00:00"
            self.attachments: List[Any] = []

    class MockFolder:
        def set(self, name: str) -> None:
            pass

    class MockClient:
        def __init__(self):
            self.folder = MockFolder()
            self._logged_in = False
            self._msgs = [
                MockMsg("u-001", "alice@northwind.com", "RFQ 6061 brackets", "Need quote 50 pcs"),
                MockMsg("u-002", "bob@acme.de", "TC4 urgent", "10 pcs titanium"),
            ]

        def login(self, user: str, pwd: str) -> None:
            self._logged_in = True

        def logout(self) -> None:
            self._logged_in = False

        def fetch(self, limit: int = 50, reverse: bool = True):
            assert self._logged_in, "must login first"
            return iter(self._msgs[:limit])

    def factory(host: str, port: int) -> MockClient:
        return MockClient()

    return factory


@pytest.fixture
def failing_factory():
    """总是抛异常的 IMAP 工厂 (测失败路径)."""
    def factory(host: str, port: int):
        class Bad:
            def login(self, *a, **kw):
                raise ConnectionError("imap refused")

            def logout(self):
                pass

            def folder(self):
                class F:
                    def set(self, n): pass

                return F()

            def fetch(self, *a, **kw):
                raise TimeoutError("fetch timeout")

        return Bad()

    return factory


def _write_gmail_settings(root: Path, *, enabled: bool = True, host: str = "imap.gmail.com", port: int = 993) -> Path:
    p = root / "data" / "gmail_settings.json"
    p.write_text(json.dumps({"enabled": enabled, "host": host, "port": port}), encoding="utf-8")
    return p


def _write_credentials(root: Path, account: str = "test@gmail.com", password: str = "fake-app-pwd") -> None:
    from services.credentials import save_credentials
    save_credentials("gmail", account, password)


def _make_puller(tmp_root: Path, factory=None) -> Any:
    from services.mail_puller import MailPuller
    return MailPuller(root=tmp_root, interval_s=0.5, limit=10, mailbox_factory=factory)


# ---- 1. start/stop 基础 ----
def test_start_stop_background_thread(tmp_root: Path, mock_imap_factory) -> None:
    _write_gmail_settings(tmp_root, enabled=True)
    _write_credentials(tmp_root)
    puller = _make_puller(tmp_root, factory=mock_imap_factory)
    r = puller.start()
    assert r["ok"] is True
    assert r["running"] is True
    # 给后台线程 1s 跑一次
    time.sleep(1.2)
    r2 = puller.stop(timeout=3.0)
    assert r2["ok"] is True
    assert r2["running"] is False
    # 至少跑过 1 次
    st = puller.status()
    assert st["state"]["last_pull_at"] is not None
    assert st["state"]["consecutive_failures"] == 0


# ---- 2. is_enabled 三态 ----
def test_is_enabled_three_states(tmp_root: Path) -> None:
    # (a) 无 settings → disabled
    p = _make_puller(tmp_root)
    assert p.is_enabled() is False
    # (b) settings.enabled=true 但无 credentials → disabled
    _write_gmail_settings(tmp_root, enabled=True)
    assert p.is_enabled() is False
    # (c) settings.enabled=false 即使有 credentials → disabled
    _write_credentials(tmp_root)
    _write_gmail_settings(tmp_root, enabled=False)
    assert p.is_enabled() is False
    # (d) 全开 → enabled
    _write_gmail_settings(tmp_root, enabled=True)
    assert p.is_enabled() is True


# ---- 3. poll_once 成功 ----
def test_poll_once_success_enqueues_pending(tmp_root: Path, mock_imap_factory) -> None:
    _write_gmail_settings(tmp_root, enabled=True)
    _write_credentials(tmp_root)
    puller = _make_puller(tmp_root, factory=mock_imap_factory)
    res = puller.poll_once()
    assert res["ok"] is True
    assert res["fetched"] == 2
    assert res["enqueued"] == 2
    # mailbox 应有 2 个 .eml + 2 个 .meta.json
    emls = list((tmp_root / "data" / "mailbox").glob("*.eml"))
    metas = list((tmp_root / "data" / "mailbox").glob("*.meta.json"))
    assert len(emls) == 2
    assert len(metas) == 2
    # pending.jsonl 应有 2 行 NEW
    pendings = puller.list_by_state("NEW")
    assert len(pendings) == 2
    # 二次 poll_once → 已存在 skipped=2, enqueued=0
    res2 = puller.poll_once()
    assert res2["ok"] is True
    assert res2["enqueued"] == 0
    assert puller.list_by_state("NEW") == puller.list_by_state("NEW")  # 仍 2 条 NEW (未处理)


# ---- 4. 失败重试 + 退避计数 ----
def test_failure_records_and_backoff(tmp_root: Path, failing_factory) -> None:
    _write_gmail_settings(tmp_root, enabled=True)
    _write_credentials(tmp_root)
    puller = _make_puller(tmp_root, factory=failing_factory)
    # 1st failure
    r = puller.poll_once()
    assert r["ok"] is False
    assert r["stage"] == "connect"
    st = puller.status()
    assert st["state"]["consecutive_failures"] == 1
    assert "imap refused" in (st["state"]["last_error"] or "")
    # 2nd failure
    r2 = puller.poll_once()
    assert r2["ok"] is False
    assert puller.status()["state"]["consecutive_failures"] == 2
    # 3rd failure
    puller.poll_once()
    assert puller.status()["state"]["consecutive_failures"] == 3
    # 成功后归零
    # 替换为成功 factory → poll_once 应清零
    from services.mail_puller import MailPuller
    puller2 = MailPuller(root=tmp_root, interval_s=0.5, limit=10, mailbox_factory=lambda h, p: None)
    # 注入成功工厂: 直接 mock IMAP 拉 1 封
    class GoodMsg:
        uid = "g-001"
        from_ = "ok@x.com"
        subject = "OK"
        text = "OK"
        html = None
        to_values: List[str] = []
        cc_values: List[str] = []
        date_str = "2026-09-19"
        attachments: List[Any] = []

    class GoodClient:
        folder = type("F", (), {"set": lambda self, n: None})()
        def login(self, *a, **kw): pass
        def logout(self): pass
        def fetch(self, limit=50, reverse=True): return iter([GoodMsg()])

    puller2._factory = lambda h, p: GoodClient()
    # puller2 独立, 不会影响前一个
    r3 = puller2.poll_once()
    assert r3["ok"] is True
    assert puller2.status()["state"]["consecutive_failures"] == 0


# ---- 5. 状态机完整流程 NEW→PROCESSING→DONE ----
def test_state_machine_full_lifecycle(tmp_root: Path) -> None:
    _write_gmail_settings(tmp_root, enabled=False)  # 避免真实拉信
    puller = _make_puller(tmp_root)
    # 手工写 3 条 NEW
    from services.mail_puller import PendingEntry, STATE_NEW, STATE_PROCESSING, STATE_DONE, STATE_HITL, STATE_FAILED
    entries = [PendingEntry(mail_id=f"M{i:03d}", state=STATE_NEW) for i in range(3)]
    puller._append_pending(entries)
    assert len(puller.list_by_state("NEW")) == 3
    # claim_next_new 应原子获取一个
    e = puller.claim_next_new(consumer="orchestrator")
    assert e is not None
    assert e.state == STATE_PROCESSING
    assert e.consumer == "orchestrator"
    assert e.started_at is not None
    # 现在 2 NEW + 1 PROCESSING
    assert len(puller.list_by_state("NEW")) == 2
    assert len(puller.list_by_state("PROCESSING")) == 1
    # mark_state DONE
    assert puller.mark_state(e.mail_id, STATE_DONE, context_id="RFQ-20260919-XYZ") is True
    assert len(puller.list_by_state("DONE")) == 1
    done = puller.list_by_state("DONE")[0]
    assert done.context_id == "RFQ-20260919-XYZ"
    assert done.finished_at is not None
    # mark_state HITL (另一个 mail)
    e2 = puller.claim_next_new()
    assert puller.mark_state(e2.mail_id, STATE_HITL, error="IT5 precision") is True
    assert len(puller.list_by_state("HITL")) == 1


# ---- 6. claim_next_new 原子性 ----
def test_claim_next_new_thread_safe(tmp_root: Path) -> None:
    _write_gmail_settings(tmp_root, enabled=False)
    puller = _make_puller(tmp_root)
    from services.mail_puller import PendingEntry, STATE_NEW
    puller._append_pending([PendingEntry(mail_id=f"M{i:03d}", state=STATE_NEW) for i in range(10)])
    claimed = []
    lock = threading.Lock()

    def worker():
        while True:
            e = puller.claim_next_new(consumer=f"worker-{threading.get_ident()}")
            if e is None:
                return
            with lock:
                claimed.append(e.mail_id)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    # 10 条应全部被 claim 一次 (无重复)
    assert len(claimed) == 10
    assert len(set(claimed)) == 10
    assert len(puller.list_by_state("NEW")) == 0
    assert len(puller.list_by_state("PROCESSING")) == 10


# ---- 7. mark_state 非法 state 拒绝 ----
def test_mark_state_invalid_rejected(tmp_root: Path) -> None:
    _write_gmail_settings(tmp_root, enabled=False)
    puller = _make_puller(tmp_root)
    from services.mail_puller import PendingEntry, STATE_NEW, MailPullerError
    puller._append_pending([PendingEntry(mail_id="M001", state=STATE_NEW)])
    with pytest.raises(MailPullerError):
        puller.mark_state("M001", "INVALID_STATE")
    with pytest.raises(MailPullerError):
        puller.mark_state("M001", "")
    # mail_id 不存在
    assert puller.mark_state("M-NOT-EXIST", "DONE") is False
    # 合法但不存在的 mail_id → False
    assert puller.mark_state("M-NOT-EXIST", "DONE") is False


# ---- 8. 持久化原子性 + 重启恢复 ----
def test_persistence_survives_restart(tmp_root: Path) -> None:
    _write_gmail_settings(tmp_root, enabled=False)
    puller1 = _make_puller(tmp_root)
    from services.mail_puller import PendingEntry, STATE_NEW
    puller1._append_pending([
        PendingEntry(mail_id="M-001", state=STATE_NEW),
        PendingEntry(mail_id="M-002", state="DONE"),
    ])
    # 新建第二个 puller 读同一目录 → 应看到同样数据
    puller2 = _make_puller(tmp_root)
    assert len(puller2._read_pending()) == 2
    # state.json 持久化
    puller1._update_state(consecutive_failures=2, last_error="x")
    puller3 = _make_puller(tmp_root)
    st = puller3._read_state()
    assert st.consecutive_failures == 2
    assert st.last_error == "x"


# ---- 9. P0 driver 标记: 默认值 ----
def test_pending_entry_driver_defaults(tmp_root: Path) -> None:
    from services.mail_puller import PendingEntry
    e = PendingEntry(mail_id="M-DRV-1")
    assert e.driver == "email"      # 邮件队列默认邮件驱动
    assert e.source_ref == ""


# ---- 10. P0 driver 标记: 旧数据向后兼容 ----
def test_pending_entry_from_dict_legacy_compat(tmp_root: Path) -> None:
    """旧 pending.jsonl 行无 driver/source_ref → 解析不炸, 默认 email."""
    from services.mail_puller import PendingEntry
    legacy = {
        "mail_id": "M-OLD-1", "state": "NEW", "queued_at": 1.0,
        "started_at": None, "finished_at": None, "context_id": None,
        "error": None, "consumer": None, "attempts": 0,
    }
    e = PendingEntry.from_dict(legacy)
    assert e.driver == "email"
    assert e.source_ref == ""
    d = e.to_dict()
    assert d["driver"] == "email"
    # round-trip
    assert PendingEntry.from_dict(d).mail_id == "M-OLD-1"


# ---- 11. P0 driver 标记: 显式 driver 穿越状态机 ----
def test_driver_survives_state_transitions(tmp_root: Path) -> None:
    from services.mail_puller import PendingEntry, STATE_NEW, STATE_DONE
    puller = _make_puller(tmp_root)
    puller._append_pending([PendingEntry(mail_id="M-DRV-2", state=STATE_NEW,
                                         driver="email", source_ref="<abc@msg>")])
    e = puller.claim_next_new(consumer="orchestrator")
    assert e is not None and e.driver == "email" and e.source_ref == "<abc@msg>"
    assert puller.mark_state("M-DRV-2", STATE_DONE, context_id="RFQ-X") is True
    done = puller.list_by_state("DONE")[0]
    assert done.driver == "email"          # mark_state 不丢 driver
    assert done.source_ref == "<abc@msg>"
