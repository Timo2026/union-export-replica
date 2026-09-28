# -*- coding: utf-8 -*-
"""C2 DFM 微调建议：基于 C1 实测 features + rule_dfm 结果生成结构化 DFM 修改建议。

定位：把 feature_extractor.extract_features 的实测数据 + part_analysis.rule_dfm 的
issues/recommendations 转化为面向工程师的「可操作建议清单」——每条建议含
severity / action_type / current_value / suggested_value，可直接驱动前端复核 UI。

设计原则：
- 禁止编造：所有建议必须基于传入的 features 数据字段，不凭空生成数值或规格。
- 模块级常量定义阈值（壁厚下限、深径比阈值、螺纹底孔映射），禁止散落硬编码。
- 容错：features 缺字段时跳过该建议，绝不抛异常（与 feature_extractor 降级承诺一致）。
- 材料分类复用 part_analysis.material_category（DRY，不重复材料识别逻辑）。

规则映射（基于零件 4xOdRrJv2S 实测）：
  1. 壁厚 1.086 < 1.5(铝下限) → error / modify / 加厚到≥1.5mm
  2. 36 螺纹底孔(Ø3.3×8→M4, Ø5.0×28→M6) → warning / confirm / 需确认螺纹规格
  3. 52 锥面(沉头/倒角) → info / confirm / 需确认沉头孔规格
  4. max_ld_ratio 3.03 < 5 → info / info / 深径比 OK 排屑无风险
  5. 0 内直角边 → info / info / 无需清角
"""
from src.runtime.part_analysis import material_category as _infer_material_category

# ─────────────────────────────────────────────────────────────
# 模块级常量（禁止硬编码：所有阈值/映射集中于此）
# ─────────────────────────────────────────────────────────────
# 各材料类别最小壁厚下限(mm)（与 part_analysis._WALL_LIMITS 保持一致，DRY）
_WALL_LIMITS_BY_CATEGORY = {
    "aluminum": 1.5,
    "steel": 3.0,
    "stainless": 3.0,
    "titanium": 4.0,
    "copper": 1.5,
}
_WALL_LIMIT_DEFAULT = 1.5  # 未知材料默认壁厚下限(mm)

# 深径比阈值(mm/mm)
_LD_RATIO_OK = 5.0    # ≤5 → 排屑无风险(info)
_LD_RATIO_WARN = 5.0  # >5 → 注意排屑(warning)
_LD_RATIO_ERROR = 8.0  # >8 → 需枪钻/内冷(error)

# 公制螺纹底孔直径(mm) → 螺纹规格
# （与 feature_extractor._TAP_DRILL_SIZES_MM 保持一致；此处为 advise 独立常量，
#   因 feature_extractor 中为私有下划线常量，不宜跨模块导入）
_TAP_DRILL_TO_THREAD = {
    1.6: "M2", 2.05: "M2.5", 2.5: "M3", 3.3: "M4",
    4.2: "M5", 5.0: "M6", 6.8: "M8", 8.5: "M10",
    10.2: "M12", 12.0: "M14", 14.0: "M16", 17.5: "M20",
}
_TAP_DRILL_TOL_MM = 0.2  # 底孔直径匹配容差(mm)


def advise(features, dfm_result=None):
    """基于实测 features 生成 DFM 微调建议清单。

    参数:
        features: dict, feature_extractor.extract_features 的返回值（含
                  holes/hole_summary/min_wall_mm/stats/right_angle_edges 等）。
        dfm_result: dict, 可选, part_analysis.rule_dfm 的返回值；用于取材料类别
                    以选择壁厚下限。缺省时按铝(aluminum)判定。

    返回:
        {
            "suggestions": [ {id, severity, category, title, description,
                              action_type, current_value, suggested_value,
                              related_feature}, ... ],
            "summary": {total, errors, warnings, infos}
        }
        features 为空或缺字段时返回空 suggestions + 零计数，绝不抛异常。
    """
    features = features or {}
    suggestions = []
    _advise_wall(features, dfm_result, suggestions)
    _advise_thread(features, suggestions)
    _advise_cone(features, suggestions)
    _advise_ld_ratio(features, suggestions)
    _advise_right_angle(features, suggestions)
    return {
        "suggestions": suggestions,
        "summary": _summary(suggestions),
    }


# ─────────────────────────────────────────────────────────────
# 各规则实现（每条规则一个 _advise_* 函数，互不依赖，顺序追加）
# ─────────────────────────────────────────────────────────────
def _advise_wall(features, dfm_result, suggestions):
    """规则1：最小壁厚 vs 材料下限。"""
    mw = features.get("min_wall_mm")
    if not mw or mw.get("value") is None:
        return
    wall = float(mw["value"])
    cat = _material_category(dfm_result)
    thresh = _WALL_LIMITS_BY_CATEGORY.get(cat, _WALL_LIMIT_DEFAULT)
    if wall < thresh:
        suggestions.append({
            "id": "WALL-001",
            "severity": "error",
            "category": "壁厚",
            "title": "最小壁厚低于%s件下限" % cat,
            "description": "实测最小壁厚 %smm，低于 %s 推荐下限 %smm，存在装夹变形/铣穿风险"
                            % (wall, cat, thresh),
            "action_type": "modify",
            "current_value": wall,
            "suggested_value": "≥%smm" % thresh,
            "related_feature": "min_wall_mm",
        })
    else:
        suggestions.append({
            "id": "WALL-001",
            "severity": "info",
            "category": "壁厚",
            "title": "最小壁厚满足要求",
            "description": "实测最小壁厚 %smm ≥ %s 下限 %smm" % (wall, cat, thresh),
            "action_type": "info",
            "current_value": wall,
            "suggested_value": None,
            "related_feature": "min_wall_mm",
        })


def _advise_thread(features, suggestions):
    """规则2：螺纹底孔嫌疑（thread_suspect=True 的光圆柱孔）需确认螺纹规格。"""
    holes = features.get("holes") or []
    if not holes:
        return
    # 按底孔直径分组统计嫌疑孔，并映射到螺纹规格
    suspect_by_d = {}  # {(d_mm, spec): count}
    unmatched = 0
    for h in holes:
        if not h.get("thread_suspect"):
            continue
        d = round(float(h["d_mm"]), 2)
        spec = _match_tap_drill(d)
        if spec:
            suspect_by_d[(d, spec)] = suspect_by_d.get((d, spec), 0) + 1
        else:
            unmatched += 1
    total = sum(suspect_by_d.values()) + unmatched
    if total == 0:
        return
    # 明细：Ø3.3×8→M4；Ø5.0×28→M6
    detail_parts = ["Ø%g×%d→%s" % (d, cnt, spec)
                    for (d, spec), cnt in sorted(suspect_by_d.items())]
    if unmatched:
        detail_parts.append("%d 个未匹配标准底孔" % unmatched)
    suggestions.append({
        "id": "THREAD-001",
        "severity": "warning",
        "category": "螺纹",
        "title": "%d 个光圆柱孔疑为螺纹底孔，需确认螺纹规格" % total,
        "description": "实测光圆柱孔直径匹配公制螺纹底孔标准，需按图纸确认螺纹规格与深度：" +
                       "；".join(detail_parts),
        "action_type": "confirm",
        "current_value": "%d 个底孔嫌疑" % total,
        "suggested_value": "按图纸标注螺纹规格（如 M4×0.7、M6×1.0）",
        "related_feature": "holes.thread_suspect",
    })


def _advise_cone(features, suggestions):
    """规则3：锥面（沉头/倒角）未解析，需确认规格。"""
    stats = features.get("stats") or {}
    cone = stats.get("cone_face_count")
    if not cone:
        return
    suggestions.append({
        "id": "CONE-001",
        "severity": "info",
        "category": "沉头",
        "title": "%d 个锥面未解析，需确认沉头/倒角规格" % cone,
        "description": "实测 %d 个圆锥面，可能为沉头孔或倒角，B-rep 未解析为独立孔径特征，需按图纸确认"
                       % cone,
        "action_type": "confirm",
        "current_value": "%d 个锥面" % cone,
        "suggested_value": "按图纸标注沉头孔规格与倒角尺寸",
        "related_feature": "stats.cone_face_count",
    })


def _advise_ld_ratio(features, suggestions):
    """规则4：孔系最大深径比评估排屑风险。"""
    hs = features.get("hole_summary") or {}
    max_ld = hs.get("max_ld_ratio")
    if max_ld is None:
        return
    max_ld = float(max_ld)
    if max_ld > _LD_RATIO_ERROR:
        suggestions.append({
            "id": "LDR-001",
            "severity": "error",
            "category": "深径比",
            "title": "孔系深径比 %.2f > 8，需深孔刀具" % max_ld,
            "description": "实测最大深径比 %.2f，超过 8，需枪钻/分段钻孔/内冷刀具" % max_ld,
            "action_type": "modify",
            "current_value": max_ld,
            "suggested_value": "≤8（或改用枪钻/内冷工艺）",
            "related_feature": "hole_summary.max_ld_ratio",
        })
    elif max_ld > _LD_RATIO_WARN:
        suggestions.append({
            "id": "LDR-001",
            "severity": "warning",
            "category": "深径比",
            "title": "孔系深径比 %.2f > 5，需注意排屑" % max_ld,
            "description": "实测最大深径比 %.2f，超过 5，排屑需关注，建议分级钻削/断屑" % max_ld,
            "action_type": "confirm",
            "current_value": max_ld,
            "suggested_value": "≤5（或增加排屑措施）",
            "related_feature": "hole_summary.max_ld_ratio",
        })
    else:
        suggestions.append({
            "id": "LDR-001",
            "severity": "info",
            "category": "深径比",
            "title": "孔系深径比 max %.2f ≤ 5，排屑无风险" % max_ld,
            "description": "实测最大深径比 %.2f，≤5 排屑顺畅，无需特殊深孔刀具" % max_ld,
            "action_type": "info",
            "current_value": max_ld,
            "suggested_value": None,
            "related_feature": "hole_summary.max_ld_ratio",
        })


def _advise_right_angle(features, suggestions):
    """规则5：内直角(凹直角)边清角评估。"""
    rae = features.get("right_angle_edges")
    if rae is None:
        return
    if rae == 0:
        suggestions.append({
            "id": "EDGE-001",
            "severity": "info",
            "category": "其他",
            "title": "无内直角边，无需清角加工",
            "description": "实测内直角(凹直角)边数为 0，无需清角刀/电火花清角",
            "action_type": "info",
            "current_value": 0,
            "suggested_value": None,
            "related_feature": "right_angle_edges",
        })
    else:
        suggestions.append({
            "id": "EDGE-001",
            "severity": "warning",
            "category": "其他",
            "title": "%d 个内直角边需清角" % rae,
            "description": "实测 %d 个内直角(凹直角)边，铣削存在 R 角残留，需清角刀/电火花" % rae,
            "action_type": "modify",
            "current_value": rae,
            "suggested_value": "0（或增加清角工序）",
            "related_feature": "right_angle_edges",
        })


# ─────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────
def _material_category(dfm_result):
    """从 rule_dfm 结果取材料类别；缺省按铝（任务背景 6061）。"""
    if not dfm_result:
        return "aluminum"
    details = dfm_result.get("details") or {}
    cat = details.get("material_category")
    if cat and cat in _WALL_LIMITS_BY_CATEGORY:
        return cat
    mat = details.get("material") or ""
    inferred = _infer_material_category(mat)
    return inferred if inferred in _WALL_LIMITS_BY_CATEGORY else "aluminum"


def _match_tap_drill(d_mm):
    """直径匹配公制螺纹底孔标准 → 返回规格(如 'M4')，否则 None。"""
    for drill, spec in _TAP_DRILL_TO_THREAD.items():
        if abs(d_mm - drill) <= _TAP_DRILL_TOL_MM:
            return spec
    return None


def _summary(suggestions):
    """汇总 severity 分布。"""
    counts = {"error": 0, "warning": 0, "info": 0}
    for s in suggestions:
        sev = s.get("severity", "info")
        counts[sev] = counts.get(sev, 0) + 1
    return {
        "total": len(suggestions),
        "errors": counts["error"],
        "warnings": counts["warning"],
        "infos": counts["info"],
    }