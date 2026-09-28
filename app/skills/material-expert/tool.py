"""material-expert skill tool — 材料工程专家推理.

被 services.skill_dispatcher 通过 skills._runtime 自动发现注册.
"""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, calculation: Dict[str, Any] = None, user_input: str = "",
        **kwargs) -> Dict[str, Any]:
    """材料专家: 验证选型 + 兼容性 + 替代材料."""
    if calculation is None:
        return {"ok": False, "skill": "material-expert", "iron_rule": "llm_proposal",
                "error": "calculation required", "_source": "mock"}

    material = calculation.get("material", "")
    material_name = calculation.get("material_name", "")
    surface = calculation.get("surface", "none")

    # 离线降级: keyword rules
    try:
        ctrl = ctx.get_ctrl() if hasattr(ctx, "get_ctrl") else None
        if ctrl is not None and getattr(ctrl, "planner", None) is not None and ctrl.planner.online():
            return _run_llm(ctrl.planner, calculation, user_input)
    except Exception as e:
        pass  # 降级到 mock

    # Mock 分析 (基于 MATERIAL_DB 知识)
    from services.fleet_v4.calculation import MATERIAL_DB
    mat_info = MATERIAL_DB.get(material, {})
    anodizing_ok = mat_info.get("anodizing_ok", False)
    compatible = anodizing_ok if surface in ("none", "anodizing") else True
    risks = []
    if surface == "anodizing" and not anodizing_ok:
        risks.append(f"{material_name} 不能阳极氧化 (铁基材料)")
        compatible = False
    recommended = []
    if material == "6061" and not anodizing_ok:
        recommended.append("升级 7075 铝合金 (强度 +75%, 阳极可)")
    elif material == "304" and surface == "none":
        recommended.append("考虑 316L 不锈钢 (耐腐蚀更好)")

    return {
        "ok": True,
        "skill": "material-expert",
        "agent": "material_expert",
        "iron_rule": "llm_proposal",
        "analysis": {
            "material": material,
            "material_name": material_name,
            "surface": surface,
            "compatible": compatible,
            "anodizing_ok": anodizing_ok,
            "risks": risks,
            "recommended": recommended,
            "score": 85 if compatible else 45,
        },
        "source": "mock",
        "_source": "material-expert mock fallback (LLM offline)",
    }


def _run_llm(planner, calculation: Dict[str, Any], user_input: str) -> Dict[str, Any]:
    """调 LLMPlanner.chat_json 做材料推理."""
    import json
    system = (
        "你是材料工程专家, 精通工业材料选型. 基于给定的精确计算数值 (Python已算), "
        "分析材料兼容性 + 表面处理 + 推荐替代材料. 严禁重算数字, 仅做领域推理."
    )
    user = (
        f"材料: {calculation.get('material_name', '')}\n"
        f"表面: {calculation.get('surface', 'none')}\n"
        f"单件重量: {calculation.get('weight_kg_single', 0)} kg\n"
        f"单件总价: ¥{calculation.get('total_single', 0)}\n"
        f"用户需求: {user_input or '(空)'}\n\n"
        "输出 JSON: {compatible: bool, anodizing_ok: bool, risks: [str], recommended: [str], score: 0-100}"
    )
    schema = {
        "type": "object",
        "properties": {
            "compatible": {"type": "boolean"},
            "anodizing_ok": {"type": "boolean"},
            "risks": {"type": "array", "items": {"type": "string"}},
            "recommended": {"type": "array", "items": {"type": "string"}},
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
        },
        "required": ["compatible", "score"],
    }
    try:
        result = planner.chat_json("material-expert", user, schema=schema, system=system)
        if result.get("ok") and result.get("data"):
            return {
                "ok": True,
                "skill": "material-expert",
                "agent": "material_expert",
                "iron_rule": "llm_proposal",
                "analysis": result["data"],
                "source": "llm",
                "_source": result.get("_source", "llm-planner"),
            }
    except Exception as e:
        pass  # 降级
    # 降级: LLM 返 ok=False 也走 mock
    return run.__wrapped__ if hasattr(run, "__wrapped__") else _mock_fallback(calculation)


def _mock_fallback(calculation: Dict[str, Any]) -> Dict[str, Any]:
    """mock 兜底 (供 _run_llm 异常时调用)."""
    from services.fleet_v4.calculation import MATERIAL_DB
    mat_info = MATERIAL_DB.get(calculation.get("material", ""), {})
    return {
        "ok": True,
        "skill": "material-expert",
        "iron_rule": "llm_proposal",
        "analysis": {
            "material": calculation.get("material"),
            "compatible": True,
            "score": 80,
            "note": "mock after LLM failure",
        },
        "source": "mock",
    }
