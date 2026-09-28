# -*- coding: utf-8 -*-
"""
C5 白盒报价说明器：将 calc_quote 返回的 dict 逐项拆解为可读的 line_items + 公式 + 中文说明。

设计原则：
  1. 所有数值来自 calc_quote 的真实返回，不编造价格。
  2. calc_quote 未直接返回的中间变量（mat_price, fixed_coef, max_dim_mm,
     thread_count, profit_rate）从已知明细反算，公式字符串含实际数值代入。
  3. surface 处理的 surf_fixed / surf_area_rate 通过 lazy import
     app.main_lite 的 SURF_FIXED_FEE / SURF_AREA_RATE 获取（单一真相源），
     import 失败时回退为符号表示。

calc_quote 白盒公式（app/main_lite.py L251-305）：
    material_cost  = weight_kg × mat_price
    machining_cost = (80 + 0.15 × max_dim_mm) × fixed_coef
    setup_cost     = (30 / quantity) × fixed_coef
    qc_cost        = 20 × fixed_coef
    surface_cost   = surf_fixed + surf_area_rate × surface_area_dm2   (大件封顶 ≤ 0.45×(mat+mach))
    thread_cost    = thread_count × thread_fee_per_hole
    base_price     = 15 + material_cost + machining_cost × tol_coef × rough_coef + setup_cost + qc_cost
    unit_price     = base_price + surface_cost + thread_cost
    total          = unit_price × quantity × volume_discount          (direct 模式再 × direct_ratio)
    profit         = total × profit_rate                              (xometry: 0.30, direct: 0.25)
    final          = total + profit
"""
from __future__ import annotations

from typing import Any, Dict, List


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    """安全除法，避免除零。"""
    if b == 0:
        return default
    return a / b


def _round(v: Any, n: int = 2) -> float:
    """统一舍入，None 安全。"""
    if v is None:
        return 0.0
    return round(float(v), n)


def _get_surface_coeffs(surface: str) -> tuple:
    """
    获取表面处理的固定费和面积费率。
    lazy import app.main_lite 的常量（单一真相源），失败回退 (符号, None)。
    """
    try:
        from app.main_lite import SURF_FIXED_FEE, SURF_AREA_RATE
        s = surface or "无"
        return SURF_FIXED_FEE.get(s, 0.0), SURF_AREA_RATE.get(s, 0.0)
    except Exception:
        return None, None  # 符号表示


def explain(quote_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 calc_quote 返回的 dict 拆解为白盒说明。

    输入: calc_quote(...) 返回的 dict
    输出: {
        "line_items": [ {name, formula, value, unit, category}, ... ],
        "subtotals": {base_cost, overhead, extras, profit, final},
        "formulas": {unit_price, total, final},
        "summary_text": "中文逐项说明"
    }
    """
    q = quote_result or {}
    cb = q.get("cost_breakdown", {}) or {}

    # ── 直接从返回值提取的明细 ──
    base_fee = float(cb.get("base_fee", 15.0))
    material_cost = float(cb.get("material_cost", 0.0))
    machining_cost = float(cb.get("machining_cost", 0.0))
    setup_cost = float(cb.get("setup_cost", 0.0))
    qc_cost = float(cb.get("qc_cost", 0.0))
    surface_cost = float(cb.get("surface_cost", 0.0))
    tol_coef = float(cb.get("tol_coef", 1.0))
    rough_coef = float(cb.get("rough_coef", 1.0))
    thread_cost = float(cb.get("thread_cost", 0.0))
    thread_fee_per_hole = float(cb.get("thread_fee_per_hole", 0.0))
    surface_area_dm2 = float(cb.get("surface_area_dm2", 0.0))

    weight_kg = float(q.get("weight_kg", 0.0))
    quantity = int(q.get("quantity", 1))
    unit_price = float(q.get("unit_price", 0.0))
    total_price = float(q.get("total_price", 0.0))
    profit = float(q.get("profit", 0.0))
    final_price = float(q.get("final_price", 0.0))
    volume_discount = float(q.get("volume_discount", 1.0))
    price_mode = q.get("price_mode", "xometry")
    direct_ratio = q.get("direct_ratio")
    material = q.get("material", "未知")
    surface = q.get("surface", "无")

    # ── 反算中间变量（calc_quote 未直接返回）──
    # mat_price = material_cost / weight_kg
    mat_price = _safe_div(material_cost, weight_kg, 0.0) if weight_kg > 0 else 0.0

    # fixed_coef = qc_cost / 20  (因为 qc_cost = 20 × fixed_coef)
    fixed_coef = _safe_div(qc_cost, 20.0, 1.0)

    # max_dim_mm = (machining_cost / fixed_coef - 80) / 0.15
    if fixed_coef > 0:
        max_dim_mm = (_safe_div(machining_cost, fixed_coef) - 80.0) / 0.15
    else:
        max_dim_mm = 0.0

    # thread_count = thread_cost / thread_fee_per_hole
    thread_count = int(_safe_div(thread_cost, thread_fee_per_hole, 0.0)) if thread_fee_per_hole > 0 else 0

    # profit_rate = profit / total_price
    profit_rate = _safe_div(profit, total_price, 0.0) if total_price > 0 else 0.0

    # surface 系数
    surf_fixed, surf_area_rate = _get_surface_coeffs(surface)

    # base_price = unit_price - surface_cost - thread_cost
    base_price = unit_price - surface_cost - thread_cost

    # ── 构建 line_items ──
    line_items: List[Dict[str, Any]] = []

    # 1. 基础费
    line_items.append({
        "name": "基础费",
        "formula": f"固定基础费 = {base_fee}",
        "value": _round(base_fee),
        "unit": "元",
        "category": "base",
    })

    # 2. 材料费
    line_items.append({
        "name": "材料费",
        "formula": f"weight_kg × mat_price = {weight_kg} × {mat_price}",
        "value": _round(material_cost),
        "unit": "元",
        "category": "material",
    })

    # 3. 加工费
    line_items.append({
        "name": "加工费",
        "formula": (
            f"(80 + 0.15 × max_dim_mm) × fixed_coef "
            f"= (80 + 0.15 × {_round(max_dim_mm, 1)}) × {_round(fixed_coef, 2)}"
        ),
        "value": _round(machining_cost),
        "unit": "元",
        "category": "machining",
    })

    # 4. 设置费
    line_items.append({
        "name": "设置费",
        "formula": f"(30 / quantity) × fixed_coef = (30 / {quantity}) × {_round(fixed_coef, 2)}",
        "value": _round(setup_cost),
        "unit": "元",
        "category": "overhead",
    })

    # 5. 质控费
    line_items.append({
        "name": "质控费",
        "formula": f"20 × fixed_coef = 20 × {_round(fixed_coef, 2)}",
        "value": _round(qc_cost),
        "unit": "元",
        "category": "overhead",
    })

    # 6. 表面费
    if surf_fixed is not None and surf_area_rate is not None:
        surf_formula = (
            f"surf_fixed + surf_area_rate × surface_area_dm2 "
            f"= {surf_fixed} + {surf_area_rate} × {surface_area_dm2}"
        )
    else:
        surf_formula = f"surf_fixed + surf_area_rate × {surface_area_dm2} (系数未导入)"
    line_items.append({
        "name": "表面费",
        "formula": surf_formula,
        "value": _round(surface_cost),
        "unit": "元",
        "category": "extras",
    })

    # 7. 螺纹费
    line_items.append({
        "name": "螺纹费",
        "formula": (
            f"thread_count × thread_fee_per_hole "
            f"= {thread_count} × {thread_fee_per_hole}"
        ),
        "value": _round(thread_cost),
        "unit": "元",
        "category": "extras",
    })

    # 8. 利润
    mode_label = "直客" if price_mode == "direct" else "Xometry"
    line_items.append({
        "name": "利润",
        "formula": f"total × profit_rate = {_round(total_price)} × {_round(profit_rate, 4)} ({mode_label}模式)",
        "value": _round(profit),
        "unit": "元",
        "category": "profit",
    })

    # ── subtotals ──
    subtotals = {
        "base_cost": _round(material_cost + machining_cost),   # 材料+加工
        "overhead": _round(setup_cost + qc_cost),              # 设置+质控
        "extras": _round(surface_cost + thread_cost),          # 表面+螺纹
        "profit": _round(profit),
        "final": _round(final_price),
    }

    # ── formulas ──
    direct_part = " × direct_ratio" if price_mode == "direct" and direct_ratio else ""
    formulas = {
        "unit_price": (
            f"15 + material_cost + machining_cost × tol_coef × rough_coef "
            f"+ setup_cost + qc_cost + surface_cost + thread_cost "
            f"= 15 + {_round(material_cost)} + {_round(machining_cost)} × {tol_coef} × {rough_coef} "
            f"+ {_round(setup_cost)} + {_round(qc_cost)} + {_round(surface_cost)} + {_round(thread_cost)} "
            f"= {_round(unit_price)}"
        ),
        "total": (
            f"unit_price × quantity × volume_discount{direct_part} "
            f"= {_round(unit_price)} × {quantity} × {volume_discount}"
            + (f" × {direct_ratio}" if direct_part else "")
            + f" = {_round(total_price)}"
        ),
        "final": f"total + profit = {_round(total_price)} + {_round(profit)} = {_round(final_price)}",
    }

    # ── summary_text（中文逐项说明）──
    lines = []
    lines.append(f"【{material} 零件报价白盒拆解】")
    lines.append(f"数量: {quantity} 件 | 重量: {weight_kg} kg | 表面处理: {surface} | 价格模式: {mode_label}")
    lines.append("")
    lines.append("一、成本明细（逐项）：")
    lines.append(f"  1. 基础费: {base_fee} 元（固定起步费）")
    lines.append(f"  2. 材料费: {_round(material_cost)} 元 = {weight_kg} kg × {mat_price} 元/kg")
    lines.append(f"  3. 加工费: {_round(machining_cost)} 元 = (80 + 0.15 × {_round(max_dim_mm, 1)}) × {_round(fixed_coef, 2)}")
    lines.append(f"  4. 设置费: {_round(setup_cost)} 元 = (30 / {quantity}) × {_round(fixed_coef, 2)}")
    lines.append(f"  5. 质控费: {_round(qc_cost)} 元 = 20 × {_round(fixed_coef, 2)}")
    if surf_fixed is not None and surf_area_rate is not None:
        lines.append(f"  6. 表面费: {_round(surface_cost)} 元 = {surf_fixed} + {surf_area_rate} × {surface_area_dm2} dm²")
    else:
        lines.append(f"  6. 表面费: {_round(surface_cost)} 元（面积 {surface_area_dm2} dm²）")
    lines.append(f"  7. 螺纹费: {_round(thread_cost)} 元 = {thread_count} 孔 × {thread_fee_per_hole} 元/孔")
    lines.append("")
    lines.append("二、价格汇总：")
    lines.append(f"  单价 = 15 + {_round(material_cost)} + {_round(machining_cost)}×{tol_coef}×{rough_coef} + {_round(setup_cost)} + {_round(qc_cost)} + {_round(surface_cost)} + {_round(thread_cost)} = {_round(unit_price)} 元")
    lines.append(f"  总价 = {_round(unit_price)} × {quantity} × {volume_discount}{(' × ' + str(direct_ratio)) if direct_part else ''} = {_round(total_price)} 元")
    lines.append(f"  利润 = {_round(total_price)} × {_round(profit_rate, 4)} = {_round(profit)} 元")
    lines.append(f"  最终价 = {_round(total_price)} + {_round(profit)} = {_round(final_price)} 元")
    lines.append("")
    lines.append("三、小计：")
    lines.append(f"  基础成本(材料+加工): {subtotals['base_cost']} 元")
    lines.append(f"  间接成本(设置+质控): {subtotals['overhead']} 元")
    lines.append(f"  附加费(表面+螺纹): {subtotals['extras']} 元")
    lines.append(f"  利润: {subtotals['profit']} 元")
    lines.append(f"  最终报价: {subtotals['final']} 元")

    summary_text = "\n".join(lines)

    return {
        "line_items": line_items,
        "subtotals": subtotals,
        "formulas": formulas,
        "summary_text": summary_text,
    }