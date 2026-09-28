"""golden_chain — CAT 黄金链 Blueprint (端到端封装)."""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, email_text: str = "", customer: Dict[str, Any] | None = None,
        use_llm: bool = False, destination_country: str = "",
        shipping_mode: str = "", incoterm: str = "",
        voice_transcript: str = "", **kwargs) -> Dict[str, Any]:
    body = email_text or ctx.scratch.get("email_text") or ""
    if not body:
        return {"ok": False, "skill": "golden_chain", "error": "email_text required"}
    ctrl = ctx.get_ctrl()
    try:
        out = ctrl.run(
            email_text=body,
            customer=customer or ctx.scratch.get("customer") or {},
            destination_country=destination_country or None,
            shipping_mode=shipping_mode or None,
            incoterm=incoterm or None,
            voice_transcript=voice_transcript or None,
            use_llm=bool(use_llm),
        )
    except Exception as e:  # noqa
        return {"ok": False, "skill": "golden_chain", "error": repr(e),
                "iron_rule": "deterministic"}
    if not isinstance(out, dict):
        out = {"raw": out}
    quote = out.get("quote") or {}
    ver = out.get("verification") or {}
    status = out.get("verification_status") or ver.get("status") or "PASS"
    result = {
        "ok": True,
        "skill": "golden_chain",
        "iron_rule": "deterministic",
        "context_id": out.get("context_id"),
        "state": out.get("state"),
        "verification_status": status,
        "quote": quote,
        "unit_price": quote.get("unit_price"),
        "final_price": quote.get("final_price"),
        "quote_total_cny": quote.get("final_price") or quote.get("total_price"),
        "dfm_valid": (out.get("manufacturing") or {}).get("dfm", {}).get("valid", True),
        "multimodal_conflicts": out.get("multimodal_conflicts") or [],
        "reply": out.get("reply"),
        "hitl_required": status in ("HITL", "BLOCKED"),
        "_source": getattr(getattr(ctrl, "timo", None), "source_label", lambda: "cat_controller")(),
        "raw": out,
    }
    ctx.scratch["golden_chain"] = result
    ctx.scratch["rfq"] = out.get("rfq") or ctx.scratch.get("rfq") or {}
    return result
