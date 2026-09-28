"""test_qq_mailbox.py — QQ 邮箱 IMAP 收信接入 (service provider 泛化).

覆盖 (mock imap 工厂, 不真连):
  1) GmailMailbox(service="qq") 只认 "qq" 凭据; 仅有 gmail 凭据 → connect 失败
  2) qq sync → mail_id 前缀 "qq_", meta source="qq-imap", badge "QQ_PULLED"
  3) puller settings service="qq" → is_enabled 跟 qq 凭据走
  4) puller poll_once(qq) → 落 qq_ 前缀 eml + enqueued
  5) 回归守卫: 不传 service → 默认 gmail 行为不变

铁律①: 授权码不落测试/代码; 全部用假凭据.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

import pytest

from services import credentials as cred_mod
from services import gmail_imap as gim


class _MockMsg:
    def __init__(self, uid: str, frm: str, subj: str):
        self.uid = uid
        self.from_ = frm
        self.subject = subj
        self.text = "need quote"
        self.html = None
        self.to_values: List[str] = []
        self.cc_values: List[str] = []
        self.date_str = "2026-09-19 10:00:00"
        self.attachments: List[Any] = []


class _MockClient:
    def __init__(self, msgs):
        self._msgs = msgs
        self._logged_in = False

        class F:
            def set(self, name):
                pass

        self.folder = F()

    def login(self, user, pwd):
        self._logged_in = True

    def logout(self):
        pass

    def fetch(self, limit=50, reverse=True):
        assert self._logged_in, "must login first"
        return iter(self._msgs[:limit])


def _factory(msgs):
    def f(host, port):
        return _MockClient(msgs)
    return f


@pytest.fixture
def iso(tmp_path, isolated_creds):
    """独立 root + 全局凭据隔离 (isolated_creds 已清空/还原 data/credentials.json)."""
    (tmp_path / "data").mkdir()
    gim.reset_global()
    return tmp_path


# ---- 1) service=qq 只认 qq 凭据 ----
def test_qq_connect_requires_qq_credentials(iso):
    """仅存 gmail 凭据时, service=qq connect 必须失败 (不回落 gmail)."""
    cred_mod.save_credentials("gmail", "someone@gmail.com", "fake-gmail-app-pwd")
    mb = gim.GmailMailbox(
        mailbox_dir=iso, service="qq", host="imap.qq.com", port=993,
        mailbox_factory=_factory([]),
    )
    r = mb.connect()
    assert r["ok"] is False
    assert "no credentials" in r["error"].lower()


def test_qq_connect_with_qq_credentials(iso):
    cred_mod.save_credentials("qq", "tester@qq.com", "fake-qq-authcode")
    mb = gim.GmailMailbox(
        mailbox_dir=iso, service="qq", host="imap.qq.com", port=993,
        mailbox_factory=_factory([]),
    )
    r = mb.connect()
    assert r["ok"] is True
    assert r["account"] == "tester@qq.com"
    assert r["host"] == "imap.qq.com"
    assert r["port"] == 993
    mb.disconnect()


# ---- 2) qq sync 前缀 / source / badge ----
def test_qq_sync_prefix_source_badge(iso):
    cred_mod.save_credentials("qq", "tester@qq.com", "fake-qq-authcode")
    msgs = [_MockMsg("u-2001", "buyer@factory.cn", "RFQ 6061")]
    mb = gim.GmailMailbox(
        mailbox_dir=iso, service="qq", host="imap.qq.com", port=993,
        mailbox_factory=_factory(msgs),
    )
    assert mb.connect()["ok"] is True
    r = mb.sync(limit=10)
    assert r["ok"] is True and r["fetched"] == 1
    metas = list(iso.glob("qq_*.meta.json"))
    assert len(metas) == 1, "mail_id 必须以 qq_ 前缀落盘"
    meta = json.loads(metas[0].read_text(encoding="utf-8"))
    assert meta["source"] == "qq-imap"
    assert "QQ_PULLED" in meta["badges"]
    assert list(iso.glob("qq_*.eml"))


# ---- 3/4) puller service=qq ----
def _write_settings(root: Path, service: str) -> None:
    (root / "data" / "gmail_settings.json").write_text(
        json.dumps({"enabled": True, "service": service,
                    "host": "imap.qq.com" if service == "qq" else "imap.gmail.com",
                    "port": 993}),
        encoding="utf-8",
    )


def _make_puller(root: Path, msgs):
    from services.mail_puller import MailPuller
    return MailPuller(root=root, interval_s=0.5, limit=10,
                      mailbox_factory=_factory(msgs))


def test_puller_is_enabled_uses_qq_service(iso):
    _write_settings(iso, "qq")
    puller = _make_puller(iso, [])
    assert puller.is_enabled() is False  # 无 qq 凭据
    cred_mod.save_credentials("gmail", "g@gmail.com", "fake")
    assert puller.is_enabled() is False  # 只有 gmail 凭据也不行
    cred_mod.save_credentials("qq", "tester@qq.com", "fake-qq-authcode")
    assert puller.is_enabled() is True


def test_puller_poll_once_qq_prefix(iso):
    _write_settings(iso, "qq")
    cred_mod.save_credentials("qq", "tester@qq.com", "fake-qq-authcode")
    msgs = [_MockMsg("u-3001", "buyer@factory.cn", "PO 补报价"),
            _MockMsg("u-3002", "pm@works.com", "图纸确认")]
    puller = _make_puller(iso, msgs)
    r = puller.poll_once()
    assert r["ok"] is True, r
    assert r["fetched"] == 2
    emls = list((iso / "data" / "mailbox").glob("qq_*.eml"))
    assert len(emls) == 2
    pending = puller._read_pending()
    assert len(pending) == 2


# ---- 5) 回归守卫: 默认仍是 gmail 行为 ----
def test_default_service_stays_gmail(iso):
    cred_mod.save_credentials("gmail", "alice@gmail.com", "fake-gmail-app-pwd")
    msgs = [_MockMsg("u-4001", "x@y.com", "hello")]
    mb = gim.GmailMailbox(
        mailbox_dir=iso, mailbox_factory=_factory(msgs),
    )
    assert mb.connect()["ok"] is True
    r = mb.sync(limit=10)
    assert r["ok"] is True
    assert list(iso.glob("gmail_*.meta.json"))


# ---- 6) 真机 bug 回归: imap_tools 的 to_values 是 EmailAddress 对象, 不是 str ----
def test_sync_handles_email_address_objects(iso):
    """QQ 真信触发过 TypeError('expected str instance, EmailAddress found') — 必须能落盘."""
    # imap_tools 是可选依赖 (services/gmail_imap.py 懒加载); 未装则该模态整条链路不可用, skip 而非报错
    imap_tools = pytest.importorskip(
        "imap_tools", reason="imap-tools 未安装 (可选依赖); pip install imap-tools 后本回归用例生效")
    EmailAddress = imap_tools.EmailAddress

    cred_mod.save_credentials("qq", "tester@qq.com", "fake-qq-authcode")
    msg = _MockMsg("u-5001", "buyer@factory.cn", "PO 报价")
    msg.to_values = [EmailAddress("", "buyer@example.com")]
    msg.cc_values = [EmailAddress("cc", "pm@works.com")]
    mb = gim.GmailMailbox(
        mailbox_dir=iso, service="qq", host="imap.qq.com", port=993,
        mailbox_factory=_factory([msg]),
    )
    assert mb.connect()["ok"] is True
    r = mb.sync(limit=10)
    assert r["ok"] is True, r
    assert r["fetched"] == 1
    eml = next(iso.glob("qq_*.eml"))
    text = eml.read_text(encoding="utf-8", errors="ignore")
    assert "buyer@example.com" in text
    assert "pm@works.com" in text


# ---- 7) 真机 bug 回归: RFC2047 折叠头解码后含 \r\n → email 库抛 ValueError ----
def test_sync_flattens_multiline_headers(iso):
    cred_mod.save_credentials("qq", "tester@qq.com", "fake-qq-authcode")
    msg = _MockMsg("u-6001", "buyer@factory.cn", "=?utf-8?B?5oql5ZGK?=\r\n 6061 bracket")
    msg.from_ = "Buyer <buyer@factory.cn>\r\n"
    mb = gim.GmailMailbox(
        mailbox_dir=iso, service="qq", host="imap.qq.com", port=993,
        mailbox_factory=_factory([msg]),
    )
    assert mb.connect()["ok"] is True
    r = mb.sync(limit=10)
    assert r["ok"] is True, r
    assert r["fetched"] == 1
    eml = next(iso.glob("qq_*.eml"))
    text = eml.read_text(encoding="utf-8", errors="ignore")
    assert "\r\n " not in text.split("\r\n\r\n")[0]  # 头部无残留折行注入
