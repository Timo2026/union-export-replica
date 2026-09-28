"""reply-draft skill — 委托 services/reply.build_reply (v6.0.0 最小补全)."""
from __future__ import annotations
from typing import Any, Dict


def run(ctx, ctx_dict: Dict[str, Any] = None, verification: Dict[str, Any] = None,
        **kwargs) -> Dict[str, Any]:
    """起草英文外贸回复. 委托 services.reply.build_reply. draft_only 守护."""
    if not ctx_dict or not verification:
        return {"ok": False, "skill": "reply-draft", "iron_rule": "draft_only",
                "error": "ctx_dict and verification required"}
    try:
        from services.reply import build_reply
        draft = build_reply(ctx_dict, verification)
        # 强制 draft_only (铁律③)
        draft["auto_send"] = False
        draft["mode"] = draft.get("mode", "draft_only")
        return {
            "ok": True, "skill": "reply-draft", "iron_rule": "draft_only",
            "subject": draft.get("subject", ""),
            "body": draft.get("body", ""),
            "auto_send": False,
            "mode": "draft_only",
            "_source": "services.reply.build_reply",
        }
    except Exception as e:
        return {"ok": False, "skill": "reply-draft", "iron_rule": "draft_only",
                "error": repr(e)}
