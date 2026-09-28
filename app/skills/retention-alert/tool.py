"""retention_alert — 流失预警 Skill."""
from __future__ import annotations
from typing import Any, Dict


def run(ctx, threshold: float = 65.0, no_contact_days: int = 30,
        **kwargs) -> Dict[str, Any]:
    ctrl = ctx.get_ctrl()
    from services.customer_flywheel import RetentionAlert
    from services.customer_health import CustomerHealthEngine
    heal = CustomerHealthEngine(ctrl.crm)
    ra = RetentionAlert(ctrl.crm, heal)
    alerts = ra.scan(threshold=threshold, no_contact_days=no_contact_days)
    return {"ok": True, "skill": "retention_alert",
            "iron_rule": "deterministic", "alerts": alerts,
            "count": len(alerts), "threshold": threshold,
            "no_contact_days": no_contact_days}