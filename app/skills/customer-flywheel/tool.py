"""customer_flywheel — 跟进编排 Skill."""
from __future__ import annotations
from typing import Any, Dict


def run(ctx, action: str = "list",
        context_id: str = "",
        customer_id: str = "",
        **kwargs) -> Dict[str, Any]:
    ctrl = ctx.get_ctrl()
    from services.customer_flywheel import CustomerFlywheel
    fw = getattr(ctrl, "flywheel", None)
    if fw is None:
        return {"ok": False, "error": "flywheel 未初始化", "skill": "customer_flywheel"}

    if action == "schedule":
        ids = fw.schedule_followups(context_id, customer_id)
        return {"ok": True, "skill": "customer_flywheel",
                "iron_rule": "deterministic", "scheduled_ids": ids}
    if action == "cancel":
        n = fw.cancel_followups(context_id)
        return {"ok": True, "skill": "customer_flywheel",
                "iron_rule": "deterministic", "cancelled": n}
    # default: list
    pending = ctrl.crm.list_pending_followups(customer_id=customer_id, limit=20)
    return {"ok": True, "skill": "customer_flywheel",
            "iron_rule": "deterministic", "pending": pending}