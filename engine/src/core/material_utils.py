# -*- coding: utf-8 -*-
"""材料别名归一工具（单一来源）。

DRY 原则：材料别名映射集中在本模块，报价引擎（src/runtime/quote_adapter.py）
与冲突检测（src/neuro_core/conflict_check.py）统一引用，避免两处重复实现。

废弃散落各处的 _norm_material，统一使用 normalize_material()。
"""

# 别名 -> 规范名（小写匹配）
MATERIAL_ALIASES = {
    "sus304": "304", "sus316": "316l", "al6061": "6061",
    "45#": "45钢", "45#钢": "45钢", "titanium": "tc4",
    "铝": "6061", "铝合金": "6061", "不锈钢": "304", "铜": "h59",
}


def normalize_material(m, default="6061"):
    """将材料名归一为规范名。

    - 空值(None/''/空白)返回 default
    - 命中别名的返回规范名
    - 未知材料原样返回（交由调用方决定兜底策略）
    """
    if not m:
        return default
    s = str(m).strip()
    return MATERIAL_ALIASES.get(s.lower(), s)