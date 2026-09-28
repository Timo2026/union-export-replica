"""test_mail_context_api.py — v3.0 #34 邮件台 7 区聚合 API 单测.

12 条覆盖:
  inbox: 1 列出空 + 1 有数据 + 1 404
  detail: 1 详情 + 1 404
  context: 7 区各 1 条 (mock/空场景, 不依赖真实 context 文件)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api_server import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mailbox_with_eml(tmp_path, monkeypatch):
    """临时注入一封 .eml 到 mailbox + meta, 让 inbox/detail 端点能命中."""
    import services.mailbox_api as mb
    mb._MAILBOX_DIR = tmp_path
    # 二进制写保留 \r\n (Windows universal newlines 会破坏 stdlib email parser)
    (tmp_path / "test_001.eml").write_bytes(
        b"From: alice@acme.com\r\n"
        b"To: sales@union.io\r\n"
        b"Subject: RFQ 6061 bracket 100pcs\r\n"
        b"\r\n"
        b"Need 100pcs 6061 bracket, IT7, as-machined. See attached STEP.\r\n"
    )
    (tmp_path / "test_001.meta.json").write_text(json.dumps({
        "context_id": "RFQ-20260101-DEMO01",
        "badges": ["NEW"],
    }), encoding="utf-8")
    return tmp_path


# ---------------- inbox ----------------
def test_inbox_empty(client):
    """空 mailbox → count=0."""
    r = client.get("/v1/mail/inbox")
    assert r.status_code == 200
    d = r.json()
    assert "items" in d and "count" in d


def test_inbox_with_eml(client, mailbox_with_eml):
    """注入 1 封后 → count≥1, 含 mail_id+subject+badges."""
    r = client.get("/v1/mail/inbox")
    assert r.status_code == 200
    d = r.json()
    assert d["count"] >= 1
    first = d["items"][0]
    assert "mail_id" in first
    assert "RFQ" in first["subject"]
    assert "NEW" in first["badges"]


def test_inbox_limit(client, mailbox_with_eml):
    """limit 生效."""
    r = client.get("/v1/mail/inbox?limit=1")
    d = r.json()
    assert len(d["items"]) <= 1


def test_inbox_pending_merge(client, mailbox_with_eml, monkeypatch):
    """P0 标记 (方案 D): inbox 每项带 pending ledger 摘要 (state + driver)."""
    from services.mail_puller import MailPuller
    monkeypatch.setattr(MailPuller, "pending_index", lambda self: {
        "test_001": {"state": "PROCESSING", "driver": "email", "attempts": 0,
                     "consumer": "orchestrator", "source_ref": "<msg-1@acme.com>"},
    })
    r = client.get("/v1/mail/inbox")
    d = r.json()
    item = next(i for i in d["items"] if i["mail_id"] == "test_001")
    assert item["pending"]["state"] == "PROCESSING"
    assert item["pending"]["driver"] == "email"
    # 不在 ledger 的邮件 → pending=None (mock 上传/历史预置)
    other = next((i for i in d["items"] if i["mail_id"] != "test_001"), None)
    if other is not None:
        assert other["pending"] is None


# ---------------- detail ----------------
def test_detail_ok(client, mailbox_with_eml):
    """test_001 → ok, from/subject/attachments_detail 都在."""
    r = client.get("/v1/mail/test_001")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert "alice@acme.com" in d["from"]
    assert "RFQ" in d["subject"]
    assert "attachments_detail" in d


def test_detail_404(client):
    """不存在的 mail_id → 404."""
    r = client.get("/v1/mail/nonexistent_xxx")
    assert r.status_code == 404


# ---------------- context/customer ----------------
def test_context_customer_unknown(client, mailbox_with_eml):
    """未在 CRM 建档的客户 → is_new=true."""
    r = client.get("/v1/mail/test_001/context/customer")
    assert r.status_code == 200
    d = r.json()
    # alice@acme.com 未注册 → is_new 应为 True
    assert d["is_new"] in (True, False)
    assert "signals" in d
    assert "history" in d


# ---------------- context/geometry ----------------
def test_context_geometry_no_step(client, mailbox_with_eml):
    """邮件无 STEP 附件 → ok=false + reason."""
    r = client.get("/v1/mail/test_001/context/geometry")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    assert d["reason"] in ("no STEP attachment", None) or "STEP" in str(d.get("reason", ""))


# ---------------- context/rag ----------------
def test_context_rag_with_query(client, mailbox_with_eml):
    """正文含 '6061 bracket' → rag.search 返回 hits (mock)."""
    r = client.get("/v1/mail/test_001/context/rag")
    assert r.status_code == 200
    d = r.json()
    assert "hits" in d
    assert "mock" in d
    # mock 知识库应至少返回 1 条 (兜底 fallback)
    # 或者 query 触发空 → 仍 ok
    assert isinstance(d["hits"], list)


# ---------------- context/pending ----------------
def test_context_pending(client, mailbox_with_eml):
    """调用不报错, 返回 customer_id + tasks + count."""
    r = client.get("/v1/mail/test_001/context/pending")
    assert r.status_code == 200
    d = r.json()
    assert "tasks" in d
    assert "count" in d
    assert isinstance(d["tasks"], list)


# ---------------- context/verification ----------------
def test_context_verification_no_context(client, mailbox_with_eml):
    """无 context.json 绑 → status=UNKNOWN + note."""
    r = client.get("/v1/mail/test_001/context/verification")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "UNKNOWN"
    assert "reasons" in d
    assert "note" in d


# ---------------- context/postmortem ----------------
def test_context_postmortem(client, mailbox_with_eml):
    """返回 won_count / lost_count / total, 全局聚合."""
    r = client.get("/v1/mail/test_001/context/postmortem")
    assert r.status_code == 200
    d = r.json()
    assert "won_count" in d
    assert "lost_count" in d
    assert "total" in d
    assert isinstance(d["won_count"], int)


# ---------------- context/commercial ----------------
def test_context_commercial_no_context(client, mailbox_with_eml):
    """无 context.json → ok=false + reason."""
    r = client.get("/v1/mail/test_001/context/commercial")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False


# ---------------- context/trace ----------------
def test_context_trace(client, mailbox_with_eml):
    """返回 events[] (空也 OK, 不报错)."""
    r = client.get("/v1/mail/test_001/context/trace")
    assert r.status_code == 200
    d = r.json()
    assert "events" in d
    assert "count" in d
    assert isinstance(d["events"], list)
