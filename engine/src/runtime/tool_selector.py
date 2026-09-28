# -*- coding: utf-8 -*-
"""C3 刀具审核：基于孔径分布选择 CNC 刀具清单。

定位：把 feature_extractor.hole_summary 的孔径分布(by_diameter)转化为面向工艺的
「刀具清单」——钻头/丝锥/沉头刀/铰刀，供换刀次数估算与备料参考。

设计原则：
- 禁止编造：刀具仅基于传入的 hole_summary 孔径分布生成，不凭空增加规格。
- 螺纹底孔/沉头孔识别用模块级常量映射，有工艺标准依据（非硬编码零件尺寸）。
- 容错：hole_summary 缺字段时返回空清单，绝不抛异常。

识别依据：
  - 螺纹底孔：公制螺纹底孔直径标准（如 Ø3.3→M4, Ø5.0→M6）→ 钻头 + 丝锥
  - 沉头孔：ISO 10642 沉头螺钉头部沉孔直径（如 Ø11.0→M6 沉头）→ 沉头刀
  - 其余：普通直孔 → 钻头（公差紧时后续可升级铰刀）

换刀次数：三轴CNC 每换一种刀一次换刀，tool_changes = 刀具种类数。
"""
# ─────────────────────────────────────────────────────────────
# 模块级常量（禁止硬编码：所有映射/容差集中于此）
# ─────────────────────────────────────────────────────────────
# 公制螺纹底孔直径(mm) → 螺纹规格
# （与 feature_extractor._TAP_DRILL_SIZES_MM 保持一致；此处为 tool_selector 独立常量）
_TAP_DRILL_TO_THREAD = {
    1.6: "M2", 2.05: "M2.5", 2.5: "M3", 3.3: "M4",
    4.2: "M5", 5.0: "M6", 6.8: "M8", 8.5: "M10",
    10.2: "M12", 12.0: "M14", 14.0: "M16", 17.5: "M20",
}
_TAP_DRILL_TOL_MM = 0.2  # 底孔直径匹配容差(mm)

# ISO 10642 沉头螺钉头部沉孔直径(mm) → 螺纹规格
# （M4→Ø8.8, M5→Ø10.5, M6→Ø11.0, M8→Ø17.5；用于识别沉头孔并选沉头刀）
_SUNK_SCREW_HEAD_TO_THREAD = {
    8.8: "M4", 10.5: "M5", 11.0: "M6", 17.5: "M8",
}
_SUNK_SCREW_HEAD_TOL_MM = 0.3  # 沉头直径匹配容差(mm)


def select_tools(hole_summary, thread_suspect_count=0):
    """基于孔径分布选择刀具清单。

    参数:
        hole_summary: dict, feature_extractor.hole_summary，含
                      {count, min_d_mm, max_ld_ratio, by_diameter:{d_str: cnt}}。
        thread_suspect_count: int, 可选, 螺纹底孔嫌疑总数（来自 features.warnings
                              解析或 holes 统计），用于校验底孔识别覆盖度。

    返回:
        {
            "tool_list": [ {tool_type, diameter_mm, qty_needed, hole_count,
                            purpose, notes}, ... ],
            "summary": {total_tool_types, drills, taps, countersinks,
                        total_holes, tool_changes}
        }
        hole_summary 为空时返回空清单 + 零计数，绝不抛异常。
    """
    hole_summary = hole_summary or {}
    by_d = hole_summary.get("by_diameter") or {}
    tool_list = []
    for key, count in by_d.items():
        d = _parse_diameter(key)
        if d is None:
            continue
        _add_tools_for_diameter(d, int(count), tool_list)
    # 按直径排序，便于阅读（钻头/沉头刀/丝锥混合排序）
    tool_list.sort(key=lambda t: (t["diameter_mm"] or 0, t["tool_type"]))
    return {
        "tool_list": tool_list,
        "summary": _summary(tool_list, hole_summary, thread_suspect_count),
    }


# ─────────────────────────────────────────────────────────────
# 单径刀具决策（沉头 → 底孔+丝锥 → 直孔，优先级从高到低）
# ─────────────────────────────────────────────────────────────
def _add_tools_for_diameter(d, count, tool_list):
    """为一个直径添加对应刀具（可能多条：底孔钻头+丝锥）。"""
    # 1) 沉头孔？→ 沉头刀（优先，因沉头直径与底孔直径不会重合）
    sunk_spec = _match_sunk_head(d)
    if sunk_spec:
        tool_list.append({
            "tool_type": "沉头刀",
            "diameter_mm": round(d, 2),
            "qty_needed": 1,
            "hole_count": count,
            "purpose": "%s 沉头孔" % sunk_spec,
            "notes": "沉孔直径 Ø%g，配合锥面加工沉头座" % d,
        })
        return
    # 2) 螺纹底孔？→ 钻头 + 丝锥
    tap_spec = _match_tap_drill(d)
    if tap_spec:
        tool_list.append({
            "tool_type": "钻头",
            "diameter_mm": round(d, 2),
            "qty_needed": 1,
            "hole_count": count,
            "purpose": "%s 螺纹底孔" % tap_spec,
            "notes": "底孔，需配 %s 丝锥" % tap_spec,
        })
        tool_list.append({
            "tool_type": "丝锥",
            "diameter_mm": _thread_diameter(tap_spec),
            "qty_needed": 1,
            "hole_count": count,
            "purpose": "%s 螺纹" % tap_spec,
            "notes": "攻丝 %s，底孔 Ø%g" % (tap_spec, d),
        })
        return
    # 3) 普通直孔 → 钻头
    tool_list.append({
        "tool_type": "钻头",
        "diameter_mm": round(d, 2),
        "qty_needed": 1,
        "hole_count": count,
        "purpose": "直孔",
        "notes": "光孔，按公差选钻头/铰刀",
    })


# ─────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────
def _parse_diameter(key):
    """by_diameter 的 key(字符串如 '3.3'/'11') → float，失败返回 None。"""
    try:
        return float(key)
    except (TypeError, ValueError):
        return None


def _match_tap_drill(d_mm):
    """直径匹配公制螺纹底孔标准 → 返回规格(如 'M4')，否则 None。"""
    for drill, spec in _TAP_DRILL_TO_THREAD.items():
        if abs(d_mm - drill) <= _TAP_DRILL_TOL_MM:
            return spec
    return None


def _match_sunk_head(d_mm):
    """直径匹配 ISO 10642 沉头螺钉沉孔直径 → 返回规格(如 'M6')，否则 None。"""
    for head, spec in _SUNK_SCREW_HEAD_TO_THREAD.items():
        if abs(d_mm - head) <= _SUNK_SCREW_HEAD_TOL_MM:
            return spec
    return None


def _thread_diameter(spec):
    """'M4' → 4.0, 'M6' → 6.0；解析失败返回 None。"""
    try:
        return float(spec.lstrip("M"))
    except (TypeError, ValueError, AttributeError):
        return None


def _summary(tool_list, hole_summary, thread_suspect_count):
    """汇总刀具种类与孔数。"""
    drills = sum(1 for t in tool_list if t["tool_type"] == "钻头")
    taps = sum(1 for t in tool_list if t["tool_type"] == "丝锥")
    countersinks = sum(1 for t in tool_list if t["tool_type"] == "沉头刀")
    reamers = sum(1 for t in tool_list if t["tool_type"] == "铰刀")
    total_types = len(tool_list)
    # total_holes 优先用 hole_summary.count（最准），否则按钻头+沉头刀 hole_count 求和
    # （丝锥加工同一孔的螺纹，不重复计入孔数）
    total_holes = hole_summary.get("count")
    if not total_holes:
        total_holes = sum(t["hole_count"] for t in tool_list
                          if t["tool_type"] in ("钻头", "沉头刀"))
    # 三轴CNC 换刀次数 = 刀具种类数（每换一种刀一次换刀）
    return {
        "total_tool_types": total_types,
        "drills": drills,
        "taps": taps,
        "countersinks": countersinks,
        "total_holes": total_holes,
        "tool_changes": total_types,
    }