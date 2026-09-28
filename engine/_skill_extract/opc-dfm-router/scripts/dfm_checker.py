#!/usr/bin/env python3
"""
dfm_checker.py — DFM制造可行性检查引擎
======================================
从真实客户对话提炼的DFM规则表。
检查项: 薄壁、深孔、内直角、细长比、深腔、最小特征、材料限制。
"""

# ── 规则优先级: fatal > warn > ok ──
# 每条规则 = (条件, 检查项, 严重度, 问题描述, 建议)

# ── CNC 规则 ──
CNC_RULES = [
    # 薄壁
    (lambda p: p.get("min_wall", 999) < 0.5, "CNC-薄壁",
     "fatal", "壁厚<0.5mm, CNC无法加工(刀具会让壁变形或震断)",
     "建议增大壁厚至≥0.5mm；如需更薄考虑线切割或激光切割"),
    (lambda p: 0.5 <= p.get("min_wall", 999) < 1.5, "CNC-薄壁",
     "warn", "壁厚{:.1f}mm, 变形风险高, 需要真空吸盘或软爪装夹",
     "建议增加壁厚至≥1.5mm；或预留工艺加强筋，加工后去除"),
    (lambda p: 1.5 <= p.get("min_wall", 999) < 3.0, "CNC-薄壁",
     "info", "壁厚{:.1f}mm, 可加工但需要控制切削力",
     "精加工余量≤0.3mm, 避免径向切削力过大"),

    # 深孔 L/D > 8
    (lambda p: p.get("hole_ld", 0) > 8, "CNC-深孔",
     "fatal", "孔深径比L/D={:.1f}>8, 普通钻头无法排屑, 需深孔钻",
     "建议：1)钻头改为枪钻 2)分步钻: 先钻后铰 3)两侧对钻(若通孔)"),
    (lambda p: 3 < p.get("hole_ld", 0) <= 8, "CNC-深孔",
     "warn", "孔深径比L/D={:.1f}>3, 需关注排屑和钻头偏斜",
     "建议: 啄钻切削, 使用高压内冷钻头"),
    (lambda p: 6 < p.get("hole_ld", 0) <= 8, "CNC-深孔",
     "info", "深孔L/D={:.1f}在常规钻床上限",
     "需定量退刀排屑, 每次进给≤3×D"),

    # 内直角 (CNC铣刀有半径, 无法做真正的内直角)
    (lambda p: p.get("inner_corner_r", 0) == 0, "CNC-内直角",
     "warn", "内直角无法直接CNC加工 (铣刀是圆的)",
     "建议: 1)允许R角≥刀具半径 2)改为电火花清角 3)拆分焊接"),
    (lambda p: 0 < p.get("inner_corner_r", 999) < 0.5, "CNC-内直角",
     "info", "内R角{:.1f}mm, 需要小直径刀具, 加工效率低",
     "若允许R≥D/4(D=刀具直径)效率提升明显"),

    # 深腔 D/W > 4
    (lambda p: p.get("cavity_dw", 0) > 4, "CNC-深腔",
     "warn", "腔深比D/W={:.1f}>4, 刀具悬伸过长→震刀/让刀",
     "建议: 1)短刀开粗+长刀清根 2)考虑电火花 3)考虑五轴倾斜加工"),
    (lambda p: p.get("cavity_dw", 0) > 6, "CNC-深腔",
     "fatal", "腔深比D/W={:.1f}>6, 普通CNC无法加工, 刀具悬伸不足",
     "建议: 电火花加工(EDM) 或 拆分多件装配"),

    # 细长件 L/min(W,H) > 10
    (lambda p: p.get("slenderness", 0) > 10, "CNC-细长件",
     "warn", "长径比{:.1f}>10, 加工中变形风险大",
     "建议: 1)增加辅助支撑/跟刀架 2)多次翻面, 每次余量≤0.5mm"),
    (lambda p: p.get("slenderness", 0) > 15, "CNC-细长件",
     "fatal", "长径比{:.1f}>15, 普通装夹无法保证精度",
     "建议: 中心架 + 跟刀架, 或分两段加工后焊接"),

    # 过大件 > 800mm
    (lambda p: max(p.get("width",0), p.get("height",0), p.get("depth",0)) > 800,
     "CNC-超大件", "warn", "最大尺寸>800mm, 需龙门机床(Gantry)",
     "需确认工厂是否有龙门CNC; 大件装夹/运输需提前规划"),

    # 螺纹 < M2
    (lambda p: p.get("min_thread", "") == "M1.6" or p.get("min_thread", "") == "M1.4",
     "CNC-微螺纹", "warn", "螺纹<M2, 容易断丝锥",
     "建议: 1)使用挤压丝锥 2)或改嵌件 3)或改为M2以上"),
]

# ── 线切割规则 ──
WEDM_RULES = [
    (lambda p: p.get("inner_corner_r", 0) < 0.15, "WEDM-内角",
     "warn", "线切割内R角<0.15mm, 钼丝/铜丝有直径限制",
     "快丝钼丝0.18mm→R≥0.15mm；慢丝铜丝0.25mm→R≥0.2mm"),
    (lambda p: p.get("min_wall", 999) < 1.0, "WEDM-薄壁",
     "warn", "线切割薄壁<1mm, 放电热影响区可能导致变形",
     "建议: 降低放电能量, 多次轻切"),
    (lambda p: p.get("thickness", 0) > 300, "WEDM-厚度",
     "fatal", "线切割厚度>300mm, 穿丝困难, 效率极低",
     "建议: 考虑水刀切割或带锯+后续机加工"),
    (lambda p: p.get("slenderness", 0) > 30, "WEDM-细长",
     "fatal", "线切割细长比>30, 放电变形导致切割线弯曲",
     "建议: 分成多段, 加辅助支撑"),
]

# ── 3D打印(SLM/SLS)规则 ──
AM_RULES = [
    (lambda p: p.get("min_wall", 999) < 0.3, "AM-薄壁",
     "fatal", "SLM最小壁厚<0.3mm, 粉末无法铺展/熔合不足",
     "建议: 增大壁厚至≥0.3mm (不锈钢≥0.4mm)"),
    (lambda p: 0.3 <= p.get("min_wall", 999) < 0.6, "AM-薄壁",
     "warn", "SLM壁厚{:.1f}mm, 存在翘曲风险",
     "建议: 添加支撑结构, 优化摆放角度"),
    (lambda p: p.get("escape_hole", 0) < 2.0 and p.get("has_closed_cavity", False),
     "AM-逃逸孔", "fatal", "封闭腔体无逃逸孔(≥2mm), 粉末无法清除",
     "每个封闭内腔至少2个Φ≥2mm逃逸孔"),
    (lambda p: p.get("overhang_angle", 0) > 45, "AM-悬垂",
     "warn", "悬垂角度>{:.0f}°>45°, 需要支撑",
     "建议: 1)优化设计减小悬垂 2)添加支撑(需后处理去除)"),
    (lambda p: p.get("hole_d_min", 0) < 1.0, "AM-小孔",
     "warn", "SLM最小孔径{:.1f}mm<1mm, 可能闭合",
     "建议: 孔径≥1mm；打完后铰孔/钻通"),
    (lambda p: p.get("max_dim", 0) > 250, "AM-尺寸",
     "warn", "最大尺寸>250mm, 需确认打印平台尺寸",
     "默认SLM平台250×250mm; 更大需拆分+焊接"),
    (lambda p: True, "AM-公差",
     "info", "默认公差±0.2~0.3mm, 精密面需预留0.5mm加工余量",
     "关键配合面标注CNC后加工"),
]

# ── 钣金规则 ──
SHEET_METAL_RULES = [
    (lambda p: p.get("bend_r", 0) < p.get("thickness", 1), "钣金-弯曲",
     "fatal", "弯曲半径R{:.1f}<板厚{:.1f}, 会开裂",
     "建议: 最小弯曲半径≥1×板厚(铝≥1.5t)"),
    (lambda p: p.get("hole_edge", 0) < p.get("thickness", 1)*2, "钣金-孔边",
     "warn", "孔边距{:.1f}<2×板厚{:.1f}, 孔会拉变形",
     "建议: 孔距弯曲线≥2×板厚 或 先折弯后钻孔"),
    (lambda p: p.get("min_flange", 0) < 4*p.get("thickness", 1), "钣金-折弯高",
     "warn", "最小折弯高{:.1f}<4×板厚, 下模无法支撑",
     "建议: 折弯高度≥4×板厚"),
]

# ── 通用材料规则 ──
MATERIAL_RULES = [
    (lambda p: p.get("material_hb", 0) > 300 and "磨削" not in p.get("processes", ""),
     "材料-硬度", "fatal", "硬度>300HB, 车削/铣削无法加工(刀具急剧磨损)",
     "建议: 先退火→加工→淬火→磨削"),
    (lambda p: p.get("material_type") == "玻璃", "材料-玻璃",
     "warn", "K9玻璃/石英玻璃: 脆性材料, CNC易崩边",
     "建议: 需要专用研磨/抛光工艺; 薄壁玻璃(Φ9×87)难加工"),
    (lambda p: p.get("material_type") in ("钛", "钛合金"), "材料-钛合金",
     "warn", "钛合金: 导热差、弹性模量低、刀具易磨损",
     "建议: 低切削速度, 足量冷却, 专用刀具, 小切深"),
]

# ── 公差可行性 ──
TOLERANCE_CAPABILITY = {
    ("CNC", "一般"): "±0.1mm",
    ("CNC", "精密"): "±0.02mm",
    ("磨削", "一般"): "±0.01mm",
    ("磨削", "精密"): "±0.005mm",
    ("线切割", "快丝"): "±0.03mm",
    ("线切割", "慢丝"): "±0.01mm",
    ("3D打印", "SLM"): "±0.2mm",
    ("3D打印", "SLA"): "±0.1mm",
    ("钣金", "一般"): "±0.2mm",
}

def check_dfm(params: dict) -> dict:
    """
    DFM综合检查。
    
    输入:
    {
      "process": "CNC",         # 主工艺
      "width": 100, "height": 80, "depth": 30,  # 包围盒
      "min_wall": 2.0,          # 最小壁厚
      "hole_ld": 5.0,           # 最大孔深径比
      "inner_corner_r": 0.0,    # 最小内圆角半径 (0=尖角)
      "cavity_dw": 2.0,         # 最大腔深宽比
      "slenderness": 5.0,       # 长细比
      "min_thread": "M2",       # 最小螺纹
      "material_hb": 200,       # 材料硬度HB
      "material_type": "碳钢",  # 材料类型
      "thickness": 5,           # 板厚(钣金用)
      "bend_r": 0,              # 最小弯曲半径
      ...
    }
    
    输出:
    {
      "overall": "可制造",
      "risk": "medium",         # low/medium/high/fatal
      "issues": [
        {"code": "CNC-薄壁", "severity": "warn", "detail": "...", "fix": "..."},
      ],
      "tolerance_capability": "±0.1mm",
      "tolerance_feasible": True,
    }
    """
    process = params.get("process", "CNC")
    issues = []

    # 选规则表
    rule_tables = []
    if process in ("CNC", "车削", "铣削", "钻孔"):
        rule_tables.append(("CNC", CNC_RULES))
    if process in ("线切割", "WEDM"):
        rule_tables.append(("WEDM", WEDM_RULES))
    if process in ("3D打印", "SLM", "SLS", "SLA", "AM"):
        rule_tables.append(("AM", AM_RULES))
    if process in ("钣金", "折弯", "冲压"):
        rule_tables.append(("钣金", SHEET_METAL_RULES))
    if not rule_tables:
        rule_tables.append(("通用", CNC_RULES))  # 默认用CNC规则

    def _safe_format(tpl, p):
        """Safe format: try named params, then positional, then raw"""
        import re
        # Replace bare {:.Nf} with {value_N:.Nf} using matching param names
        bare_pos = re.findall(r'\{:[0-9.]*f?\}', tpl)
        if not bare_pos:
            try: return tpl.format(**p)
            except: return tpl
        # Try to match fields
        result = tpl
        for placeholder in bare_pos:
            for key in ['slenderness','hole_ld','cavity_dw','min_wall','inner_corner_r','bend_r','hole_edge','min_flange','thickness']:
                if p.get(key):
                    test = placeholder.replace('{:', '{'+key+':')
                    try:
                        test.format(**p)
                        result = result.replace(placeholder, test)
                        break
                    except: continue
        try: return result.format(**p)
        except: return tpl

    for _, rules in rule_tables:
        for condition, code, severity, detail_tpl, fix in rules:
            if condition(params):
                detail = _safe_format(detail_tpl, params)
                issues.append({
                    "code": code,
                    "severity": severity,
                    "detail": detail,
                    "fix": fix,
                })

    # 材料规则
    for condition, code, severity, detail, fix in MATERIAL_RULES:
        if condition(params):
            issues.append({"code": code, "severity": severity, "detail": detail, "fix": fix})

    # 公差检查
    tolerance = params.get("tolerance", "±0.1mm")
    tolerance_ok = True
    if process in ("CNC", "车削", "铣削"):
        cap = TOLERANCE_CAPABILITY.get(("CNC", "精密"), "±0.02mm")
        tol_val = _parse_tol(tolerance)
        if tol_val < 0.02:
            tolerance_ok = False
            issues.append({
                "code": "公差-不可达",
                "severity": "fatal",
                "detail": f"要求的{tolerance}超出CNC能力(±0.02mm)",
                "fix": "需要磨削或研磨工序达到该公差",
            })

    if process == "3D打印":
        cap = TOLERANCE_CAPABILITY.get(("3D打印", "SLM"), "±0.2mm")
        tol_val = _parse_tol(tolerance)
        if tol_val < 0.15:
            tolerance_ok = False
            issues.append({
                "code": "公差-不可达",
                "severity": "fatal",
                "detail": f"要求的{tolerance}超出SLM能力(±0.2mm)",
                "fix": "SLM件预留0.5mm余量→后续CNC到精公差",
            })

    # 总体评估
    fatals = [i for i in issues if i["severity"] == "fatal"]
    warns = [i for i in issues if i["severity"] == "warn"]
    infos = [i for i in issues if i["severity"] == "info"]

    if fatals:
        overall = "不可制造 (致命缺陷)"
        risk = "fatal"
    elif len(warns) >= 3:
        overall = "可制造但风险高"
        risk = "high"
    elif warns:
        overall = "可制造 (有工程建议)"
        risk = "medium"
    else:
        overall = "可制造 (无显著问题)"
        risk = "low"

    return {
        "overall": overall,
        "risk": risk,
        "issues": issues,
        "fatal_count": len(fatals),
        "warn_count": len(warns),
        "info_count": len(infos),
        "tolerance_feasible": tolerance_ok,
    }


def _parse_tol(tol_str: str) -> float:
    """'±0.05mm' → 0.05"""
    import re
    m = re.search(r'([0-9.]+)', tol_str)
    return float(m.group(1)) if m else 0.1


# ── 测试 ──
if __name__ == "__main__":
    import json

    # 案例1: 滑条 610×450×8mm 薄壁细长
    p1 = {"process": "CNC", "width": 610, "height": 450, "depth": 8,
          "min_wall": 8, "slenderness": 76, "material_hb": 200, "max_dim": 610,
          "tolerance": "±0.05mm", "min_thread": "M3",
          "hole_ld": 0, "inner_corner_r": 0, "cavity_dw": 0}
    print("=== 案例1: 复材滑条 610×450×8 ===")
    r1 = check_dfm(p1)
    print(json.dumps(r1, ensure_ascii=False, indent=2))

    # 案例2: K9玻璃导光柱 Φ9×87
    p2 = {"process": "CNC", "width": 9, "height": 9, "depth": 87,
          "min_wall": 9, "slenderness": 9.7, "material_hb": 500,
          "material_type": "玻璃", "max_dim": 87,
          "tolerance": "±0.1mm",
          "hole_ld": 0, "inner_corner_r": 0, "cavity_dw": 0}
    print("\n=== 案例2: K9玻璃导光柱 Φ9×87 ===")
    r2 = check_dfm(p2)
    print(json.dumps(r2, ensure_ascii=False, indent=2))
