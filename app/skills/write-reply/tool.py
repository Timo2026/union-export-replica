"""write_reply — 英文回复草稿 (draft_only, 不定最终数字承诺)."""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, use_llm: bool = False, **kwargs) -> Dict[str, Any]:
    rfq = ctx.scratch.get("rfq") or {}
    verification = ctx.scratch.get("verification") or {}
    quote = ctx.scratch.get("quote") or {}
    from services.reply import build_reply
    ctx_dict = {
        "rfq": rfq,
        "quote": quote,
        "verification_status": verification.get("verification_status", "PASS"),
        "reasons": verification.get("reasons") or [],
    }
    try:
        out = build_reply(ctx_dict, verification.get("raw") or verification)
    except Exception as e:  # noqa
        return {"ok": False, "skill": "write_reply", "error": repr(e)}
    subject = out.get("subject") or out.get("title") or ""
    body = out.get("body") or out.get("text") or str(out)
    source = "template:services.reply"
    if use_llm:
        planner = ctx.planner
        if planner is None:
            try:
                planner = ctx.get_ctrl().planner
            except Exception:
                planner = None
        if planner is not None and getattr(planner, "online", lambda: False)():
            lr = planner.draft_reply(ctx_dict)
            data = lr.get("data") if isinstance(lr, dict) else None
            if isinstance(data, dict) and (data.get("body") or data.get("text")):
                body = data.get("body") or data.get("text")
                subject = data.get("subject") or subject
                source = lr.get("_source", "live:llm")
            else:
                source = f"{source}|llm_miss:{lr.get('_source') if isinstance(lr, dict) else 'n/a'}"
        else:
            source = f"{source}|MOCK:llm-offline"
    result = {
        "ok": True,
        "skill": "write_reply",
        "iron_rule": "draft_only",
        "draft_only": True,
        "subject": subject,
        "body": body,
        "reply": body,
        "_source": source,
    }
    ctx.scratch["reply"] = result
    return result
