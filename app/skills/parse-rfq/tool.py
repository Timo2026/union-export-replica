"""parse_rfq — 邮件/文本 → canonical RFQ (确定性规则抽取)."""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, email_text: str = "", text: str = "", customer: Dict[str, Any] | None = None,
        **kwargs) -> Dict[str, Any]:
    body = email_text or text or kwargs.get("raw") or ""
    if not body:
        return {"ok": False, "error": "email_text/text required", "skill": "parse_rfq"}
    ctrl = ctx.get_ctrl()
    from services.intake import extract_rfq
    rfq = extract_rfq(body, customer or {})
    ctx.scratch["rfq"] = rfq
    ctx.scratch["email_text"] = body
    if customer:
        ctx.scratch["customer"] = customer
    return {
        "ok": True,
        "skill": "parse_rfq",
        "iron_rule": "deterministic",
        "rfq": rfq,
        "missing_information": rfq.get("missing_information") or [],
        "_source": "services.intake.extract_rfq",
        "_engine": getattr(getattr(ctrl, "timo", None), "source_label", lambda: "n/a")(),
    }
