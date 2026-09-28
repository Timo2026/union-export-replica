"""test_gmail_imap_api.py — v3.0 #41/#43/#47 Gmail IMAP 拉信 + API 端点单测.

8 条覆盖 (凭代码核对, mock imap_tools 不真连):
  GmailMailbox (4):
    1) connect() 无凭据 → ok=False, error="no credentials saved"
    2) connect() 注入 mock factory → login 成功, last_account=account
    3) sync() 拉 2 封新信 → fetched=2, 写 .eml+.meta.json, badges 含 NEW+GMAIL_PULLED
    4) sync() 重复拉 → skipped 正确, fetched=0
  API 端点 (4):
    5) GET /v1/gmail/status 默认 enabled=False
    6) POST /v1/gmail/settings 切 enabled=true
    7) POST /v1/gmail/connect 未启用 → 403
    8) POST /v1/gmail/disconnect 清凭据
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services import credentials as cred_mod
from services import gmail_imap as gim
from services.api_server import app


# ---------- GmailMailbox mock ----------
class _MockMsg:
    def __init__(self, uid, frm, subj, date_str="Wed, 17 Sep 2026 10:00:00 +0800", body="hello", atts=None):
        self.uid = uid
        self.from_ = frm
        self.subject = subj
        self.date_str = date_str
        self.text = body
        self.html = None
        self.attachments = atts or []
    @property
    def to_values(self): return ["sales@union.io"]
    @property
    def cc_values(self): return []


class _MockFolder:
    def __init__(self, msgs): self.msgs = msgs
    def set(self, folder): pass


class _MockMailBox:
    def __init__(self, msgs): self.msgs = msgs; self.logged_in = False; self.folder = _MockFolder(msgs)
    def login(self, account, password): self.logged_in = True; self.account=account
    def logout(self): self.logged_in = False
    def fetch(self, limit=None, reverse=False):
        return iter(self.msgs[:limit] if limit else self.msgs)


@pytest.fixture
def mb_dir(tmp_path, monkeypatch):
    """隔离 mailbox_dir + credentials file."""
    fake_cred = tmp_path / "credentials.json"
    monkeypatch.setattr(cred_mod, "CRED_FILE", fake_cred)
    gim.reset_global()
    return tmp_path


# ---------- GmailMailbox tests ----------
def test_connect_no_credentials(mb_dir):
    """未存凭据 → connect 返回 ok=False, last_error='no credentials saved'."""
    mb = gim.GmailMailbox(mailbox_dir=mb_dir)
    r = mb.connect()
    assert r["ok"] is False
    assert "no credentials" in r["error"].lower()
    assert mb.last_error is not None


def test_connect_with_mock(mb_dir):
    """注入 mock factory → login 成功, last_account 正确."""
    cred_mod.save_credentials("gmail", "alice@gmail.com", "abcd-efgh-ijkl-mnop")
    mb = gim.GmailMailbox(
        mailbox_dir=mb_dir,
        mailbox_factory=lambda host, port: _MockMailBox([]),
    )
    r = mb.connect()
    assert r["ok"] is True
    assert r["account"] == "alice@gmail.com"
    assert r["host"] == "imap.gmail.com"
    assert mb.last_account == "alice@gmail.com"
    mb.disconnect()


def test_sync_writes_eml_and_meta(mb_dir):
    """拉 2 封 → fetched=2, data/mailbox/*.eml + *.meta.json 各 2 个, 含 GMAIL_PULLED badge."""
    cred_mod.save_credentials("gmail", "alice@gmail.com", "abcd-efgh-ijkl-mnop")
    msgs = [
        _MockMsg("100", "alice@gmail.com", "RFQ 6061 bracket"),
        _MockMsg("101", "bob@buyer.com", "Need 50 pcs 304"),
    ]
    mb = gim.GmailMailbox(
        mailbox_dir=mb_dir,
        mailbox_factory=lambda host, port: _MockMailBox(msgs),
    )
    assert mb.connect()["ok"] is True
    r = mb.sync(limit=10)
    assert r["ok"] is True
    assert r["fetched"] == 2
    assert r["skipped"] == 0
    emls = list(mb_dir.glob("*.eml"))
    metas = list(mb_dir.glob("*.meta.json"))
    assert len(emls) == 2 and len(metas) == 2
    # meta 检查 badges
    for m in metas:
        meta = json.loads(m.read_text())
        assert "NEW" in meta["badges"]
        assert "GMAIL_PULLED" in meta["badges"]
        assert meta["source"] == "gmail-imap"
        assert meta["uid"] in ("100", "101")
    mb.disconnect()


def test_sync_idempotent(mb_dir):
    """二次 sync → skipped=2, fetched=0 (幂等)."""
    cred_mod.save_credentials("gmail", "alice@gmail.com", "abcd-efgh-ijkl-mnop")
    msgs = [_MockMsg("200", "alice@gmail.com", "first mail")]
    mb = gim.GmailMailbox(
        mailbox_dir=mb_dir,
        mailbox_factory=lambda host, port: _MockMailBox(msgs),
    )
    assert mb.connect()["ok"] is True
    r1 = mb.sync(limit=10)
    assert r1["ok"] is True and r1["fetched"] == 1
    r2 = mb.sync(limit=10)
    assert r2["ok"] is True and r2["fetched"] == 0
    assert r2["skipped"] == 1
    mb.disconnect()


# ---------- API tests ----------
@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """隔离运行时文件: SETTINGS_FILE + CRED_FILE 重定向 tmp, 不碰仓库真实配置."""
    import services.gmail_api as ga

    monkeypatch.setattr(ga, "SETTINGS_FILE", tmp_path / "gmail_settings.json")
    monkeypatch.setattr(cred_mod, "CRED_FILE", tmp_path / "credentials.json")
    with TestClient(app) as c:
        yield c
    ga._MAILBOX = None


def test_gmail_status_default_disabled(api_client):
    """GET /v1/gmail/status 默认 enabled=False."""
    r = api_client.get("/v1/gmail/status")
    assert r.status_code == 200
    d = r.json()
    assert "settings" in d
    assert d["settings"].get("enabled") is False


def test_gmail_settings_toggle(api_client):
    """POST /v1/gmail/settings 切 enabled=true."""
    r = api_client.post("/v1/gmail/settings", json={"enabled": True})
    assert r.status_code == 200
    d = r.json()
    assert d["saved"] is True
    assert d["settings"]["enabled"] is True
    # 复位
    api_client.post("/v1/gmail/settings", json={"enabled": False})


def test_gmail_connect_403_when_disabled(api_client):
    """未启用时 POST /v1/gmail/connect → 403 'gmail disabled'."""
    api_client.post("/v1/gmail/settings", json={"enabled": False})
    r = api_client.post("/v1/gmail/connect", json={"email": "alice@gmail.com", "app_password": "abcd-efgh-ijkl-mnop"})
    assert r.status_code == 403
    assert "gmail disabled" in r.json()["detail"].lower()


def test_gmail_disconnect_clears(api_client):
    """POST /v1/gmail/disconnect → 200 ok=True, 凭据清空."""
    r = api_client.post("/v1/gmail/disconnect")
    assert r.status_code == 200
    d = r.json()
    assert d.get("ok") is True
    # credentials 列表应空 (或保持空)
    s = api_client.get("/v1/gmail/status").json()
    assert s.get("credentials", {}).get("services", []) == []