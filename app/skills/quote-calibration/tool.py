"""quote_calibration — 价格自学习 Skill."""
from __future__ import annotations
from typing import Any, Dict


def run(ctx, action: str = "get_adjustments",
        context_id: str = "",
        customer_id: str = "",
        material: str = "",
        quoted_unit_price: float = 0.0,
        actual_unit_cost: float = 0.0,
        outcome: str = "",
        **kwargs) -> Dict[str, Any]:
    ctrl = ctx.get_ctrl()
    from services.quote_calibration import QuoteCalibration
    cal = QuoteCalibration(ctrl.crm)
    if action == "record":
        if not (context_id and customer_id and outcome):
            return {"ok": False, "error": "context_id/customer_id/outcome 必填"}
        ev = cal.record_outcome(context_id, customer_id, material, "",
                                0, quoted_unit_price,
                                actual_unit_cost or None, outcome)
        return {"ok": True, "skill": "quote_calibration",
                "iron_rule": "deterministic", "event": ev}
    # get_adjustments
    adj = cal.get_adjustments(customer_id, material=material or None)
    return {"ok": True, "skill": "quote_calibration",
            "iron_rule": "deterministic", "adjustments": adj}