"""price-expert skill tool — CNC 加工报价专家推理."""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, calculation: Dict[str, Any] = None, user_input: str = "",
        **kwargs) -> Dict[str, Any]:
    """报价专家: 分项费用解释 + 批量经济性 + 毛利合理性."""
    if calculation is None:
        return {"ok": False, "skill": "price-expert", "iron_rule": "llm_proposal",
                "error": "calculation required", "_source": "mock"}

    # 离线降级
    try:
        ctrl = ctx.get_ctrl() if hasattr(ctx, "get_ctrl") else None
        if ctrl is not None and getattr(ctrl, "planner", None) is not None and ctrl.planner.online():
            return _run_llm(ctrl.planner, calculation, user_input)
    except Exception:
        pass

    # Mock 解释
    mat = calculation.get("material_cost_single", 0)
    mach = calculation.get("machining_cost_single", 0)
    surf = calculation.get("surface_cost_single", 0)
    total = max(calculation.get("total_single", 1), 0.01)
    quantity = calculation.get("quantity", 1)
    batch_total = calculation.get("total_batch", total * quantity)

    mat_pct = round(mat / total * 100, 1)
    mach_pct = round(mach / total * 100, 1)
    surf_pct = round(surf / total * 100, 1)

    suggestions = []
    if surf_pct > 30:
        suggestions.append("表面处理占比过高, 考虑降级或取消")
    if mach_pct > 60:
        suggestions.append("加工费占比过高, 考虑工艺优化")
    if quantity < 10:
        suggestions.append("小批量生产, 单件成本偏高, 建议批量优化")

    return {
        "ok": True,
        "skill": "price-expert",
        "agent": "quote_expert",
        "iron_rule": "llm_proposal",
        "explanation": {
            "ratios": {
                "material_pct": mat_pct,
                "machining_pct": mach_pct,
                "surface_pct": surf_pct,
            },
            "material_cost": mat,
            "machining_cost": mach,
            "surface_cost": surf,
            "total_single": total,
            "total_batch": batch_total,
            "quantity": quantity,
            "batch_economy": "批量折扣已计入单价" if quantity >= 10 else "建议增加批量",
            "margin_score": 80 if 15 <= mach_pct <= 60 else 60,
            "suggestions": suggestions,
        },
        "source": "mock",
        "_source": "price-expert mock fallback (LLM offline)",
    }


def _run_llm(planner, calculation: Dict[str, Any], user_input: str) -> Dict[str, Any]:
    """调 LLMPlanner 做报价解释."""
    system = (
        "你是CNC加工报价专家. 基于精确计算的分项费用 (Python已算), "
        "解释费用占比 + 批量经济性 + 毛利合理性. 严禁重算数字."
    )
    user = (
        f"分项费用: 材料 ¥{calculation.get('material_cost_single', 0)}, "
        f"加工 ¥{calculation.get('machining_cost_single', 0)}, "
        f"表面 ¥{calculation.get('surface_cost_single', 0)}\n"
        f"单件总价 ¥{calculation.get('total_single', 0)}, 批量 {calculation.get('quantity', 1)}件, "
        f"批量总价 ¥{calculation.get('total_batch', 0)}\n"
        f"用户需求: {user_input or '(空)'}\n\n"
        "输出 JSON: {ratios: {material_pct, machining_pct, surface_pct}, "
        "batch_economy: str, margin_score: 0-100, suggestions: [str]}"
    )
    schema = {
        "type": "object",
        "properties": {
            "ratios": {"type": "object"},
            "batch_economy": {"type": "string"},
            "margin_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "suggestions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["margin_score"],
    }
    try:
        result = planner.chat_json("price-expert", user, schema=schema, system=system)
        if result.get("ok") and result.get("data"):
            return {
                "ok": True,
                "skill": "price-expert",
                "agent": "quote_expert",
                "iron_rule": "llm_proposal",
                "explanation": result["data"],
                "source": "llm",
            }
    except Exception:
        pass
    return _mock(calculation)


def _mock(calculation: Dict[str, Any]) -> Dict[str, Any]:
    """mock 兜底."""
    total = max(calculation.get("total_single", 1), 0.01)
    return {
        "ok": True,
        "skill": "price-expert",
        "iron_rule": "llm_proposal",
        "explanation": {
            "ratios": {"material_pct": 30, "machining_pct": 50, "surface_pct": 20},
            "batch_economy": "mock",
            "margin_score": 70,
            "suggestions": [],
        },
        "source": "mock",
    }
