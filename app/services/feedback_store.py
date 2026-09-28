"""feedback_store.py — 用户反馈存储 (sqlite).

v2.4.0 控制台反馈邮箱后端。纯 sqlite，schema v1：
  id (autoinc) | created_at | type (bug/feature/consult/other)
  | title | body | email | user_agent | source (webui/email/api)
  | status (new/in_progress/closed) | assigned_to | notes

防滥用:
  - honeypot 字段 (前端不可见) — bot 填了就拒
  - 速率限制: 同 IP 每分钟 ≤ 5 条
  - 必填字段最小长度校验
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ROOT / "data" / "feedback.sqlite3"
_LOCK = Lock()

_VALID_TYPES = {"bug", "feature", "consult", "other"}
_VALID_STATUSES = {"new", "in_progress", "closed"}

# 简易速率限制: 同 IP 时间窗口
_RATE_WINDOW_S = 60
_RATE_MAX = 5
_ip_buckets: Dict[str, List[float]] = {}


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH), timeout=5)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    """幂等建表。"""
    with _LOCK:
        c = _conn()
        try:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    email TEXT,
                    user_agent TEXT,
                    source TEXT NOT NULL DEFAULT 'webui',
                    status TEXT NOT NULL DEFAULT 'new',
                    assigned_to TEXT,
                    notes TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_feedback_status  ON feedback(status);
            """)
            c.commit()
        finally:
            c.close()


def _check_rate(ip: str) -> bool:
    """滑动窗口限流: 60s 内最多 5 次。"""
    now = time.time()
    bucket = _ip_buckets.setdefault(ip, [])
    bucket[:] = [t for t in bucket if now - t < _RATE_WINDOW_S]
    if len(bucket) >= _RATE_MAX:
        return False
    bucket.append(now)
    return True


def submit(payload: Dict[str, Any], *, ip: str = "unknown",
           user_agent: str = "") -> Dict[str, Any]:
    """提交一条反馈。返回 {ok, id} 或 {ok:false, error}。

    payload 字段:
      type, title, body (必填), email (可选), honeypot (必须为空)
    """
    init_db()
    honeypot = (payload.get("honeypot") or "").strip()
    if honeypot:
        return {"ok": False, "error": "honeypot triggered (bot?)"}
    if not _check_rate(ip):
        return {"ok": False, "error": f"rate limited ({_RATE_MAX}/{_RATE_WINDOW_S}s)"}

    typ = (payload.get("type") or "").strip().lower()
    title = (payload.get("title") or "").strip()
    body = (payload.get("body") or "").strip()
    email = (payload.get("email") or "").strip() or None

    if typ not in _VALID_TYPES:
        return {"ok": False, "error": f"type 必须 ∈ {_VALID_TYPES}"}
    if len(title) < 4:
        return {"ok": False, "error": "title 至少 4 字符"}
    if len(body) < 10:
        return {"ok": False, "error": "body 至少 10 字符"}
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        return {"ok": False, "error": "email 格式无效"}

    source = (payload.get("source") or "webui").strip()
    created = time.strftime("%Y-%m-%d %H:%M:%S")

    with _LOCK:
        c = _conn()
        try:
            cur = c.execute(
                "INSERT INTO feedback(created_at,type,title,body,email,user_agent,source) "
                "VALUES (?,?,?,?,?,?,?)",
                (created, typ, title, body, email, user_agent[:200], source))
            new_id = cur.lastrowid
            c.commit()
        finally:
            c.close()
    return {"ok": True, "id": new_id, "created_at": created}


def list_recent(limit: int = 20, status: Optional[str] = None) -> List[Dict[str, Any]]:
    init_db()
    with _LOCK:
        c = _conn()
        try:
            if status and status in _VALID_STATUSES:
                rows = c.execute(
                    "SELECT id,created_at,type,title,body,email,user_agent,status,source "
                    "FROM feedback WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, int(limit))).fetchall()
            else:
                rows = c.execute(
                    "SELECT id,created_at,type,title,body,email,user_agent,status,source "
                    "FROM feedback ORDER BY id DESC LIMIT ?",
                    (int(limit),)).fetchall()
        finally:
            c.close()
    return [dict(r) for r in rows]


def count_unread() -> int:
    init_db()
    with _LOCK:
        c = _conn()
        try:
            row = c.execute("SELECT COUNT(*) AS n FROM feedback WHERE status='new'").fetchone()
        finally:
            c.close()
    return int(row["n"] if row else 0)


if __name__ == "__main__":
    init_db()
    print(json.dumps(list_recent(5), ensure_ascii=False, indent=2))