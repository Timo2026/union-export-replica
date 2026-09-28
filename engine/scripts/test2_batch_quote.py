# -*- coding: utf-8 -*-
"""
批量报价执行脚本 — test2 (112个常规机加件)
对每个零件执行：STEP解析→几何提取→材料识别→重量计算→报价(小件calc_quote/大件big_part_price)
输出：output/test2_quote_result.csv + output/test2_quote_report.md
"""
import os
import sys
import csv
import json
import re
import time
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 导入报价引擎
from app.main_lite import (
    calc_quote,
    MAT_COEFS, SURF_COEFS,
    MAT_PRICE_PER_KG, MAT_FIXED_COEF,
    RAW_MATERIAL_PRICE, BIG_PART_MAT_PRICE,
    SURF_FIXED_FEE, SURF_AREA_RATE,
    TOL_COEF, ROUGH_COEF,
    THREAD_FEE_PER_HOLE, THREAD_FEE_PER_HOLE_BY_MAT,
    SURF_INVALID,
)

# ══════════════════════════════════════════════════════════
# 路径配置
# ══════════════════════════════════════════════════════════
STEP_DIR = PROJECT_ROOT / "data" / "batch_quote_test2" / "常规机加件"
PDF_CSV = PROJECT_ROOT / "output" / "test2_pdf_extract.csv"
OUTPUT_DIR = PROJECT_ROOT / "output"
RESULT_CSV = OUTPUT_DIR / "test2_quote_result.csv"
REPORT_MD = OUTPUT_DIR / "test2_quote_report.md"

# ══════════════════════════════════════════════════════════
# 材料映射表：PDF材料名 → 报价引擎材料key
# 任务要求：
#   6061铝合金→6061, 304不锈钢→304, 316L不锈钢→316l, 黄铜→黄铜,
#   YG8钨合金→黄铜(近似), 440C→45钢(近似),
#   ABS→6061(非金属按最低价), POM→6061
# ══════════════════════════════════════════════════════════
MATERIAL_MAP = {
    "6061铝合金": "6061",
    "304不锈钢": "304",
    "316l不锈钢": "316l",
    "316L不锈钢": "316l",
    "黄铜": "黄铜",
    "YG8钨合金": "黄铜",      # 钨合金近似黄铜（任务要求）
    "440C不锈钢": "45钢",     # 440C近似45钢（任务要求）
    "ABS": "6061",            # 非金属按最低价（任务要求）
    "POM": "6061",            # 非金属按最低价（任务要求）
}

# 密度表（g/cm³，任务要求）
DENSITY_MAP = {
    "6061": 2.70, "304": 7.93, "316l": 7.98, "45钢": 7.85, "q235": 7.85,
    "7075": 2.81, "黄铜": 8.50, "tc4": 4.51,
    "ABS": 1.05, "POM": 1.41, "YG8": 14.5, "440C": 7.85,
}

# 非金属密度（按原始材料名查询）
NONMETAL_DENSITY = {
    "ABS": 1.05, "POM": 1.41,
}

# ══════════════════════════════════════════════════════════
# 表面处理映射：PDF表面处理 → 报价引擎表面处理key
# 任务要求：
#   喷砂+阳极氧化→阳极氧化, 喷砂+阳极氧化+喷漆→阳极氧化,
#   氮化钛涂层→镀铬(近似), DLC涂层→镀铬(近似),
#   钝化→无, 喷砂→无
# ══════════════════════════════════════════════════════════
def normalize_surface(surf):
    """表面处理标准化"""
    if not surf or surf.strip() == "":
        return "无"
    s = surf.strip()
    # 精确匹配优先
    if s == "喷砂+阳极氧化":
        return "阳极氧化"
    if s == "喷砂+阳极氧化+喷漆":
        return "阳极氧化"
    if s == "氮化钛涂层":
        return "镀铬"
    if s == "DLC涂层":
        return "镀铬"
    if s == "钝化":
        return "无"
    if s == "喷砂":
        return "无"
    if s == "阳极氧化":
        return "阳极氧化"
    if s == "无":
        return "无"
    if s == "选择黑色原料":
        return "无"  # 选择黑色原料不算表面处理
    # 包含匹配兜底
    if "阳极氧化" in s:
        return "阳极氧化"
    if "喷漆" in s:
        return "喷漆"
    if "镀铬" in s or "氮化钛" in s or "DLC" in s.upper():
        return "镀铬"
    if "镀锌" in s:
        return "镀锌"
    if "镀镍" in s:
        return "镀镍"
    if "发黑" in s:
        return "发黑"
    if "磷化" in s:
        return "磷化"
    if "喷砂" in s or "钝化" in s:
        return "无"
    return "无"


def normalize_material(mat):
    """材料名标准化，返回 (material_key, original_material_for_density)"""
    if not mat:
        return "6061", "6061"
    # 精确匹配
    if mat in MATERIAL_MAP:
        return MATERIAL_MAP[mat], mat
    # 模糊匹配
    mat_lower = mat.lower()
    if "6061" in mat_lower or "铝" in mat:
        return "6061", "6061铝合金"
    if "316" in mat_lower:
        return "316l", "316L不锈钢"
    if "304" in mat_lower:
        return "304", "304不锈钢"
    if "440c" in mat_lower:
        return "45钢", "440C不锈钢"
    if "yg8" in mat_lower or "钨" in mat:
        return "黄铜", "YG8钨合金"
    if "黄铜" in mat or "h59" in mat_lower:
        return "黄铜", "黄铜"
    if "abs" in mat_lower:
        return "6061", "ABS"
    if "pom" in mat_lower:
        return "6061", "POM"
    return "6061", mat


def get_density(material_key, original_material):
    """获取材料密度（g/cm³）"""
    # 非金属优先按原始材料名查
    if original_material in NONMETAL_DENSITY:
        return NONMETAL_DENSITY[original_material]
    # 按原始材料名查（YG8、440C等）
    if original_material in DENSITY_MAP:
        return DENSITY_MAP[original_material]
    # 按材料key查
    if material_key in DENSITY_MAP:
        return DENSITY_MAP[material_key]
    # 默认铝密度
    return 2.70


def normalize_tolerance(tol):
    """公差标准化：GB/T1804-m (中等)→中等, GB/T1804-f (精细)→精细"""
    if not tol:
        return "未知"
    if "精细" in tol or "f" in tol.lower():
        return "精细"
    if "中等" in tol or "m" in tol.lower():
        return "中等"
    if "粗糙" in tol or "c" in tol.lower():
        return "粗糙"
    return "未知"


def parse_roughness(ra_str):
    """解析粗糙度：Ra0.8→0.8, 空→0.0"""
    if not ra_str or ra_str.strip() == "":
        return 0.0
    m = re.search(r"Ra?([\d.]+)", ra_str, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return 0.0
    return 0.0


def parse_thread_count(tc_str):
    """解析螺纹孔数"""
    if not tc_str or tc_str.strip() == "":
        return 0
    try:
        return int(float(tc_str))
    except (ValueError, TypeError):
        return 0


def parse_quantity(q_str):
    """解析数量"""
    if not q_str or q_str.strip() == "":
        return 1
    try:
        return int(float(q_str))
    except (ValueError, TypeError):
        return 1


def find_step_file(part_number, step_dir):
    """根据零件号查找STEP文件"""
    prefix = str(part_number)
    for f in os.listdir(step_dir):
        if f.upper().endswith(".STEP") and f.startswith(prefix):
            return step_dir / f
    return None


def _cadquery_parse_step(step_path):
    """
    cadquery fallback：用BRep精确解析STEP文件几何。
    cadquery返回mm单位（与trimesh的米单位不同）。
    返回: {dim_x, dim_y, dim_z, volume_mm3, surface_area_mm2, ok, error}
    """
    out = {
        "dim_x": 0.0, "dim_y": 0.0, "dim_z": 0.0,
        "volume_mm3": 0.0, "surface_area_mm2": 0.0,
        "ok": False, "error": None,
    }
    try:
        import cadquery as cq
        shape = cq.importers.importStep(str(step_path))
        solid = shape.val()
        bbox = solid.BoundingBox()
        dim_x = float(bbox.xlen)
        dim_y = float(bbox.ylen)
        dim_z = float(bbox.zlen)
        if max(dim_x, dim_y, dim_z) <= 0:
            out["error"] = "cadquery bbox为0"
            return out
        out["dim_x"] = dim_x
        out["dim_y"] = dim_y
        out["dim_z"] = dim_z
        # cadquery Volume() 返回 mm³（精确BRep体积）
        vol_mm3 = float(solid.Volume())
        if vol_mm3 <= 0:
            # 复合体可能返回负体积，取绝对值；若仍为0则用bbox估算
            vol_mm3 = abs(vol_mm3) if vol_mm3 < 0 else dim_x * dim_y * dim_z
        out["volume_mm3"] = vol_mm3
        # 表面积：cadquery的Area()返回mm²（精确BRep表面积）
        try:
            out["surface_area_mm2"] = float(solid.Area())
        except Exception:
            # 退化情况用bbox表面积估算
            out["surface_area_mm2"] = 2.0 * (dim_x * dim_y + dim_y * dim_z + dim_x * dim_z)
        out["ok"] = True
        return out
    except Exception as e:
        out["error"] = f"cadquery: {str(e)[:180]}"
        return out


def parse_step_geometry(step_path):
    """
    用trimesh解析STEP文件几何，trimesh真正失败时用cadquery fallback。
    
    cadquery fallback触发条件（严格按任务要求"trimesh返回None或体积为0"）：
      - trimesh抛异常
      - trimesh返回None
      - trimesh extents为0
    非水密网格不触发cadquery（保留原bbox估算逻辑，避免精确体积反而触发更多fallback_weight）。
    
    返回: {dim_x, dim_y, dim_z, volume_mm3, surface_area_mm2, status, error, parse_method, volume_is_precise}
    - trimesh解析STEP返回米单位，需×1000转毫米
    - cadquery返回mm单位（BRep精确体积，无需实心率矫正）
    - parse_method: "trimesh" / "trimesh_bbox" / "cadquery" / "trimesh_bbox_only" / "failed"
    - volume_is_precise: True=cadquery BRep精确体积(无需0.5矫正), False=trimesh网格/bbox估算
    """
    result = {
        "dim_x": 0.0, "dim_y": 0.0, "dim_z": 0.0,
        "volume_mm3": 0.0, "surface_area_mm2": 0.0,
        "status": "failed", "error": None,
        "parse_method": "failed", "volume_is_precise": False,
    }

    # ── 阶段1: trimesh解析 ──
    trimesh_failed = True  # 默认失败，trimesh成功时置False
    trimesh_has_bbox = False  # trimesh至少给了bbox（extents有效）
    try:
        import trimesh
        m = trimesh.load(str(step_path), force="mesh")
        if m is None:
            result["error"] = "trimesh返回None"
        else:
            ext = m.extents
            # 米→毫米
            dim_x = float(ext[0]) * 1000.0
            dim_y = float(ext[1]) * 1000.0
            dim_z = float(ext[2]) * 1000.0
            if max(dim_x, dim_y, dim_z) <= 0:
                result["error"] = "trimesh extents为0"
            else:
                # trimesh至少给了有效bbox
                trimesh_has_bbox = True
                result["dim_x"] = round(dim_x, 2)
                result["dim_y"] = round(dim_y, 2)
                result["dim_z"] = round(dim_z, 2)
                # 表面积（trimesh的area对网格是可靠的）
                if hasattr(m, "area"):
                    result["surface_area_mm2"] = float(m.area) * 1e6  # m²→mm²

                is_watertight = bool(getattr(m, "is_watertight", False))
                if is_watertight and getattr(m, "volume", None) and abs(m.volume) > 0:
                    # 水密网格：trimesh体积可信
                    vol_m3 = abs(m.volume)
                    result["volume_mm3"] = vol_m3 * 1e9  # m³→mm³
                    result["parse_method"] = "trimesh"
                    result["volume_is_precise"] = False  # 网格体积仍需实心率矫正
                    result["status"] = "ok"
                    trimesh_failed = False
                    return result
                else:
                    # 非水密网格：trimesh体积不可信，用bbox估算（保持原逻辑）
                    result["volume_mm3"] = dim_x * dim_y * dim_z
                    if result["surface_area_mm2"] <= 0:
                        result["surface_area_mm2"] = 2.0 * (dim_x * dim_y + dim_y * dim_z + dim_x * dim_z)
                    result["parse_method"] = "trimesh_bbox"
                    result["volume_is_precise"] = False
                    result["status"] = "ok"
                    trimesh_failed = False
                    return result
    except Exception as e:
        result["error"] = f"trimesh: {str(e)[:150]}"

    # ── 阶段2: cadquery fallback ──
    # 触发条件：trimesh真正失败（返回None/抛异常/extents为0）
    if trimesh_failed:
        cq = _cadquery_parse_step(step_path)
        if cq["ok"]:
            # cadquery成功：用BRep精确几何
            result["dim_x"] = round(cq["dim_x"], 2)
            result["dim_y"] = round(cq["dim_y"], 2)
            result["dim_z"] = round(cq["dim_z"], 2)
            result["volume_mm3"] = cq["volume_mm3"]
            if cq["surface_area_mm2"] > 0:
                result["surface_area_mm2"] = cq["surface_area_mm2"]
            result["status"] = "ok"
            result["parse_method"] = "cadquery"
            result["volume_is_precise"] = True  # BRep精确体积，无需0.5实心率矫正
            result["error"] = None
            return result

    # ── 阶段3: 两者都失败 ──
    # 如果trimesh至少给了bbox（非水密但extents有效），保留bbox估算
    if trimesh_has_bbox and result["dim_x"] > 0 and result["dim_y"] > 0 and result["dim_z"] > 0:
        result["volume_mm3"] = result["dim_x"] * result["dim_y"] * result["dim_z"]
        result["surface_area_mm2"] = 2.0 * (
            result["dim_x"] * result["dim_y"]
            + result["dim_y"] * result["dim_z"]
            + result["dim_x"] * result["dim_z"]
        )
        result["status"] = "ok"
        result["parse_method"] = "trimesh_bbox_only"
        result["volume_is_precise"] = False
        return result

    # 完全失败
    if not result["error"]:
        result["error"] = "未知解析失败"
    return result


def fallback_geometry_by_filesize(step_path):
    """
    STEP解析失败时的降级估算（参考batch_quote_engine.py）
    按文件大小分级估算重量
    """
    file_size = os.path.getsize(step_path)
    if file_size > 500000:  # >500KB → 中等件
        weight_kg = 1.5
        dim_x, dim_y, dim_z = 200.0, 150.0, 100.0
    elif file_size > 100000:  # >100KB → 小件
        weight_kg = 0.3
        dim_x, dim_y, dim_z = 100.0, 80.0, 50.0
    else:
        weight_kg = 0.1
        dim_x, dim_y, dim_z = 50.0, 40.0, 30.0
    return {
        "dim_x": dim_x, "dim_y": dim_y, "dim_z": dim_z,
        "volume_mm3": dim_x * dim_y * dim_z,
        "surface_area_mm2": 2 * (dim_x * dim_y + dim_y * dim_z + dim_x * dim_z),
        "weight_kg_fallback": weight_kg,
        "file_size": file_size,
    }


def big_part_price(mat_key, surface, qty, weight_kg, dim_x, dim_y, dim_z,
                   surface_area_dm2, roughness_ra, thread_count, tolerance):
    """
    大件定价模型（与 batch_quote_engine.py 完全一致）
    返回完整成本明细
    """
    mat_coef = MAT_COEFS.get(mat_key.lower(), MAT_COEFS.get(mat_key, 1.3))
    # 材料费：大件用大件专用材料单价
    raw_price = BIG_PART_MAT_PRICE.get(
        mat_key.lower(),
        BIG_PART_MAT_PRICE.get(
            mat_key,
            RAW_MATERIAL_PRICE.get(mat_key.lower(), RAW_MATERIAL_PRICE.get(mat_key, 30.0))
        )
    )
    material_cost = weight_kg * raw_price

    # 加工费：基础工时费 + 尺寸复杂度
    max_dim = max(dim_x, dim_y, dim_z)
    fixed_coef = MAT_FIXED_COEF.get(mat_key.lower(), MAT_FIXED_COEF.get(mat_key, 1.0))
    if max_dim > 500:
        machining_cost = (200.0 + 0.2 * max_dim) * fixed_coef
    elif max_dim > 200:
        machining_cost = (120.0 + 0.15 * max_dim) * fixed_coef
    else:
        machining_cost = (80.0 + 0.1 * max_dim) * fixed_coef

    # 粗糙度系数
    rough_coef = 1.0
    if roughness_ra > 0:
        rough_coef = ROUGH_COEF.get(roughness_ra, 1.0)
    machining_cost = machining_cost * rough_coef

    # 表面处理费（面积计价模型）
    surf_fixed = SURF_FIXED_FEE.get(surface, 0.0)
    surf_area_rate = SURF_AREA_RATE.get(surface, 0.0)
    surface_cost = surf_fixed + surf_area_rate * surface_area_dm2

    # 螺纹孔附加费（按材料分档）
    thread_fee_per_hole = THREAD_FEE_PER_HOLE_BY_MAT.get(
        mat_key.lower(), THREAD_FEE_PER_HOLE_BY_MAT.get(mat_key, THREAD_FEE_PER_HOLE)
    )
    thread_cost = max(0, thread_count) * thread_fee_per_hole

    unit_price = material_cost + machining_cost + surface_cost + thread_cost

    # 门槛：材料费占比不超过90%
    if unit_price > 0 and material_cost > 0.9 * unit_price:
        material_cost = 0.9 * unit_price
        surface_cost = surf_fixed + surf_area_rate * surface_area_dm2
        unit_price = material_cost + machining_cost + surface_cost + thread_cost

    # 大件单价上限
    unit_price = min(unit_price, 12000.0)

    # 批量折扣
    if qty >= 100:
        discount = 0.75
    elif qty >= 50:
        discount = 0.85
    elif qty >= 20:
        discount = 0.92
    else:
        discount = 1.0

    total_price = unit_price * qty * discount
    profit = total_price * 0.30
    final_price = total_price + profit

    return {
        "unit_price": round(unit_price, 2),
        "total_price": round(total_price, 2),
        "final_price": round(final_price, 2),
        "material_cost": round(material_cost, 2),
        "machining_cost": round(machining_cost, 2),
        "setup_cost": 0.0,  # 大件模型无设置费
        "qc_cost": 0.0,     # 大件模型无质控费
        "surface_cost": round(surface_cost, 2),
        "thread_cost": round(thread_cost, 2),
        "rough_coef": rough_coef,
        "thread_fee_per_hole": thread_fee_per_hole,
        "discount": discount,
    }


def check_conflict(material_key, surface):
    """检查材料+表面处理冲突（SURF_INVALID黑名单）"""
    _mat_key = material_key.lower()
    reason = SURF_INVALID.get((_mat_key, surface)) or SURF_INVALID.get((material_key, surface))
    if reason:
        return f"{material_key}+{surface} 工艺不支持：{reason}"
    return ""


def quote_one_part(row, step_path):
    """对单个零件执行报价"""
    part_number = row["part_number"]
    part_name = row.get("part_name", "")
    original_material = row.get("material", "")
    original_surface = row.get("surface_treatment", "")
    quantity = parse_quantity(row.get("quantity", "1"))
    tolerance = normalize_tolerance(row.get("tolerance", ""))
    roughness_ra = parse_roughness(row.get("roughness_ra", ""))
    thread_count = parse_thread_count(row.get("thread_count", "0"))

    # 材料标准化
    material_key, original_for_density = normalize_material(original_material)
    density = get_density(material_key, original_for_density)

    # 表面处理标准化
    surface = normalize_surface(original_surface)

    # 冲突检测
    conflict_msg = check_conflict(material_key, surface)

    # 初始化结果
    result = {
        "part_number": part_number,
        "part_name": part_name,
        "material": material_key,
        "surface_treatment": surface,
        "weight_kg": 0.0,
        "dim_x": 0.0, "dim_y": 0.0, "dim_z": 0.0,
        "surface_area_dm2": 0.0,
        "is_big_part": 0,
        "quantity": quantity,
        "tolerance": tolerance,
        "roughness_ra": roughness_ra,
        "thread_count": thread_count,
        "material_cost": 0.0,
        "machining_cost": 0.0,
        "setup_cost": 0.0,
        "qc_cost": 0.0,
        "surface_cost": 0.0,
        "thread_cost": 0.0,
        "unit_price": 0.0,
        "total_price": 0.0,
        "final_price": 0.0,
        "quote_model": "",
        "conflicts": conflict_msg,
        "step_parse_status": "",
        "parse_method": "",  # trimesh / cadquery / trimesh_bbox_only / failed
    }

    # 解析STEP几何
    if step_path is None:
        # 无STEP文件
        result["step_parse_status"] = "no_step_file"
        result["parse_method"] = "no_step_file"
        result["quote_model"] = "no_step_fallback"
        # 降级估价：按固定30元/件
        result["unit_price"] = 30.0
        result["total_price"] = round(30.0 * quantity, 2)
        result["final_price"] = round(result["total_price"] * 1.25, 2)
        result["material_cost"] = 0.0
        result["machining_cost"] = 30.0
        return result

    # 解析STEP
    geom = parse_step_geometry(step_path)
    volume_is_precise = bool(geom.get("volume_is_precise", False))
    parse_method = geom.get("parse_method", "failed")
    result["parse_method"] = parse_method

    if geom["status"] == "ok":
        # 解析成功（trimesh水密 / cadquery BRep / trimesh bbox）
        result["step_parse_status"] = "ok"
        dim_x = geom["dim_x"]
        dim_y = geom["dim_y"]
        dim_z = geom["dim_z"]
        volume_mm3 = geom["volume_mm3"]
        surface_area_mm2 = geom["surface_area_mm2"]
    else:
        # STEP解析失败：用文件大小降级估算
        result["step_parse_status"] = "fallback_filesize"
        fb = fallback_geometry_by_filesize(step_path)
        dim_x = fb["dim_x"]
        dim_y = fb["dim_y"]
        dim_z = fb["dim_z"]
        volume_mm3 = fb["volume_mm3"]
        surface_area_mm2 = fb["surface_area_mm2"]
        volume_is_precise = False

    result["dim_x"] = round(dim_x, 2)
    result["dim_y"] = round(dim_y, 2)
    result["dim_z"] = round(dim_z, 2)

    # 表面积 dm²
    surface_area_dm2 = surface_area_mm2 / 10000.0
    result["surface_area_dm2"] = round(surface_area_dm2, 4)

    # 计算重量
    # 体积 cm³ = mm³ / 1000
    volume_cm3 = volume_mm3 / 1000.0
    # 实心率矫正：机加工件实心率约0.5
    # cadquery BRep精确体积无需实心率矫正（已是真实几何体积）
    # trimesh网格/bbox估算体积需0.5矫正（bbox偏大、网格非水密）
    if volume_is_precise:
        solidity_factor = 1.0  # cadquery BRep精确体积
    else:
        solidity_factor = 0.5  # trimesh网格/bbox估算
    volume_cm3_corrected = volume_cm3 * solidity_factor
    # 重量 kg = cm³ × g/cm³ / 1000
    weight_kg = (volume_cm3_corrected * density) / 1000.0

    # STEP解析失败时用文件大小估算的重量覆盖
    if geom["status"] != "ok":
        weight_kg = fb["weight_kg_fallback"]

    if weight_kg < 0.001:
        # 极小重量降级
        file_size = os.path.getsize(step_path)
        if file_size > 500000:
            weight_kg = 1.5
        elif file_size > 100000:
            weight_kg = 0.3
        else:
            weight_kg = 0.1
        result["step_parse_status"] = "fallback_weight"

    result["weight_kg"] = round(weight_kg, 4)

    # 分级定价
    max_dim = max(dim_x, dim_y, dim_z)

    if weight_kg <= 2:
        # 小件：用calc_quote
        result["is_big_part"] = 0
        result["quote_model"] = "calc_quote_v10"
        quote = calc_quote(
            material=material_key, surface=surface, quantity=quantity,
            weight_kg=weight_kg, max_dim_mm=max_dim,
            surface_area_dm2=surface_area_dm2,
            tolerance=tolerance, roughness_ra=roughness_ra,
            thread_count=thread_count,
        )
        result["unit_price"] = quote["unit_price"]
        result["total_price"] = quote["total_price"]
        result["final_price"] = quote["final_price"]
        cb = quote["cost_breakdown"]
        result["material_cost"] = cb["material_cost"]
        result["machining_cost"] = cb["machining_cost"]
        result["setup_cost"] = cb["setup_cost"]
        result["qc_cost"] = cb["qc_cost"]
        result["surface_cost"] = cb["surface_cost"]
        result["thread_cost"] = cb["thread_cost"]
        # 冲突从小件quote中取（更准确）
        if not quote["valid"]:
            result["conflicts"] = "; ".join(c["message"] for c in quote["conflicts"])
    else:
        # 大件：用big_part_price
        result["is_big_part"] = 1
        result["quote_model"] = "big_part_price_v10"
        quote = big_part_price(
            mat_key=material_key, surface=surface, qty=quantity,
            weight_kg=weight_kg, dim_x=dim_x, dim_y=dim_y, dim_z=dim_z,
            surface_area_dm2=surface_area_dm2, roughness_ra=roughness_ra,
            thread_count=thread_count, tolerance=tolerance,
        )
        result["unit_price"] = quote["unit_price"]
        result["total_price"] = quote["total_price"]
        result["final_price"] = quote["final_price"]
        result["material_cost"] = quote["material_cost"]
        result["machining_cost"] = quote["machining_cost"]
        result["setup_cost"] = quote["setup_cost"]
        result["qc_cost"] = quote["qc_cost"]
        result["surface_cost"] = quote["surface_cost"]
        result["thread_cost"] = quote["thread_cost"]

    return result


def main():
    print("=" * 80)
    print("  批量报价执行 — test2 (112个常规机加件)")
    print("  引擎: calc_quote(小件≤2kg) + big_part_price(大件>2kg) v10")
    print("=" * 80)

    # 1. 读取PDF提取CSV
    print("\n[1] 读取PDF提取CSV...")
    with open(PDF_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        pdf_rows = list(reader)
    print(f"    PDF提取行数: {len(pdf_rows)}")

    # 2. 统计STEP文件
    step_files = [f for f in os.listdir(STEP_DIR) if f.upper().endswith(".STEP")]
    print(f"    STEP文件数: {len(step_files)}")

    # 3. 逐个报价
    print(f"\n[2] 逐个执行报价计算 ({len(pdf_rows)}件)...")
    results = []
    start_time = time.time()

    for i, row in enumerate(pdf_rows):
        part_number = row["part_number"]
        step_path = find_step_file(part_number, STEP_DIR)
        result = quote_one_part(row, step_path)
        results.append(result)

        # 进度报告（每20件）
        if (i + 1) % 20 == 0 or i == len(pdf_rows) - 1:
            elapsed = time.time() - start_time
            print(f"    进度: {i+1}/{len(pdf_rows)} ({(i+1)/len(pdf_rows)*100:.1f}%) 耗时: {elapsed:.1f}s")

    elapsed = time.time() - start_time
    print(f"\n    完成! 总耗时: {elapsed:.1f}s")

    # 4. 导出CSV
    print("\n[3] 导出报价结果CSV...")
    fieldnames = [
        "part_number", "part_name", "material", "surface_treatment",
        "weight_kg", "dim_x", "dim_y", "dim_z", "surface_area_dm2",
        "is_big_part", "quantity", "tolerance", "roughness_ra", "thread_count",
        "material_cost", "machining_cost", "setup_cost", "qc_cost",
        "surface_cost", "thread_cost",
        "unit_price", "total_price", "final_price",
        "quote_model", "conflicts", "step_parse_status", "parse_method",
    ]
    with open(RESULT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"    CSV: {RESULT_CSV}")

    # 5. 生成报告
    print("\n[4] 生成报价报告MD...")
    generate_report(results, elapsed)
    print(f"    MD:  {REPORT_MD}")

    # 6. 汇总打印
    print_summary(results, elapsed)

    print("\n" + "=" * 80)
    print("  批量报价完成!")
    print("=" * 80)

    return results


def print_summary(results, elapsed):
    """打印汇总"""
    total_parts = len(results)
    success_count = sum(1 for r in results if r["step_parse_status"] == "ok")
    fallback_count = sum(1 for r in results if r["step_parse_status"].startswith("fallback"))
    no_step_count = sum(1 for r in results if r["step_parse_status"] == "no_step_file")

    big_count = sum(1 for r in results if r["is_big_part"] == 1)
    small_count = sum(1 for r in results if r["is_big_part"] == 0)

    total_final = sum(r["final_price"] for r in results)
    prices = [r["final_price"] for r in results if r["final_price"] > 0]
    avg_price = sum(prices) / len(prices) if prices else 0
    sorted_prices = sorted(prices)
    median_price = sorted_prices[len(sorted_prices) // 2] if sorted_prices else 0
    min_price = min(prices) if prices else 0
    max_price = max(prices) if prices else 0

    print(f"\n    总零件数: {total_parts}")
    print(f"    STEP解析成功: {success_count} ({success_count/total_parts*100:.1f}%)")
    print(f"    STEP降级估算: {fallback_count}")
    print(f"    无STEP文件: {no_step_count}")
    # 解析方法统计
    from collections import Counter as _C
    _mc = _C(r.get("parse_method", "") for r in results)
    print(f"    解析方法: trimesh={_mc.get('trimesh', 0)}  trimesh_bbox={_mc.get('trimesh_bbox', 0)}  cadquery_fallback={_mc.get('cadquery', 0)}  bbox_only={_mc.get('trimesh_bbox_only', 0)}")
    print(f"    小件(≤2kg): {small_count}, 大件(>2kg): {big_count}")
    print(f"    总报价金额: ¥{total_final:,.2f}")
    print(f"    平均单价: ¥{avg_price:,.2f}")
    print(f"    中位单价: ¥{median_price:,.2f}")
    print(f"    最低价: ¥{min_price:,.2f}")
    print(f"    最高价: ¥{max_price:,.2f}")


def generate_report(results, elapsed):
    """生成Markdown报告"""
    total_parts = len(results)
    success_count = sum(1 for r in results if r["step_parse_status"] == "ok")
    fallback_count = sum(1 for r in results if r["step_parse_status"].startswith("fallback"))
    no_step_count = sum(1 for r in results if r["step_parse_status"] == "no_step_file")
    fail_count = fallback_count + no_step_count

    big_count = sum(1 for r in results if r["is_big_part"] == 1)
    small_count = sum(1 for r in results if r["is_big_part"] == 0)

    total_final = sum(r["final_price"] for r in results)
    total_qty = sum(r["quantity"] for r in results)
    prices = [r["final_price"] for r in results if r["final_price"] > 0]
    avg_price = sum(prices) / len(prices) if prices else 0
    sorted_prices = sorted(prices)
    median_price = sorted_prices[len(sorted_prices) // 2] if sorted_prices else 0
    min_price = min(prices) if prices else 0
    max_price = max(prices) if prices else 0

    # 材料分布
    from collections import Counter, defaultdict
    mat_counts = Counter(r["material"] for r in results)
    mat_totals = defaultdict(float)
    for r in results:
        mat_totals[r["material"]] += r["final_price"]

    # 表面处理分布
    surf_counts = Counter(r["surface_treatment"] for r in results)

    # 报价模型分布
    model_counts = Counter(r["quote_model"] for r in results)

    # STEP解析状态分布
    status_counts = Counter(r["step_parse_status"] for r in results)

    # STEP解析方法分布（trimesh/cadquery/trimesh_bbox_only/failed）
    method_counts = Counter(r.get("parse_method", "") for r in results)

    # 价格区间直方图
    price_bins = [
        (0, 100, "0-100"),
        (100, 500, "100-500"),
        (500, 1000, "500-1000"),
        (1000, 2000, "1000-2000"),
        (2000, 5000, "2000-5000"),
        (5000, 10000, "5000-10000"),
        (10000, 50000, "10000-50000"),
        (50000, float("inf"), "50000+"),
    ]
    bin_counts = [0] * len(price_bins)
    for p in prices:
        for i, (lo, hi, _) in enumerate(price_bins):
            if lo <= p < hi:
                bin_counts[i] += 1
                break

    # 成本构成分析
    total_material_cost = sum(r["material_cost"] for r in results)
    total_machining_cost = sum(r["machining_cost"] for r in results)
    total_setup_cost = sum(r["setup_cost"] for r in results)
    total_qc_cost = sum(r["qc_cost"] for r in results)
    total_surface_cost = sum(r["surface_cost"] for r in results)
    total_thread_cost = sum(r["thread_cost"] for r in results)
    total_cost_sum = (total_material_cost + total_machining_cost + total_setup_cost
                      + total_qc_cost + total_surface_cost + total_thread_cost)

    # 冲突清单
    conflicts_list = [r for r in results if r["conflicts"]]

    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("# 批量报价报告 — test2 (112个常规机加件)\n\n")
        f.write(f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**报价引擎**: calc_quote(小件≤2kg) + big_part_price(大件>2kg) v10\n\n")
        f.write(f"**数据源**: STEP文件({total_parts}个) + PDF提取CSV(材料/表面处理/公差/粗糙度/螺纹)\n\n")

        # ── 1. 汇总 ──
        f.write("## 1. 汇总\n\n")
        f.write("| 指标 | 值 |\n|------|----|\n")
        f.write(f"| 总零件数 | {total_parts} |\n")
        f.write(f"| 成功报价数 | {total_parts - fail_count} |\n")
        f.write(f"| 失败/降级数 | {fail_count} |\n")
        f.write(f"| STEP解析成功率 | {success_count}/{total_parts} = {success_count/total_parts*100:.1f}% |\n")
        f.write(f"| 总数量 | {total_qty}件 |\n")
        f.write(f"| 总报价金额 | ¥{total_final:,.2f} |\n")
        f.write(f"| 平均单价 | ¥{avg_price:,.2f} |\n")
        f.write(f"| 中位单价 | ¥{median_price:,.2f} |\n")
        f.write(f"| 最高价 | ¥{max_price:,.2f} |\n")
        f.write(f"| 最低价 | ¥{min_price:,.2f} |\n")
        f.write(f"| 耗时 | {elapsed:.1f}s |\n\n")

        # ── 2. STEP解析状态 ──
        f.write("## 2. STEP解析状态\n\n")
        f.write("| 状态 | 件数 | 占比 |\n|------|------|------|\n")
        for s, c in sorted(status_counts.items(), key=lambda x: -x[1]):
            f.write(f"| {s} | {c} | {c/total_parts*100:.1f}% |\n")
        f.write("\n")

        # ── 2.1 STEP解析方法分布（trimesh/cadquery fallback） ──
        f.write("### 2.1 STEP解析方法分布（cadquery fallback统计）\n\n")
        f.write("| 解析方法 | 件数 | 占比 | 说明 |\n|------|------|------|------|\n")
        method_desc = {
            "trimesh": "trimesh水密网格，体积可信",
            "cadquery": "cadquery BRep精确体积（trimesh失败/非水密时fallback）",
            "trimesh_bbox_only": "trimesh+cadquery都失败，仅bbox估算",
            "failed": "完全解析失败",
            "no_step_file": "无STEP文件",
            "": "未记录",
        }
        for m, c in sorted(method_counts.items(), key=lambda x: -x[1]):
            desc = method_desc.get(m, m)
            f.write(f"| {m or '(空)'} | {c} | {c/total_parts*100:.1f}% | {desc} |\n")
        f.write("\n")

        # ── 3. 小件/大件分布 ──
        f.write("## 3. 小件/大件分布\n\n")
        f.write("| 类型 | 件数 | 占比 | 说明 |\n|------|------|------|------|\n")
        f.write(f"| 小件(≤2kg) | {small_count} | {small_count/total_parts*100:.1f}% | 使用calc_quote报价 |\n")
        f.write(f"| 大件(>2kg) | {big_count} | {big_count/total_parts*100:.1f}% | 使用big_part_price报价 |\n\n")

        # ── 4. 报价模型分布 ──
        f.write("## 4. 报价模型分布\n\n")
        f.write("| 模型 | 件数 | 占比 |\n|------|------|------|\n")
        for m, c in sorted(model_counts.items(), key=lambda x: -x[1]):
            f.write(f"| {m} | {c} | {c/total_parts*100:.1f}% |\n")
        f.write("\n")

        # ── 5. 材料分布 ──
        f.write("## 5. 材料分布\n\n")
        f.write("| 材料 | 件数 | 占比 | 总报价 |\n|------|------|------|------|\n")
        for mat, c in sorted(mat_counts.items(), key=lambda x: -x[1]):
            f.write(f"| {mat} | {c} | {c/total_parts*100:.1f}% | ¥{mat_totals[mat]:,.2f} |\n")
        f.write("\n")

        # ── 6. 表面处理分布 ──
        f.write("## 6. 表面处理分布\n\n")
        f.write("| 表面处理 | 件数 | 占比 |\n|------|------|------|\n")
        for s, c in sorted(surf_counts.items(), key=lambda x: -x[1]):
            f.write(f"| {s} | {c} | {c/total_parts*100:.1f}% |\n")
        f.write("\n")

        # ── 7. 报价分布直方图 ──
        f.write("## 7. 报价分布直方图（按价格区间）\n\n")
        f.write("| 价格区间(元) | 件数 | 占比 | 直方图 |\n|------|------|------|------|\n")
        max_bin = max(bin_counts) if bin_counts else 1
        for (lo, hi, label), cnt in zip(price_bins, bin_counts):
            bar = "█" * int(cnt / max_bin * 30) if cnt > 0 else ""
            f.write(f"| {label} | {cnt} | {cnt/total_parts*100:.1f}% | {bar} |\n")
        f.write("\n")

        # ── 8. 成本构成分析 ──
        f.write("## 8. 成本构成分析\n\n")
        f.write("| 成本项 | 金额(元) | 占比 |\n|------|------|------|\n")
        if total_cost_sum > 0:
            f.write(f"| 材料费 | ¥{total_material_cost:,.2f} | {total_material_cost/total_cost_sum*100:.1f}% |\n")
            f.write(f"| 加工费 | ¥{total_machining_cost:,.2f} | {total_machining_cost/total_cost_sum*100:.1f}% |\n")
            f.write(f"| 设置费 | ¥{total_setup_cost:,.2f} | {total_setup_cost/total_cost_sum*100:.1f}% |\n")
            f.write(f"| 质控费 | ¥{total_qc_cost:,.2f} | {total_qc_cost/total_cost_sum*100:.1f}% |\n")
            f.write(f"| 表面处理费 | ¥{total_surface_cost:,.2f} | {total_surface_cost/total_cost_sum*100:.1f}% |\n")
            f.write(f"| 螺纹孔费 | ¥{total_thread_cost:,.2f} | {total_thread_cost/total_cost_sum*100:.1f}% |\n")
            f.write(f"| **合计** | **¥{total_cost_sum:,.2f}** | **100.0%** |\n")
        f.write("\n")

        # ── 9. 冲突清单 ──
        f.write(f"## 9. 冲突清单（SURF_INVALID黑名单拦截的不兼容组合）\n\n")
        if conflicts_list:
            f.write(f"共 **{len(conflicts_list)}** 件零件存在工艺冲突：\n\n")
            f.write("| 零件号 | 零件名 | 材料 | 表面处理 | 冲突原因 |\n|------|------|------|------|------|\n")
            for r in conflicts_list:
                f.write(f"| {r['part_number']} | {r['part_name']} | {r['material']} | {r['surface_treatment']} | {r['conflicts']} |\n")
        else:
            f.write("无工艺冲突。\n")
        f.write("\n")

        # ── 10. 详细报价清单 ──
        f.write("## 10. 详细报价清单（全部112件）\n\n")
        f.write("| 零件号 | 零件名 | 材料 | 表面 | 重量kg | 尺寸(X×Y×Z) | 数量 | 单价 | 总价 | 最终价 | 模型 | 状态 | 解析方法 |\n")
        f.write("|------|------|------|------|--------|------------|------|------|------|--------|------|------|------|\n")
        for r in results:
            dim_str = f"{r['dim_x']:.0f}×{r['dim_y']:.0f}×{r['dim_z']:.0f}"
            f.write(f"| {r['part_number']} | {r['part_name']} | {r['material']} | {r['surface_treatment']} "
                    f"| {r['weight_kg']} | {dim_str} | {r['quantity']} "
                    f"| ¥{r['unit_price']} | ¥{r['total_price']} | ¥{r['final_price']} "
                    f"| {r['quote_model']} | {r['step_parse_status']} | {r.get('parse_method', '')} |\n")


if __name__ == "__main__":
    main()