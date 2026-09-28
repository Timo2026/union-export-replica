"""services.fleet_v4.calculation — 纯计算层 (从 FleetCoordinator v4 抽取).

设计原则:
  - 100% pure Python, 零 LLM 算术 (铁律①)
  - 与项目 Timo 引擎互补: Timo 走真实 STEP 几何 + OCP, CalculationEngine 走参数化公式
  - 适用于: 用户没传 STEP 但描述了零件参数的场景 (表单式 RFQ)
  - 计算结果 4 位小数精度

材料库/价格表 与原 v4 完全一致 (6061/7075/304/碳钢 + 4 种表面处理).
"""
from __future__ import annotations

import math
from typing import Any, Dict

# ─── 材料库 ─── (精确参数, 不依赖 LLM 记忆)
MATERIAL_DB: Dict[str, Dict[str, Any]] = {
    "6061": {
        "name": "6061铝合金",
        "density_g_cm3": 2.70,
        "price_kg": 25,
        "yield_mpa": 275,
        "tensile_mpa": 390,
        "elongation_pct": 8,
        "hardness_hb": 95,
        "anodizing_ok": True,
    },
    "7075": {
        "name": "7075铝合金",
        "density_g_cm3": 2.81,
        "price_kg": 45,
        "yield_mpa": 503,
        "tensile_mpa": 572,
        "elongation_pct": 11,
        "hardness_hb": 150,
        "anodizing_ok": False,
    },
    "304": {
        "name": "304不锈钢",
        "density_g_cm3": 7.93,
        "price_kg": 35,
        "yield_mpa": 205,
        "tensile_mpa": 515,
        "elongation_pct": 40,
        "hardness_hb": 201,
        "anodizing_ok": False,
    },
    "carbon_steel": {
        "name": "碳钢",
        "density_g_cm3": 7.85,
        "price_kg": 8,
        "yield_mpa": 235,
        "tensile_mpa": 400,
        "elongation_pct": 22,
        "hardness_hb": 131,
        "anodizing_ok": False,
    },
}

# ─── 表面处理价格 (元/m²) ───
SURFACE_PRICE: Dict[str, float] = {
    "none": 0,
    "anodizing": 120,    # 黑色阳极氧化
    "pvd": 350,          # PVD 涂层
    "spray": 80,         # 喷涂
    "electroplating": 100,  # 电镀
}

# ─── CNC 加工费率 ───
MACHINING_RATE = 80  # 元/小时

# ─── 毛利率 ───
GROSS_MARGIN = 0.20  # 20%


class CalculationEngine:
    """精确几何/重量/费用计算 — 100% 确定性, 零误差."""

    @staticmethod
    def cylinder_volume_outer_inner_mm(outer_d: float, inner_d: float, length: float) -> float:
        """空心圆柱体积 (法兰/轴套), mm → cm³.
        V = π × (R² - r²) × L
        """
        if outer_d <= inner_d or length <= 0:
            raise ValueError(f"invalid dimensions: outer_d={outer_d}, inner_d={inner_d}, length={length}")
        od_cm = outer_d / 10.0
        id_cm = inner_d / 10.0
        l_cm = length / 10.0
        return math.pi * ((od_cm / 2) ** 2 - (id_cm / 2) ** 2) * l_cm

    @staticmethod
    def solid_cylinder_volume_mm(d: float, length: float) -> float:
        """实心圆柱体积, mm → cm³. V = π × r² × h; r=d/2 mm→d/20 cm; h mm→h/10 cm."""
        if d <= 0 or length <= 0:
            raise ValueError(f"invalid dimensions: d={d}, length={length}")
        return math.pi * (d / 20.0) ** 2 * (length / 10.0)

    @staticmethod
    def rectangular_block_volume_mm(w: float, h: float, t: float) -> float:
        """长方体体积, mm → cm³."""
        if w <= 0 or h <= 0 or t <= 0:
            raise ValueError(f"invalid dimensions: w={w}, h={h}, t={t}")
        return (w / 10.0) * (h / 10.0) * (t / 10.0)

    @staticmethod
    def weight_kg(volume_cm3: float, density_g_cm3: float) -> float:
        """重量计算, kg."""
        if volume_cm3 < 0 or density_g_cm3 <= 0:
            raise ValueError(f"invalid: volume={volume_cm3}, density={density_g_cm3}")
        return (volume_cm3 * density_g_cm3) / 1000.0

    @staticmethod
    def surface_area_cylinder_outer_mm(outer_d: float, length: float) -> float:
        """圆柱外表面积, m² (含两个底面)."""
        if outer_d <= 0 or length <= 0:
            raise ValueError(f"invalid dimensions: outer_d={outer_d}, length={length}")
        od_cm = outer_d / 10.0
        l_cm = length / 10.0
        area_cm2 = math.pi * od_cm * l_cm + 2 * math.pi * (od_cm / 2) ** 2
        return area_cm2 / 10000.0


def calculate_quote(
    material: str,
    shape: str,
    dimensions: Dict[str, Any],
    quantity: int,
    surface: str = "none",
) -> Dict[str, Any]:
    """完整报价计算 — 与原 v4 完全一致 (方案文档 §5 测试用例验证).

    Args:
        material: 材料 (6061/7075/304/carbon_steel)
        shape: 零件形状 (flange/bushing/block)
        dimensions: 尺寸字典 (mm), 含 outer_d/inner_d/thickness/length/width/height/holes
        quantity: 数量
        surface: 表面处理 (none/anodizing/pvd/spray/electroplating)

    Returns:
        标准报价字典, 含 shape/material/volume_cm3/weight_kg_single/total_single/total_batch 等
    """
    mat = MATERIAL_DB.get(material)
    if mat is None:
        raise ValueError(f"unknown material: {material}; supported: {list(MATERIAL_DB.keys())}")
    if quantity <= 0:
        raise ValueError(f"invalid quantity: {quantity}")

    # 体积计算 (按形状分支)
    if shape == "flange":
        if not all(k in dimensions for k in ("outer_d", "inner_d", "thickness")):
            raise ValueError(f"flange requires outer_d, inner_d, thickness; got {list(dimensions.keys())}")
        volume_cm3 = CalculationEngine.cylinder_volume_outer_inner_mm(
            dimensions["outer_d"], dimensions["inner_d"], dimensions["thickness"]
        )
        surface_area_m2 = CalculationEngine.surface_area_cylinder_outer_mm(
            dimensions["outer_d"], dimensions["thickness"]
        )
    elif shape == "bushing":
        if not all(k in dimensions for k in ("outer_d", "inner_d", "length")):
            raise ValueError(f"bushing requires outer_d, inner_d, length; got {list(dimensions.keys())}")
        volume_cm3 = CalculationEngine.cylinder_volume_outer_inner_mm(
            dimensions["outer_d"], dimensions["inner_d"], dimensions["length"]
        )
        surface_area_m2 = CalculationEngine.surface_area_cylinder_outer_mm(
            dimensions["outer_d"], dimensions["length"]
        )
    elif shape == "block":
        if not all(k in dimensions for k in ("width", "height", "thickness")):
            raise ValueError(f"block requires width, height, thickness; got {list(dimensions.keys())}")
        volume_cm3 = CalculationEngine.rectangular_block_volume_mm(
            dimensions["width"], dimensions["height"], dimensions["thickness"]
        )
        w = dimensions["width"] / 10.0
        h = dimensions["height"] / 10.0
        t = dimensions["thickness"] / 10.0
        area_cm2 = 2 * (w * h + w * t + h * t)
        surface_area_m2 = area_cm2 / 10000.0
    else:
        raise ValueError(f"unknown shape: {shape}; supported: flange/bushing/block")

    # 重量 + 工时估算
    weight_kg_single = CalculationEngine.weight_kg(volume_cm3, mat["density_g_cm3"])
    holes = dimensions.get("holes", 0)
    machining_hours = (weight_kg_single * 0.5) + (holes * 0.1)
    if machining_hours < 0.5:
        machining_hours = 0.5

    # 费用分项 (含 15% 材料损耗)
    material_cost_single = weight_kg_single * mat["price_kg"] * 1.15
    machining_cost_single = machining_hours * MACHINING_RATE
    surface_cost_single = surface_area_m2 * SURFACE_PRICE.get(surface, 0)
    total_cost_single = material_cost_single + machining_cost_single + surface_cost_single
    total_cost_single_with_margin = total_cost_single * (1 + GROSS_MARGIN)
    total_cost_batch = total_cost_single_with_margin * quantity

    return {
        "shape": shape,
        "material": material,
        "material_name": mat["name"],
        "volume_cm3": round(volume_cm3, 2),
        "weight_kg_single": round(weight_kg_single, 3),
        "machining_hours_single": round(machining_hours, 2),
        "surface_area_m2": round(surface_area_m2, 3),
        "material_cost_single": round(material_cost_single, 2),
        "machining_cost_single": round(machining_cost_single, 2),
        "surface_cost_single": round(surface_cost_single, 2),
        "total_single": round(total_cost_single_with_margin, 2),
        "total_batch": round(total_cost_batch, 2),
        "quantity": quantity,
        "surface": surface,
    }
