"""tests/test_egress_gate.py — D-P0.1 集中式发信主闸 (egress kill-switch).

铁律①: 数据不出本机。任何真实外发 (SMTP/IMAP/webhook) 必须过集中闸;
闸默认 DENY, 仅显式 allow (settings.egress 或 env UEA_EGRESS_ALLOW) 才放行。
闸关时即便 per-notifier real_send=True 也强制降级为本地草稿 + 审计。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---- 1. 默认拒绝 ----
def test_default_deny_no_config():
    """无任何配置 → 所有通道默认 DENY (铁律① fail-safe)."""
    from services.egress_gate import check
    for ch in ("smtp", "imap", "webhook"):
        d = check(ch, settings={}, env={})
        assert d.allowed is False, f"{ch} 应默认拒绝"
        assert d.channel == ch
        assert d.reason  # 必须给出拒绝原因


# ---- 2. settings 显式放行单通道 ----
def test_allow_via_settings_channel():
    from services.egress_gate import check
    settings = {"egress": {"allow": True, "channels": {"smtp": True}}}
    assert check("smtp", settings=settings, env={}).allowed is True
    # imap 未显式开 → 仍拒
    assert check("imap", settings=settings, env={}).allowed is False


# ---- 3. settings 总开关 off 即便通道 true 也拒 ----
def test_master_switch_off_overrides_channel():
    from services.egress_gate import check
    settings = {"egress": {"allow": False, "channels": {"smtp": True}}}
    assert check("smtp", settings=settings, env={}).allowed is False


# ---- 4. env 放行指定通道 ----
def test_allow_via_env_specific():
    from services.egress_gate import check
    env = {"UEA_EGRESS_ALLOW": "smtp"}
    assert check("smtp", settings={}, env=env).allowed is True
    assert check("imap", settings={}, env=env).allowed is False


# ---- 5. env all 放行全部 ----
def test_allow_via_env_all():
    from services.egress_gate import check
    env = {"UEA_EGRESS_ALLOW": "all"}
    for ch in ("smtp", "imap", "webhook"):
        assert check(ch, settings={}, env=env).allowed is True


# ---- 6. assert_allowed 拒绝时抛错 ----
def test_assert_allowed_raises_when_denied():
    from services.egress_gate import assert_allowed, EgressBlockedError
    with pytest.raises(EgressBlockedError):
        assert_allowed("smtp", settings={}, env={})
    # 放行时不抛
    assert_allowed("smtp", settings={"egress": {"allow": True, "channels": {"smtp": True}}}, env={})


# ---- 7. EmailNotifier real_send=True 但闸关 → 降级本地草稿, 绝不真发 ----
def test_email_notifier_downgraded_when_gate_closed(tmp_root: Path, monkeypatch):
    monkeypatch.chdir(tmp_root)
    import services.notify.email_notifier as em_mod
    from services.notify.email_notifier import EmailNotifier
    from services.notify.base import NotificationEvent

    # 哨兵: 若真调 SMTP 立即失败 (证明没走真实外发)
    smtp_calls = []

    class _FakeSMTP:
        def __init__(self, *a, **k):
            smtp_calls.append(a)
            raise AssertionError("real SMTP must NOT be called when egress gate closed")

    monkeypatch.setattr(em_mod.smtplib, "SMTP", _FakeSMTP)
    # 强制闸关 (默认即关), real_send=True 试图真发
    monkeypatch.delenv("UEA_EGRESS_ALLOW", raising=False)
    n = EmailNotifier(smtp_host="smtp.example.com", real_send=True)
    e = NotificationEvent(kind="approved", context_id="RFQ-GATE-1",
                          customer="bob", verdict="PASS",
                          quote={"unit_price": 10, "final_price": 100, "currency": "CNY"})
    ok = n.send(e)
    assert ok is True            # 降级成功 (写了本地草稿)
    assert smtp_calls == []      # 真实 SMTP 从未被调用
    # 本地草稿落盘
    drafts = list((tmp_root / "data" / "notifications").glob("approved_RFQ-GATE-1_*.eml"))
    assert len(drafts) >= 1


# ---- 8. 闸开 + real_send=True → 允许走真实 SMTP ----
def test_email_notifier_real_send_when_gate_open(tmp_root: Path, monkeypatch):
    monkeypatch.chdir(tmp_root)
    import services.notify.email_notifier as em_mod
    from services.notify.email_notifier import EmailNotifier
    from services.notify.base import NotificationEvent

    sent = []

    class _FakeSMTP:
        def __init__(self, *a, **k):
            self._a = a
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def starttls(self):
            pass
        def login(self, u, p):
            pass
        def send_message(self, msg):
            sent.append(msg["Subject"])

    monkeypatch.setattr(em_mod.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setenv("UEA_EGRESS_ALLOW", "smtp")
    n = EmailNotifier(smtp_host="smtp.example.com", user="u", password="p", real_send=True)
    e = NotificationEvent(kind="approved", context_id="RFQ-GATE-2", customer="bob",
                          verdict="PASS", quote={"unit_price": 10, "final_price": 100})
    ok = n.send(e)
    assert ok is True
    assert len(sent) == 1  # 闸开 → 真实发送通道被走到


# ---- 9. Slack webhook 闸关 → 不发 HTTP, 返 False ----
def test_slack_blocked_when_gate_closed(tmp_root: Path, monkeypatch):
    monkeypatch.chdir(tmp_root)
    import services.notify.slack as slack_mod
    from services.notify.slack import SlackNotifier
    from services.notify.base import NotificationEvent

    calls = []
    monkeypatch.setattr(slack_mod.urllib.request, "urlopen",
                        lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("must not egress")))
    monkeypatch.delenv("UEA_EGRESS_ALLOW", raising=False)
    n = SlackNotifier(webhook_url="https://hooks.slack.com/x")
    e = NotificationEvent(kind="blocked", context_id="RFQ-SL-1")
    assert n.send(e) is False
    assert calls == []  # urlopen 从未被调


# ---- 10. Telegram webhook 闸关 → 不发 HTTP, 返 False ----
def test_telegram_blocked_when_gate_closed(tmp_root: Path, monkeypatch):
    monkeypatch.chdir(tmp_root)
    import services.notify.telegram as tg_mod
    from services.notify.telegram import TelegramNotifier
    from services.notify.base import NotificationEvent

    calls = []
    monkeypatch.setattr(tg_mod.urllib.request, "urlopen",
                        lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("must not egress")))
    monkeypatch.delenv("UEA_EGRESS_ALLOW", raising=False)
    n = TelegramNotifier(bot_token="tok", chat_id="cid")
    e = NotificationEvent(kind="hitl", context_id="RFQ-TG-1")
    assert n.send(e) is False
    assert calls == []


# ---- 11. Slack 闸开 → 允许 HTTP 外发 ----
def test_slack_allowed_when_gate_open(tmp_root: Path, monkeypatch):
    monkeypatch.chdir(tmp_root)
    import services.notify.slack as slack_mod
    from services.notify.slack import SlackNotifier
    from services.notify.base import NotificationEvent

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    sent = []
    monkeypatch.setattr(slack_mod.urllib.request, "urlopen", lambda *a, **k: sent.append(a) or _Resp())
    monkeypatch.setenv("UEA_EGRESS_ALLOW", "webhook")
    n = SlackNotifier(webhook_url="https://hooks.slack.com/x")
    e = NotificationEvent(kind="blocked", context_id="RFQ-SL-2")
    assert n.send(e) is True
    assert len(sent) == 1
