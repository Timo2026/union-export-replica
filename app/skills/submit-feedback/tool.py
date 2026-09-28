"""submit_feedback — 写入 feedback_store (v2.4.0)."""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, type: str = "other", title: str = "", body: str = "",
        email: str = "", honeypot: str = "", source: str = "skill_dispatcher",
        ip: str = "skill", **kwargs) -> Dict[str, Any]:
    from services import feedback_store as fs
    payload = {
        "type": type or "other",
        "title": title,
        "body": body,
        "email": email,
        "honeypot": honeypot,
        "source": source,
    }
    res = fs.submit(payload, ip=ip, user_agent="skill-dispatcher/3.0")
    if not res.get("ok"):
        return {"ok": False, "skill": "submit_feedback", "error": res.get("error", "submit failed")}
    return {
        "ok": True,
        "skill": "submit_feedback",
        "iron_rule": "deterministic",
        "id": res.get("id"),
        "created_at": res.get("created_at"),
        "_source": "services.feedback_store",
    }
