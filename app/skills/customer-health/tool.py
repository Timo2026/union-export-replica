"""customer_health — 健康分 Skill."""
from __future__ import annotations
from typing import Any, Dict


def run(ctx, action: str = "compute",
        customer_id: str = "",
        threshold: float = 65.0,
        **kwargs) -> Dict[str, Any]:
    ctrl = ctx.get_ctrl()
    from services.customer_health import CustomerHealthEngine
    eng = CustomerHealthEngine(ctrl.crm)
    if action == "compute":
        h = eng.compute_health(customer_id)
        return {"ok": True, "skill": "customer_health",
                "iron_rule": "deterministic", "health": h}
    if action == "list_at_risk":
        at_risk = eng.list_at_risk(threshold)
        return {"ok": True, "skill": "customer_health",
                "iron_rule": "deterministic", "at_risk": at_risk,
                "threshold": threshold, "count": len(at_risk)}
    if action == "proactive_reach":
        should = eng.should_proactive_reach(customer_id)
        return {"ok": True, "skill": "customer_health",
                "iron_rule": "deterministic",
                "customer_id": customer_id,
                "should_proactive": should}
    return {"ok": False, "error": f"unknown action: {action}"}