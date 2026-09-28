"""cnc_quote — 确定性 CNC 报价 (铁律①: LLM 不生成价格数字).

契约见 SKILL.md: 在线 :7862 /api/quote 优先, 离线 byte-identical 兜底 (TimoAdapter.quote 内部处理)。
与 calc-quote 同一后端; 本 skill 输出 SKILL.md 声明的精简字段集。
"""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, material: str = "", quantity: int | None = None, surface: str = "",
        weight_kg: float | None = None, max_dim_mm: float | None = None,
        tolerance_grade: str = "", thread_count: int | None = None,
        dims: list | None = None, rfq: Dict[str, Any] | None = None,
        step_facts: Dict[str, Any] | None = None, **kwargs) -> Dict[str, Any]:
    payload = dict(rfq or ctx.scratch.get("rfq") or {})
    facts = dict(step_facts or ctx.scratch.get("step_facts") or {})
    if material:
        payload["material"] = material
    payload.setdefault("material", "6061")
    if quantity is not None:
        payload["quantity"] = int(quantity)
    payload.setdefault("quantity", 1)
    if surface:
        payload["surface"] = surface
    if tolerance_grade:
        payload["tolerance_grade"] = tolerance_grade
    if weight_kg is not None:
        payload["weight_kg"] = weight_kg
    elif facts.get("weight_kg"):
        payload["weight_kg"] = facts["weight_kg"]
    if max_dim_mm is not None:
        payload["max_dim_mm"] = max_dim_mm
    elif facts.get("max_dim_mm"):
        payload["max_dim_mm"] = facts["max_dim_mm"]
    elif dims:
        try:
            payload["max_dim_mm"] = max(float(x) for x in dims if x is not None)
        except (TypeError, ValueError):
            pass
    if thread_count is not None:
        payload["thread_count"] = int(thread_count)

    ctrl = ctx.get_ctrl()
    timo = ctx.timo or getattr(ctrl, "timo", None)
    try:
        out = timo.quote(payload)
    except Exception as e:  # noqa
        return {"ok": False, "skill": "cnc_quote", "error": repr(e),
                "iron_rule": "deterministic"}
    if not isinstance(out, dict):
        out = {"raw": out}
    result = {
        "ok": True,
        "skill": "cnc_quote",
        "iron_rule": "deterministic",
        "unit_price": out.get("unit_price"),
        "total_price": out.get("total_price"),
        "final_price": out.get("final_price"),
        "profit": out.get("profit"),
        "lead_time_days": out.get("lead_time_days"),
        "valid": out.get("valid", True),
        "conflicts": out.get("conflicts") or [],
        "_source": out.get("_source", "timo:calc_quote"),
    }
    ctx.scratch.setdefault("quote", result)
    return result
