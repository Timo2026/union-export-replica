"""feasibility_check — 设备能力校验 (确定性, 铁律②不定价).

精选自外部 skill 库的设备能力表为默认占位值, 需工厂真实机床参数替换。
"""
from __future__ import annotations

from typing import Any, Dict, List

# 默认机床能力表 (占位值): envelope=长×宽×高(mm), max_kg, materials, it_min=可稳定达到的最小 IT 级(越小越精)
_CAPABILITY_TABLE = {
    "三轴铣": {"envelope": (500, 400, 300), "max_kg": 200,
               "materials": {"6061", "7075", "45钢", "Q235", "黄铜"}, "it_min": 7},
    "四轴铣": {"envelope": (600, 400, 300), "max_kg": 250,
               "materials": {"6061", "7075", "45钢", "Q235", "黄铜"}, "it_min": 7},
    "五轴铣": {"envelope": (800, 600, 400), "max_kg": 400,
               "materials": {"6061", "7075", "TC4", "45钢"}, "it_min": 6},
    "车床":   {"envelope": (320, 320, 800), "max_kg": 150,
               "materials": {"6061", "7075", "45钢", "Q235", "黄铜"}, "it_min": 7},
    "磨床":   {"envelope": (400, 200, 200), "max_kg": 100,
               "materials": {"6061", "7075", "304", "316L", "TC4", "45钢"}, "it_min": 5},
    "线切割": {"envelope": (500, 400, 300), "max_kg": 300,
               "materials": {"6061", "7075", "304", "316L", "45钢", "Q235"}, "it_min": 6},
    "电火花": {"envelope": (400, 300, 200), "max_kg": 200,
               "materials": {"6061", "7075", "304", "316L", "TC4", "45钢"}, "it_min": 6},
}


def _it_rank(tolerance_grade: str) -> int:
    """IT4..IT10 → 4..10; 未知 → 8 (常规件默认)。"""
    tg = (tolerance_grade or "").upper()
    if tg.startswith("IT") and tg[2:].isdigit():
        return int(tg[2:])
    return 8


def run(ctx, length: float = 0, width: float = 0, height: float = 0,
        weight: float = 0, material: str = "", tolerance_grade: str = "",
        rfq: Dict[str, Any] | None = None, geometry: Dict[str, Any] | None = None,
        **kwargs) -> Dict[str, Any]:
    rfq = dict(rfq or (ctx.scratch.get("rfq") if ctx else None) or {})
    geo = dict(geometry or (ctx.scratch.get("geometry") if ctx else None) or {})
    dims = geo.get("bounding_box") or geo or {}
    length = length or dims.get("length") or rfq.get("length") or 0
    width = width or dims.get("width") or rfq.get("width") or 0
    height = height or dims.get("height") or rfq.get("height") or 0
    weight = weight or geo.get("weight") or rfq.get("weight") or 0
    material = material or rfq.get("material") or ""
    tolerance_grade = tolerance_grade or rfq.get("tolerance_grade") or ""

    if not (length and width and height):
        return {"ok": False, "skill": "feasibility_check",
                "error": "length/width/height required"}

    need_it = _it_rank(tolerance_grade)
    dims_sorted = sorted([float(length), float(width), float(height)], reverse=True)
    available: List[str] = []
    issues: List[str] = []
    suggestions: List[str] = []

    for name, cap in _CAPABILITY_TABLE.items():
        env_sorted = sorted(cap["envelope"], reverse=True)
        prob = []
        if any(d > e for d, e in zip(dims_sorted, env_sorted)):
            prob.append("尺寸超包络")
        if weight and weight > cap["max_kg"]:
            prob.append(f"重量超上限(≤{cap['max_kg']}kg)")
        if material and material not in cap["materials"]:
            prob.append(f"材料{material}该设备不支持")
        if need_it < cap["it_min"]:
            prob.append(f"公差{tolerance_grade or 'IT' + str(need_it)}超设备能力(可达IT{cap['it_min']})")
        if prob:
            issues.append(f"{name}: " + "; ".join(prob))
        else:
            available.append(name)

    feasible = bool(available)
    if not feasible:
        suggestions.append("无设备满足全部约束 → 需外协或拆分零件, 或放宽公差/尺寸后重判")
        suggestions.append("若为默认能力表所致, 请工厂补充真实机床参数 (当前 _source=default-capability-table)")

    return {
        "ok": True,
        "skill": "feasibility_check",
        "iron_rule": "deterministic",
        "pricing": "none",  # 铁律②: 本 skill 不产价
        "feasible": feasible,
        "available_equipment": available,
        "issues": issues,
        "suggestions": suggestions,
        "checked": {"length": length, "width": width, "height": height,
                    "weight": weight, "material": material,
                    "tolerance_grade": tolerance_grade or f"IT{need_it}"},
        "_source": "default-capability-table",
        "_caveat": "设备能力表为默认占位值, 需工厂真实机床参数替换后方可用于生产决策",
    }
