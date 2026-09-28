"""dfm-expert skill tool — DFM 可制造性分析专家."""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, dimensions: Dict[str, Any] = None, shape: str = "bushing",
        user_input: str = "", **kwargs) -> Dict[str, Any]:
    """DFM 专家: 最小壁厚 / 深孔 / 螺纹 / 装夹风险."""
    if dimensions is None:
        return {"ok": False, "skill": "dfm-expert", "iron_rule": "llm_proposal",
                "error": "dimensions required", "_source": "mock"}

    # 离线降级
    try:
        ctrl = ctx.get_ctrl() if hasattr(ctx, "get_ctrl") else None
        if ctrl is not None and getattr(ctrl, "planner", None) is not None and ctrl.planner.online():
            return _run_llm(ctrl.planner, dimensions, shape, user_input)
    except Exception:
        pass

    # Mock DFM 检查 (keyword rules)
    risks = []
    recommendations = []

    outer_d = float(dimensions.get("outer_d", 0))
    inner_d = float(dimensions.get("inner_d", 0))
    thickness = float(dimensions.get("thickness", 0) or dimensions.get("length", 0) or 0)
    holes = int(dimensions.get("holes", 0))

    # 壁厚检查
    if inner_d > 0:
        wall_mm = (outer_d - inner_d) / 2.0
        if wall_mm < 1.5:
            risks.append({"type": "min_wall", "severity": "high",
                          "message": f"壁厚 {wall_mm:.2f}mm < 1.5mm 最小值, 易变形"})
            recommendations.append("加厚壁到 ≥ 1.5mm 或分两件加工")
        elif wall_mm < 3.0:
            risks.append({"type": "thin_wall", "severity": "medium",
                          "message": f"壁厚 {wall_mm:.2f}mm 偏薄, 注意装夹"})
        else:
            risks.append({"type": "min_wall", "severity": "info",
                          "message": f"壁厚 {wall_mm:.2f}mm 充足"})

    # 深孔长径比
    if inner_d > 0 and thickness > 0:
        ratio = thickness / inner_d
        if ratio > 5:
            risks.append({"type": "deep_hole", "severity": "high",
                          "message": f"深孔长径比 {ratio:.1f} > 5, 需特殊刀具"})
            recommendations.append("改用枪钻或 EDM")

    # 螺纹底孔
    if holes > 0:
        risks.append({"type": "thread", "severity": "info",
                      "message": f"{holes} 个螺纹孔, M 标准底孔 φ6.8mm 深度 ≥ 12mm"})
        recommendations.append("确认螺纹规格, 标准 M3/M4/M6/M8")

    # 装夹 (薄壁判断)
    is_thin_wall = inner_d > 0 and (outer_d - inner_d) / 2.0 < 2.0
    if is_thin_wall:
        risks.append({"type": "fixture", "severity": "medium",
                      "message": "薄壁装夹易变形, 建议定制软爪"})
        recommendations.append("软爪/真空夹/填充蜡辅助")

    score = 100 - sum(20 if r["severity"] == "high" else 10 if r["severity"] == "medium" else 0
                      for r in risks)
    score = max(score, 30)

    return {
        "ok": True,
        "skill": "dfm-expert",
        "agent": "dfm_expert",
        "iron_rule": "llm_proposal",
        "risks": risks,
        "score": score,
        "recommendations": recommendations,
        "source": "mock",
        "_source": "dfm-expert mock fallback (LLM offline)",
    }


def _run_llm(planner, dimensions: Dict[str, Any], shape: str, user_input: str) -> Dict[str, Any]:
    """调 LLMPlanner 做 DFM 分析."""
    system = (
        "你是DFM可制造性分析专家. 基于精确几何尺寸 (Python已算), "
        "分析壁厚/深孔/螺纹/装夹风险. 严禁重算数字, 仅做领域推理."
    )
    user = (
        f"形状: {shape}\n尺寸: {dimensions}\n用户: {user_input or '(空)'}\n\n"
        "输出 JSON: {risks: [{type, severity, message}], score: 0-100, recommendations: [str]}"
    )
    schema = {
        "type": "object",
        "properties": {
            "risks": {"type": "array", "items": {"type": "object"}},
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["score", "risks"],
    }
    try:
        result = planner.chat_json("dfm-expert", user, schema=schema, system=system)
        if result.get("ok") and result.get("data"):
            return {
                "ok": True,
                "skill": "dfm-expert",
                "agent": "dfm_expert",
                "iron_rule": "llm_proposal",
                "risks": result["data"].get("risks", []),
                "score": result["data"].get("score", 70),
                "recommendations": result["data"].get("recommendations", []),
                "source": "llm",
            }
    except Exception:
        pass
    return _mock(dimensions)


def _mock(dimensions: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": True,
        "skill": "dfm-expert",
        "iron_rule": "llm_proposal",
        "risks": [],
        "score": 70,
        "recommendations": [],
        "source": "mock",
    }
