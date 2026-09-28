"""calc_quote — Timo 确定性报价 (铁律①: LLM 不生成价格)."""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, material: str = "", quantity: int | None = None, surface: str = "",
        weight_kg: float | None = None, max_dim_mm: float | None = None,
        tolerance_grade: str = "", rfq: Dict[str, Any] | None = None,
        step_facts: Dict[str, Any] | None = None, **kwargs) -> Dict[str, Any]:
    rfq_in = dict(rfq or ctx.scratch.get("rfq") or {})
    facts = dict(step_facts or ctx.scratch.get("step_facts") or {})
    payload = dict(rfq_in)
    if material:
        payload["material"] = material
    elif not payload.get("material"):
        payload["material"] = "6061"
    if quantity is not None:
        payload["quantity"] = int(quantity)
    elif not payload.get("quantity"):
        payload["quantity"] = 1
    if surface:
        payload["surface"] = surface
    if tolerance_grade:
        payload["tolerance_grade"] = tolerance_grade
    if weight_kg is not None:
        payload["weight_kg"] = weight_kg
    elif facts.get("weight_kg"):
        payload["weight_kg"] = facts.get("weight_kg")
    if max_dim_mm is not None:
        payload["max_dim_mm"] = max_dim_mm
    elif facts.get("max_dim_mm"):
        payload["max_dim_mm"] = facts.get("max_dim_mm")
    elif payload.get("dimensions_mm"):
        dims = payload.get("dimensions_mm") or []
        if dims:
            try:
                payload["max_dim_mm"] = max(float(x) for x in dims if x is not None)
            except (TypeError, ValueError):
                pass
    ctrl = ctx.get_ctrl()
    timo = ctx.timo or getattr(ctrl, "timo", None)
    try:
        out = timo.quote(payload)
    except Exception as e:  # noqa
        return {"ok": False, "skill": "calc_quote", "error": repr(e),
                "iron_rule": "deterministic"}
    if not isinstance(out, dict):
        out = {"raw": out}
    unit = out.get("unit_price")
    total = out.get("final_price") or out.get("total_price")
    result = {
        "ok": True,
        "skill": "calc_quote",
        "iron_rule": "deterministic",
        "unit_price": unit,
        "unit_price_cny": unit,
        "total_price": out.get("total_price"),
        "final_price": out.get("final_price"),
        "quote_total_cny": total,
        "profit": out.get("profit"),
        "lead_time_days": out.get("lead_time_days"),
        "valid": out.get("valid", True),
        "conflicts": out.get("conflicts") or [],
        "_source": out.get("_source", "timo:calc_quote"),
        "raw": out,
    }
    policy = ctx.policy or {}
    unit_gate = ((policy.get("amount_gate") or {}).get("unit_price_review_cny"))
    total_gate = ((policy.get("amount_gate") or {}).get("total_price_review_cny"))
    if unit_gate and unit is not None:
        try:
            result["amount_gate_unit"] = float(unit) > float(unit_gate)
        except (TypeError, ValueError):
            pass
    if total_gate and total is not None:
        try:
            result["amount_gate_total"] = float(total) > float(total_gate)
        except (TypeError, ValueError):
            pass
    ctx.scratch["quote"] = result
    return result
