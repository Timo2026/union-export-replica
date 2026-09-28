"""test_feedback_store.py — v2.4.0 控制台反馈邮箱后端测试.

覆盖:
  - init_db 幂等建表
  - submit: 合法 payload, 短字段拒, 未知 type 拒, bad email 拒, honeypot 拒
  - rate limit: 60s 内 >5 次拒
  - list_recent: 倒序 + status 过滤
  - count_unread: 仅 status='new'
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from services import feedback_store as fs


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """每个测试用一个临时 sqlite, 不污染 data/feedback.sqlite3。"""
    monkeypatch.setattr(fs, "_DB_PATH", tmp_path / "feedback_test.sqlite3")
    fs._ip_buckets.clear()
    yield
    try:
        os.remove(fs._DB_PATH)
    except Exception:
        pass


# ---------- 初始化 ----------

def test_init_db_creates_table(_isolated_db):
    fs.init_db()
    assert fs._DB_PATH.exists()


def test_init_db_idempotent(_isolated_db):
    fs.init_db()
    fs.init_db()  # 不抛
    fs.init_db()


# ---------- submit: 正常路径 ----------

def test_submit_valid_minimal(_isolated_db):
    r = fs.submit({"type": "bug", "title": "示例标题足够长", "body": "我遇到了一个具体问题描述"})
    assert r["ok"] is True
    assert isinstance(r["id"], int) and r["id"] >= 1
    assert "created_at" in r


def test_submit_valid_with_email(_isolated_db):
    r = fs.submit({
        "type": "feature", "title": "希望加 dark mode",
        "body": "目前夜间使用偏亮, 希望加上 light/dark toggle",
        "email": "u@example.com",
    })
    assert r["ok"] is True


def test_submit_all_valid_types(_isolated_db):
    for t in ("bug", "feature", "consult", "other"):
        r = fs.submit({"type": t, "title": f"{t} 标题够长", "body": f"{t} 详细描述够长足够长"})
        assert r["ok"] is True, f"{t} 失败: {r}"


# ---------- submit: 拒绝路径 ----------

def test_submit_rejects_short_title(_isolated_db):
    r = fs.submit({"type": "bug", "title": "abc", "body": "描述足够长足够长足够长"})
    assert r["ok"] is False
    assert "title" in r["error"]


def test_submit_rejects_short_body(_isolated_db):
    r = fs.submit({"type": "bug", "title": "足够长的标题", "body": "太短"})
    assert r["ok"] is False
    assert "body" in r["error"]


def test_submit_rejects_unknown_type(_isolated_db):
    r = fs.submit({"type": "spam", "title": "足够长的标题", "body": "描述足够长足够长足够长"})
    assert r["ok"] is False
    assert "type" in r["error"]


def test_submit_rejects_bad_email(_isolated_db):
    r = fs.submit({"type": "bug", "title": "足够长的标题", "body": "描述足够长足够长足够长",
                   "email": "not-an-email"})
    assert r["ok"] is False
    assert "email" in r["error"]


def test_submit_rejects_honeypot(_isolated_db):
    r = fs.submit({"type": "bug", "title": "足够长的标题", "body": "描述足够长足够长足够长",
                   "honeypot": "i am a bot"})
    assert r["ok"] is False
    assert "honeypot" in r["error"]


def test_submit_rate_limit_blocks_overflow(_isolated_db):
    # 5 次应通过, 第 6 次被拒
    for i in range(fs._RATE_MAX):
        r = fs.submit({"type": "bug", "title": f"标题{i}够长", "body": f"描述{i}足够长足够长足够长"})
        assert r["ok"] is True, f"第{i+1}次: {r}"
    r = fs.submit({"type": "bug", "title": "标题又够长", "body": "描述又足够长足够长足够长"})
    assert r["ok"] is False
    assert "rate" in r["error"].lower()


# ---------- list / count ----------

def test_list_recent_descending(_isolated_db):
    fs.submit({"type": "bug", "title": "第一条足够长", "body": "描述足够长足够长足够长"})
    fs.submit({"type": "feature", "title": "第二条足够长", "body": "描述足够长足够长足够长"})
    items = fs.list_recent(limit=10)
    assert len(items) == 2
    assert items[0]["title"].startswith("第二条")  # 最新在前
    assert items[1]["title"].startswith("第一条")


def test_list_filter_by_status(_isolated_db):
    fs.submit({"type": "bug", "title": "新的足够长", "body": "描述足够长足够长足够长"})
    items_new = fs.list_recent(limit=10, status="new")
    assert all(x["status"] == "new" for x in items_new)
    items_closed = fs.list_recent(limit=10, status="closed")
    assert items_closed == []


def test_count_unread_only_new(_isolated_db):
    assert fs.count_unread() == 0
    fs.submit({"type": "bug", "title": "新增反馈标题够长", "body": "描述足够长足够长足够长"})
    fs.submit({"type": "feature", "title": "再增反馈标题够长", "body": "描述足够长足够长足够长"})
    assert fs.count_unread() == 2


def test_submit_optional_email_none(_isolated_db):
    r = fs.submit({"type": "bug", "title": "无邮箱也允许", "body": "描述足够长足够长足够长"})
    assert r["ok"] is True
    items = fs.list_recent(limit=1)
    assert items[0]["email"] is None


def test_submit_user_agent_truncated(_isolated_db):
    long_ua = "A" * 500
    r = fs.submit({"type": "bug", "title": "标题够长", "body": "描述足够长足够长足够长"},
                  user_agent=long_ua)
    assert r["ok"] is True
    items = fs.list_recent(limit=1)
    assert len(items[0]["user_agent"]) == 200