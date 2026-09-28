"""verify_gate — 辟·牟·援·推·止 + HITL 门禁 (确定性 policy)."""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, ctx_dict: Dict[str, Any] | None = None, **kwargs) -> Dict[str, Any]:
    payload = dict(ctx_dict or {})
    if not payload:
        rfq = ctx.scratch.get("rfq") or {}
        dfm = ctx.scratch.get("dfm") or {}
        quote = ctx.scratch.get("quote") or {}
        payload = {
            "rfq": rfq,
            "manufacturing": {"dfm": {
                "valid": dfm.get("valid", dfm.get("dfm_valid", True)),
                "conflicts": [{"message": c} if isinstance(c, str) else c
                              for c in (dfm.get("conflicts") or [])],
                "warnings": dfm.get("warnings") or [],
            }},
            "commercial": {
                "quote": quote,
                "margin_pct": quote.get("profit"),
            },
            "risk": {},
            "evidence": ctx.scratch.get("evidence") or [],
        }
        # 透传 quote 数字便于金额门禁
        if quote.get("unit_price") is not None:
            payload["commercial"]["unit_price"] = quote.get("unit_price")
        if quote.get("final_price") is not None:
            payload["commercial"]["final_price"] = quote.get("final_price")
    ctrl = ctx.get_ctrl()
    policy = ctx.policy or getattr(ctrl, "policy", {}) or {}
    from services.verification import Verification
    v = Verification(policy)
    try:
        out = v.run(payload)
    except Exception as e:  # noqa
        return {"ok": False, "skill": "verify_gate", "error": repr(e),
                "iron_rule": "deterministic"}
    status = out.get("status", "PASS")
    result = {
        "ok": True,
        "skill": "verify_gate",
        "iron_rule": "deterministic",
        "verification_status": status,
        "status": status,
        "checks": out.get("checks") or [],
        "reasons": out.get("reasons") or [],
        "next_action": out.get("next_action"),
        "dfm_valid": payload.get("manufacturing", {}).get("dfm", {}).get("valid", True),
        "hitl_required": status in ("HITL", "BLOCKED"),
        "_source": "services.verification.Verification",
        "raw": out,
    }
    ctx.scratch["verification"] = result
    return result
