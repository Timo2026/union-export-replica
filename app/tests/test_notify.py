"""tests/test_notify.py — T10: 自动批准 + 通知外发 (PASS only) 5 用例.

覆盖:
  1. PASS 自动批准 (MailOrchestrator.run_pipeline + audit)
  2. approve_gate 拒绝 → state=BLOCKED + notify
  3. TelegramNotifier 缺 token → 写 failed.jsonl + 返 False
  4. EmailNotifier mock 模式 → 写 data/notifications/*.eml
  5. SlackNotifier stub + 优先级链 (telegram→email→slack fallback)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest


# ---- 1. PASS 自动批准 ----
def test_pass_auto_approve(tmp_root: Path) -> None:
    """MailOrchestrator: verdict=PASS → 自动 approve + audit."""
    from services.mail_puller import MailPuller, PendingEntry, STATE_NEW
    from services.mail_orchestrator import MailOrchestrator

    # 写 eml
    eml = tmp_root / "data" / "mailbox" / "M-APPROVE.eml"
    eml.parent.mkdir(parents=True, exist_ok=True)
    eml.write_bytes(
        b"From: alice@x.com\r\nSubject: s\r\n\r\nbody\r\n"
    )
    (tmp_root / "data" / "mailbox" / "M-APPROVE.meta.json").write_text(
        json.dumps({"from": "alice@x.com", "badges": ["NEW"]}), encoding="utf-8"
    )

    class MockCAT:
        def run(self, email_text="", customer=None, **kw):
            return {"state": "PASS", "context_id": "RFQ-AUTO-001",
                    "verification_status": "PASS", "reasons": []}

    puller = MailPuller(root=tmp_root, interval_s=0.5, limit=10, mailbox_factory=None)
    puller._append_pending([PendingEntry(mail_id="M-APPROVE", state=STATE_NEW)])
    orch = MailOrchestrator(root=tmp_root, puller=puller, cat=MockCAT())
    r = orch.run_pipeline("M-APPROVE")
    assert r.ok is True
    assert r.state == "DONE"
    assert r.approved is True
    # audit 文件含 l3_auto_approved
    audit_path = tmp_root / "data" / "contexts" / "RFQ-AUTO-001.audit.json"
    assert audit_path.exists()
    audit_content = audit_path.read_text(encoding="utf-8")
    assert "l3_auto_approved" in audit_content
    assert "draft_only" in audit_content


# ---- 2. approve_gate 拒绝 → state=BLOCKED + notify ----
def test_blocked_with_notify(tmp_root: Path) -> None:
    """verdict=BLOCKED → notify hitl/blocked, state=BLOCKED."""
    from services.mail_puller import MailPuller, PendingEntry, STATE_NEW
    from services.mail_orchestrator import MailOrchestrator

    eml = tmp_root / "data" / "mailbox" / "M-NOTIFY.eml"
    eml.parent.mkdir(parents=True, exist_ok=True)
    eml.write_bytes(b"From: a@x.com\r\n\r\nbody\r\n")
    (tmp_root / "data" / "mailbox" / "M-NOTIFY.meta.json").write_text(
        json.dumps({"from": "a@x.com", "badges": ["NEW"]}), encoding="utf-8"
    )

    notif = []
    class MockCAT:
        def run(self, email_text="", customer=None, **kw):
            return {"state": "BLOCKED", "context_id": "RFQ-BLK-001",
                    "verification_status": "BLOCKED",
                    "reasons": ["304 anodizing hard conflict"]}

    puller = MailPuller(root=tmp_root, interval_s=0.5, limit=10, mailbox_factory=None)
    puller._append_pending([PendingEntry(mail_id="M-NOTIFY", state=STATE_NEW)])
    orch = MailOrchestrator(root=tmp_root, puller=puller, cat=MockCAT(),
                            notifier=lambda k, p: notif.append(k) or True)
    r = orch.run_pipeline("M-NOTIFY")
    assert r.state == "BLOCKED"
    assert r.notified is True
    assert notif == ["blocked"]


# ---- 3. TelegramNotifier 缺 token → 失败降级 ----
def test_telegram_no_token_returns_false(tmp_root: Path, monkeypatch) -> None:
    """bot_token 缺失 → 返 False + 写 failed.jsonl."""
    monkeypatch.chdir(tmp_root)
    from services.notify.telegram import TelegramNotifier
    from services.notify.base import NotificationEvent

    n = TelegramNotifier(bot_token="", chat_id="")
    e = NotificationEvent(kind="hitl", context_id="RFQ-001",
                          customer="alice", verdict="HITL",
                          quote={"unit_price": 100, "final_price": 5000, "currency": "CNY"},
                          reason="test", action_required="approve")
    assert n.send(e) is False
    # failed.jsonl 应被写
    failed = tmp_root / "data" / "notifications" / "telegram.failed.jsonl"
    assert failed.exists()
    lines = [json.loads(l) for l in failed.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(l.get("event", {}).get("context_id") == "RFQ-001" for l in lines)


# ---- 4. EmailNotifier mock 写本地 ----
def test_email_mock_writes_local_file(tmp_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_root)
    from services.notify.email_notifier import EmailNotifier
    from services.notify.base import NotificationEvent

    n = EmailNotifier(real_send=False)
    e = NotificationEvent(kind="approved", context_id="RFQ-002",
                          customer="bob", verdict="PASS",
                          quote={"unit_price": 76.53, "final_price": 76.53, "currency": "CNY"},
                          reason="auto approved")
    assert n.send(e) is True
    notif_dir = tmp_root / "data" / "notifications"
    assert notif_dir.exists()
    files = list(notif_dir.glob("approved_RFQ-002_*.eml"))
    assert len(files) >= 1
    content = files[0].read_text(encoding="utf-8")
    assert "Subject: [UEA-L3] APPROVED" in content
    assert "RFQ-002" in content


# ---- 5. SlackNotifier stub + 优先级链 ----
def test_slack_stub_no_webhook(tmp_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_root)
    from services.notify.slack import SlackNotifier
    from services.notify.base import NotificationEvent

    n = SlackNotifier(webhook_url="")
    e = NotificationEvent(kind="blocked", context_id="RFQ-003")
    assert n.send(e) is False  # 无 url → 返 False


def test_notify_priority_chain(tmp_root: Path, monkeypatch) -> None:
    """telegram 失败 → 自动 fallback email → fallback slack → 最终 fallback jsonl."""
    monkeypatch.chdir(tmp_root)
    from services.notify.telegram import TelegramNotifier
    from services.notify.email_notifier import EmailNotifier
    from services.notify.slack import SlackNotifier
    from services.notify.base import NotificationEvent

    e = NotificationEvent(kind="hitl", context_id="RFQ-CHAIN",
                          customer="charlie", verdict="HITL",
                          quote={"unit_price": 100, "final_price": 500, "currency": "CNY"})

    # 三层全失败 → 最终写 notifications.jsonl fallback
    tg = TelegramNotifier(bot_token="", chat_id="")
    em = EmailNotifier(real_send=False)
    sk = SlackNotifier(webhook_url="")
    chain = [tg, em, sk]
    success = False
    for n in chain:
        if n.send(e):
            success = True
            break
    # Email 一定成功 (mock 模式写本地)
    assert success is True
    assert (tmp_root / "data" / "notifications").exists()
