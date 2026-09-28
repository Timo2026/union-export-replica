#!/usr/bin/env python3
"""
shape_classifier.py — 包围盒→形状分类器
=========================================
根据零件包围盒尺寸和特征描述，推测零件类型和默认工艺链。
这是报价引擎的第一关：从几何信息推断制造路线。
"""

# ── 形状分类规则 ──
SHAPE_RULES = [
    # 轴类: 两个小尺寸接近(<1.7倍)，长尺寸>小尺寸3倍
    ("轴套/轴类",
     lambda w, h, d, f: (lambda s=sorted([w,h,d]): s[2]/max(s[0],1)>3 and s[1]/max(s[0],1)<1.7)(),
     ["车削:一般", "钻孔:简单", "精车:一般"],
     "有键槽→+铣削, 有外螺纹→+车削螺纹"),

    # 法兰/盖板: 两大尺寸接近(>0.7倍)，大尺寸>厚度2.5倍
    ("法兰/盖板",
     lambda w, h, d, f: (lambda s=sorted([w,h,d]): s[1]/max(s[2],1)>0.7 and s[2]/max(s[0],1)>2.5)(),
     ["CNC:一般", "钻孔:简单"],
     "有密封槽→+O圈槽铣, 中心孔→+镗孔"),

    # 壳体/箱体: 三轴尺寸接近且都>50mm
    ("壳体/箱体",
     lambda w, h, d, f: (lambda s=sorted([w,h,d]): s[2]/max(s[0],1)<2.5 and s[0]>50)(),
     ["CNC:一般", "钻孔:简单", "攻牙:一般"],
     "五轴特征多→五轴CNC, 有装配面→+精铣"),

    # 板件/支架: 极薄（厚度<大尺寸/5）
    ("板件/支架",
     lambda w, h, d, f: (lambda s=sorted([w,h,d]): s[2]/max(s[0],1)>5)(),
     ["CNC:一般", "钻孔:简单"],
     "壁厚<2mm→可能钣金件, 有折弯→钣金"),

    # 齿轮: 直径≈高度且非极薄
    ("齿轮",
     lambda w, h, d, f: (lambda s=sorted([w,h,d]): abs(s[2]-s[1])/max(s[2],1)<0.4 and s[2]/max(s[0],1)<2.5 and s[0]>1)(),
     ["车削:一般", "滚齿:一般", "热处理:淬火", "磨齿:一般"],
     "斜齿→+磨齿更耗时"),

    # 真空腔体: 大尺寸>200mm，壁厚相对薄
    ("真空腔体",
     lambda w, h, d, f: max(w,h,d)>200 and min(w,h,d)>50,
     ["五轴CNC:复杂", "钻孔:一般", "攻牙:一般", "清洗:一般", "测量:CMM"],
     "密封面→Ra≤0.8, 大法兰面→+平面磨"),
]

# ── 精度→附加工艺映射 ──
PRECISION_ADDITIONS = [
    (0.03, 0.10,   []),                    # ±0.03-0.10: 常规加工
    (0.01, 0.03,   ["精磨:一般"]),          # ±0.01-0.03: 加精磨
    (0.005, 0.01,  ["磨削:一般"]),           # ±0.005-0.01: 加磨削
    (0.0,  0.005,  ["研磨:精密"]),          # <±0.005: 加研磨
]

# ── 粗糙度→附加工艺映射 ──
RA_ADDITIONS = [
    (6.3,  12.5,  []),                      # Ra6.3-12.5: 常规
    (3.2,  6.3,   []),                      # Ra3.2-6.3: 常规精加工
    (1.6,  3.2,   []),                      # Ra1.6-3.2: 半精磨
    (0.8,  1.6,   ["精磨:一般"]),           # Ra0.8-1.6: 加精磨
    (0.4,  0.8,   ["磨削:一般"]),           # Ra0.4-0.8: 加磨削
    (0.0,  0.4,   ["研磨:精密"]),           # Ra0.0-0.4: 加研磨
]


def ra_to_num(ra_str: str) -> float:
    """'Ra3.2' → 3.2"""
    try:
        return float(ra_str.replace("Ra", "").replace("ra", "").strip())
    except:
        return 12.5


def tolerance_to_range(tol_str: str) -> float:
    """'±0.01mm' → 0.01, '自由公差' → 0.2"""
    import re
    m = re.search(r'[±]?\s*([0-9.]+)', tol_str)
    if m:
        return float(m.group(1))
    return 0.2  # 自由公差默认


def classify_shape(width: float, height: float, depth: float,
                   features: list[str] = None) -> dict:
    """
    输入: 包围盒宽x高x深, 特征描述列表
    输出: {"shape": "法兰", "confidence": 0.85, "default_plan": [...], "hint": "..."}
    """
    w, h, d = width, height, depth
    features = features or []

    best_match = None
    best_priority = 99  # 越小越优先

    for shape_name, condition, default_plan, hint in SHAPE_RULES:
        try:
            priority = SHAPE_RULES.index((shape_name, condition, default_plan, hint))
            if condition(w, h, d, features):
                if priority < best_priority:
                    best_priority = priority
                    dims = sorted([w,h,d])
                    ratio = dims[2] / max(dims[0], 1)
                    conf = 0.85 if ratio > 4 or ratio < 2.2 else 0.75
                    best_match = {
                        "shape": shape_name,
                        "confidence": conf,
                        "default_plan": default_plan,
                        "hint": hint
                    }
        except Exception:
            continue

    if not best_match:
        best_match = {
            "shape": "通用机加件",
            "confidence": 0.5,
            "default_plan": ["CNC:一般", "钻孔:简单"],
            "hint": "包围盒不足以精准分类，建议人工确认"
        }

    return best_match


def add_precision_processes(plan: list[str], tolerance_str: str,
                             roughness_str: str) -> list[str]:
    """
    根据公差和粗糙度，给工艺链添加必要的精加工工序。
    """
    tol_range = tolerance_to_range(tolerance_str)
    ra_value = ra_to_num(roughness_str)

    additions = set()

    # 精度驱动
    for lo, hi, procs in PRECISION_ADDITIONS:
        if lo <= tol_range < hi and procs:
            additions.update(procs)

    # Ra驱动
    for lo, hi, procs in RA_ADDITIONS:
        if lo <= ra_value < hi and procs:
            additions.update(procs)

    new_plan = list(plan)
    for add in additions:
        if add not in new_plan:
            new_plan.append(add)

    return new_plan
