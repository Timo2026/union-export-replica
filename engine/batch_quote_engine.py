# -*- coding: utf-8 -*-
"""
批量报价引擎 — 400+常规机加工件
逐个执行：STEP解析→几何提取→材料识别→报价计算→BOM对照→验证矫正
"""
import os, sys, csv, json, re, time, math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.runtime.step_parser import extract_bbox_from_step, estimate_volume_from_bbox, get_material_density
from src.runtime.step_generator import DENSITY
from app.main_lite import calc_quote, MAT_COEFS, SURF_COEFS, MAT_PRICE_PER_KG, MAT_FIXED_COEF, RAW_MATERIAL_PRICE, BIG_PART_MAT_PRICE, SURF_FIXED_FEE, SURF_AREA_RATE, TOL_COEF, ROUGH_COEF, THREAD_FEE_PER_HOLE, THREAD_FEE_PER_HOLE_BY_MAT

# 阶段0底线防护：对外接单模式（与 main_lite.py 共享同一环境变量）
EXTERNAL_MODE = os.environ.get("EXTERNAL_MODE", "0") == "1"

BATCH_DIR = PROJECT_ROOT / "data" / "batch_quote" / "常规机加工件" / "常规机加件"
BOM_CSV = PROJECT_ROOT / "data" / "batch_quote" / "bom_data.csv"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ══════════════════════════════════════════════════════════
# 材料映射表：BOM规格列 → 报价引擎材料key
# ══════════════════════════════════════════════════════════
MATERIAL_MAP = {
    "6061铝合金": "6061", "6061": "6061", "al6061": "6061",
    "7075": "7075",
    "304不锈钢": "304", "304": "304", "sus304": "304",
    "316l不锈钢": "316l", "316l": "316l", "sus316": "316l",
    "17-4ph": "304",      # 17-4PH近似304密度
    "skd11": "45钢",      # 工具钢近似45钢
    "40cr13": "45钢", "440c": "440c",   # v12: 440C不锈钢独立定价
    "40cr": "45钢",
    "301不锈钢": "304", "301": "304",
    "45钢": "45钢", "45#": "45钢",
    "黄铜": "黄铜", "h59": "黄铜",
    "yg8钨合金": "yg8",    # v12扩展：YG8硬质合金独立定价
    "yg8": "yg8",
    "tc4": "tc4", "钛合金": "tc4",
    # 非金属：用6061作基准（密度调整）
    "abs": "abs", "abs pc": "abs", "pei": "6061",   # v12: ABS独立定价
    "pom": "pom", "pmma": "6061", "pur": "6061",    # v12: POM独立定价
    "tup": "6061", "peek": "6061",
    "医用硅胶": "6061", "硅橡胶": "6061",
    "氧化铝陶瓷": "6061",
    # v12.0改进：扩展材料映射（解决149个材料映射缺失）
    "s45c": "45钢", "S45C": "45钢", "c45": "45钢", "45c": "45钢",  # S45C碳钢→45钢 (26个)
    "a3": "q235", "A3": "q235", "q235b": "q235", "q235": "q235",  # A3钢→Q235 (12个)
    "5052": "6061", "铝合金5052": "6061", "5052铝合金": "6061",  # 5052铝合金→6061 (3个)
    "303不锈钢": "304", "303": "304", "sus303": "304",  # 303不锈钢→304 (37个)
    "cr12": "45钢", "CR12": "45钢", "cr12mov": "45钢", "cr12mo1v1": "45钢",  # CR12模具钢→45钢 (4个)
    "sus420": "304", "420不锈钢": "304", "sus 420": "304", "420": "304",  # SUS420→304 (3个)
    "invar36": "45钢", "invar36铁镍合金": "45钢", "invar 36": "45钢",  # Invar36→45钢 (3个)
    "cuzn": "黄铜", "CuZn": "黄铜", "铜": "黄铜", "h62": "黄铜", "c360": "黄铜",  # CuZn铜合金→黄铜 (3个)
    "delrin": "pom", "delrin 150": "pom",  # Delrin→POM (4个)
    "尼龙": "pom", "nylon": "pom", "polycaprolacta": "pom",  # 尼龙→POM (8个)
    "铝合金": "6061",                        # 无牌号铝合金→6061 (13个)
    "钢": "45钢",                            # 无牌号钢→45钢
    "不锈钢": "304",                         # 无牌号不锈钢→304
    "铝": "6061", "钛": "tc4",              # 单元素别名
    # P0-6: 英文材料名补充映射（与API适配层_normalize_material配合）
    "brass": "黄铜",                         # brass→黄铜
    "ceramic": "6061",                      # 陶瓷→6061（与氧化铝陶瓷一致）
    "silicone": "6061",                     # 硅胶→6061（与硅橡胶一致）
    "no_machining": "6061",                 # 无需加工→默认6061
}

# 表面处理映射
SURFACE_MAP = {
    "阳极氧化": "阳极氧化",
    "硬质阳极氧化": "阳极氧化",
    "喷漆": "喷漆",
    "发黑": "发黑",
    "镀锌": "镀锌",
    "镀铬": "镀铬",
    "镀镍": "镀镍",
    "磷化": "磷化",
    "钝化": "钝化",      # v12: 钝化独立定价
    "喷砂": "喷砂",       # v12: 喷砂独立定价
    "氮化钛涂层": "氮化钛", # v12: 氮化钛涂层独立定价
    "dlc涂层": "dlc",    # v12: DLC涂层独立定价
}

# 非金属密度覆盖（g/cm³）
NONMETAL_DENSITY = {
    "abs": 1.04, "abs pc": 1.15, "pei": 1.27,
    "pom": 1.41, "pmma": 1.18, "pur": 1.20,
    "tup": 2.25, "peek": 1.32,
    "医用硅胶": 1.20, "硅橡胶": 1.20,
    "氧化铝陶瓷": 3.90,
}

def parse_spec(spec):
    """解析BOM规格列，提取材料和表面处理"""
    spec = spec.strip()
    parts = [p.strip() for p in re.split(r"[+＋]", spec)]
    
    material_key = "6061"  # 默认
    material_matched = False  # 阶段0：材料匹配追踪
    material_raw = parts[0] if parts else ""
    surfaces = []
    is_nonmetal = False
    is_assembly = False
    has_step = True
    
    # 检测组装件/焊接件
    if "组装" in spec or "焊接" in spec or "无需加工" in spec:
        is_assembly = True
        has_step = False
        return material_key, "无", surfaces, is_nonmetal, is_assembly, has_step
    
    # 检测含图纸但无STEP
    if "含图纸" in spec and "铝" not in spec and "钢" not in spec and "不锈钢" not in spec:
        has_step = False
    
    # 匹配材料
    mat_lower = material_raw.lower()
    for bom_mat, engine_mat in MATERIAL_MAP.items():
        if bom_mat in material_raw or bom_mat in mat_lower:
            material_key = engine_mat
            material_matched = True
            break
    
    # 检测非金属
    for nm in NONMETAL_DENSITY:
        if nm in mat_lower or nm in material_raw:
            is_nonmetal = True
            break
    
    # 匹配表面处理（取最后一个匹配的作为主表面）
    for part in parts[1:]:
        for bom_surf, engine_surf in SURFACE_MAP.items():
            if bom_surf in part:
                surfaces.append(engine_surf)
                break
    
    # 主表面处理：优先选价格系数最高的
    main_surface = "无"
    max_coef = 1.0
    for s in surfaces:
        coef = SURF_COEFS.get(s, 1.0)
        if coef > max_coef:
            max_coef = coef
            main_surface = s
    
    
    # 阶段0底线防护：对外模式下未识别材料不猜6061，标记为UNKNOWN→进人工队列
    if EXTERNAL_MODE and not material_matched and material_raw:
        material_key = "UNKNOWN"  # 待询客户，calc_quote会触发pending_material门禁
    
    return material_key, main_surface, surfaces, is_nonmetal, is_assembly, has_step


def get_density(material_key, is_nonmetal, spec):
    """获取材料密度"""
    if is_nonmetal:
        spec_lower = spec.lower()
        for nm, dens in NONMETAL_DENSITY.items():
            if nm in spec_lower:
                return dens
    return get_material_density(material_key)


# ══════════════════════════════════════════════════════════
# v12.0改进：重量自动补算
# 对PDF未提供重量的零件，用STEP体积×材料密度自动计算weight_kg
# 公式: weight_kg = step_volume(mm³) × density(g/cm³) / 1000000
# ══════════════════════════════════════════════════════════
WEIGHT_DENSITY_TABLE = {
    "6061": 2.70, "6063": 2.69, "7075": 2.81, "5052": 2.68,
    "304": 7.93, "303": 7.93, "316l": 7.98, "316": 7.98,
    "45钢": 7.85, "q235": 7.85, "skd11": 7.85, "cr12": 7.85,
    "黄铜": 8.50, "tc4": 4.51,
    "abs": 1.04, "pom": 1.41, "pmma": 1.18,
    "yg8": 14.50, "440c": 7.85,
}


def weight_auto_fill(weight_kg, step_volume_mm3, material_key, is_nonmetal=False, spec=""):
    """
    v12.0改进：重量自动补算
    如果weight_kg为空或0，且有step_volume，则用STEP体积×材料密度自动计算。

    Args:
        weight_kg: 原始重量(kg)，可能为空/0/None
        step_volume_mm3: STEP体积(mm³)
        material_key: 材料key（如6061, 304, 45钢等）
        is_nonmetal: 是否非金属
        spec: 规格字符串（用于非金属密度识别）

    Returns:
        (weight_kg, is_filled): 补算后的重量, 是否为补算
    """
    # 判断原始重量是否有效
    try:
        w = float(weight_kg) if weight_kg not in (None, "", "nan") else 0.0
    except (ValueError, TypeError):
        w = 0.0

    if w > 0:
        return round(w, 4), False

    # 原始重量无效，尝试补算
    try:
        vol = float(step_volume_mm3) if step_volume_mm3 not in (None, "", "nan") else 0.0
    except (ValueError, TypeError):
        vol = 0.0

    if vol <= 0:
        return 0.0, False

    # 获取密度
    density = get_density(material_key, is_nonmetal, spec)

    # 计算重量: weight_kg = volume(mm³) × density(g/cm³) / 1000000
    calc_weight = vol * density / 1000000.0
    if calc_weight > 0:
        return round(calc_weight, 4), True
    return 0.0, False


def find_step_file(material_code, batch_dir):
    """根据物料编码查找STEP文件"""
    prefix = str(material_code)
    for f in os.listdir(batch_dir):
        if f.upper().endswith(".STEP") and f.startswith(prefix):
            return os.path.join(batch_dir, f)
    return None


def find_pdf_file(material_code, batch_dir):
    """根据物料编码查找PDF文件"""
    prefix = str(material_code)
    for f in os.listdir(batch_dir):
        if f.upper().endswith(".PDF") and f.startswith(prefix):
            return os.path.join(batch_dir, f)
    return None


def calculate_quote(item, step_path, batch_dir):
    """对单个BOM项计算报价"""
    seq = item["序号"]
    code = item["物料编码"]
    name = item["名称"]
    spec = item["规格"]
    qty = int(item["数量"])
    
    result = {
        "序号": seq, "物料编码": code, "名称": name, "规格": spec, "数量": qty,
        "step_file": "", "pdf_file": "", "dim_x": 0, "dim_y": 0, "dim_z": 0,
        "volume_mm3": 0, "volume_cm3": 0, "weight_kg": 0,
        "material_key": "", "surface": "", "is_nonmetal": False, "is_assembly": False,
        "unit_price": 0, "total_price": 0, "final_price": 0,
        "status": "", "error": "", "warning": "",
    }
    
    # 解析规格
    mat_key, surface, surfaces, is_nonmetal, is_assembly, has_step = parse_spec(spec)
    result["material_key"] = mat_key
    result["surface"] = surface
    result["is_nonmetal"] = is_nonmetal
    result["is_assembly"] = is_assembly
    
    # 提取粗糙度Ra和螺纹孔数（向后兼容：BOM无此列时用默认值，行为与v5一致）
    roughness_ra = 0.0
    try:
        raw_ra = item.get("粗糙度") or item.get("roughness_ra")
        if raw_ra not in (None, "", "nan"):
            roughness_ra = float(raw_ra)
    except (ValueError, TypeError):
        roughness_ra = 0.0
    thread_count = 0
    try:
        raw_tc = item.get("螺纹孔数") or item.get("thread_count")
        if raw_tc not in (None, "", "nan"):
            thread_count = int(float(raw_tc))
    except (ValueError, TypeError):
        thread_count = 0
    result["roughness_ra"] = roughness_ra
    result["thread_count"] = thread_count
    
    # 查找STEP和PDF
    if step_path:
        result["step_file"] = os.path.basename(step_path)
    pdf_path = find_pdf_file(code, batch_dir)
    if pdf_path:
        result["pdf_file"] = os.path.basename(pdf_path)
    
    # ★ 统一报价引擎：组装件/无STEP件也走calc_quote，消除双轨制（2026-09-08 P0-5）
    # calc_quote对weight=0默认0.5kg、max_dim=0默认100mm，能算出合理价格
    if is_assembly or not step_path:
        result["status"] = "组装件估价" if is_assembly else "无STEP估价"
        quote = calc_quote(
            material=mat_key, surface=surface, quantity=qty,
            weight_kg=0, max_dim_mm=0, surface_area_dm2=0.0,
            roughness_ra=roughness_ra, thread_count=thread_count,
            dim_x=0, dim_y=0, dim_z=0,
        )
        result["unit_price"] = quote["unit_price"]
        result["total_price"] = quote["total_price"]
        result["final_price"] = quote["final_price"]
        if is_assembly:
            result["warning"] = "组装件无STEP，统一引擎估价"
        else:
            result["warning"] = "无STEP文件，统一引擎估价" + ("（含图纸）" if "含图纸" in spec else "")
        return result
    
    # 有STEP文件：解析几何
    try:
        bbox = extract_bbox_from_step(step_path)
        if bbox.get("error"):
            result["status"] = "STEP解析失败"
            result["error"] = bbox["error"]
            # 降级估价
            result["unit_price"] = 30.0
            result["total_price"] = round(30.0 * qty, 2)
            result["final_price"] = round(result["total_price"] * 1.25, 2)
            return result
        
        # 单位矫正：trimesh解析STEP返回米，需×1000转毫米
        if bbox["dim_x"] < 2 and bbox["dim_y"] < 2 and bbox["dim_z"] < 2 and bbox["dim_x"] > 0:
            bbox["dim_x"] *= 1000
            bbox["dim_y"] *= 1000
            bbox["dim_z"] *= 1000
            bbox["volume_mm3"] *= 1e9  # m³ → mm³
            bbox["volume_source"] = "trimesh_step_mm"
        
        result["dim_x"] = round(bbox["dim_x"], 2)
        result["dim_y"] = round(bbox["dim_y"], 2)
        result["dim_z"] = round(bbox["dim_z"], 2)
        result["volume_mm3"] = round(bbox["volume_mm3"], 2)
        
        # 实心率矫正：仅对bbox估算体积修正，B-Rep精确体积不修正（已剔除空腔）
        volume_cm3 = bbox["volume_mm3"] / 1000.0
        _vol_source = bbox.get("volume_source", "bbox_estimate")
        if _vol_source in ("ocp_brep", "cadquery_brep", "trimesh_volume"):
            # B-Rep/trimesh精确体积已剔除空腔/孔洞，不再×0.5（避免双重修正）
            volume_cm3_corrected = volume_cm3
        else:
            # bbox估算体积含空腔，×0.5实心率修正
            solidity_factor = 0.5  # 机加工件平均实心率(校准:杰沃数据验证0.5更准确)
            volume_cm3_corrected = volume_cm3 * solidity_factor
        result["volume_cm3"] = round(volume_cm3_corrected, 2)
        
        density = get_density(mat_key, is_nonmetal, spec)
        weight_kg = (volume_cm3_corrected * density) / 1000.0
        result["weight_kg"] = round(weight_kg, 4)
        
        if weight_kg < 0.001:
            # STEP解析失败降级：按保守固定重量估算
            file_size = os.path.getsize(step_path)
            # 保守估算：按文件大小分级（非线性，避免大文件高估）
            if file_size > 500000:  # >500KB → 中等件
                weight_kg = 1.5
            elif file_size > 100000:  # >100KB → 小件
                weight_kg = 0.3
            else:
                weight_kg = 0.1
            result["weight_kg"] = round(weight_kg, 4)
            result["warning"] = f"STEP解析降级(文件{file_size//1024}KB→估算{weight_kg}kg)"
        
        # 分级定价模型：根据重量选择不同报价策略
        # 小件(<2kg)：使用标准报价引擎
        # 中件(2-10kg)：标准引擎+加工费加权
        # 大件(>10kg)：材料成本+加工工时模型
        if weight_kg <= 2:
            # 标准报价
            max_dim = max(result["dim_x"], result["dim_y"], result["dim_z"])
            # 计算表面积（dm²）用于面积计价模型
            surface_area_dm2 = 0.0
            if "surface_area_mm2" in result and result["surface_area_mm2"] > 0:
                surface_area_dm2 = result["surface_area_mm2"] / 10000.0  # mm² → dm²
            quote = calc_quote(material=mat_key, surface=surface, quantity=qty, weight_kg=weight_kg, max_dim_mm=max_dim, surface_area_dm2=surface_area_dm2, roughness_ra=roughness_ra, thread_count=thread_count, dim_x=result["dim_x"], dim_y=result["dim_y"], dim_z=result["dim_z"])
            result["unit_price"] = quote["unit_price"]
            result["total_price"] = quote["total_price"]
            result["final_price"] = quote["final_price"]
        else:
            # v15 P1.1：fallback_default件保守估价（几何解析失败 dim=0×0×0 时单价50元/件）
            if result["dim_x"] == 0 or result["dim_y"] == 0 or result["dim_z"] == 0:
                result["unit_price"] = 50.0
                result["total_price"] = round(50.0 * qty, 2)
                result["final_price"] = round(result["total_price"] * 1.30, 2)
                result["warning"] = (result.get("warning", "") + " | fallback保守估价(¥50/件)").strip(" |")
                result["status"] = "OK"
                return result
            # ★ 统一报价引擎：大件(>2kg)也走calc_quote，消除双轨制（2026-09-08 P0-4）
            max_dim = max(result["dim_x"], result["dim_y"], result["dim_z"])
            surface_area_dm2 = 0.0
            if "surface_area_mm2" in result and result["surface_area_mm2"] > 0:
                surface_area_dm2 = result["surface_area_mm2"] / 10000.0
            quote = calc_quote(material=mat_key, surface=surface, quantity=qty, weight_kg=weight_kg, max_dim_mm=max_dim, surface_area_dm2=surface_area_dm2, roughness_ra=roughness_ra, thread_count=thread_count, dim_x=result["dim_x"], dim_y=result["dim_y"], dim_z=result["dim_z"])
            result["unit_price"] = quote["unit_price"]
            result["total_price"] = quote["total_price"]
            result["final_price"] = quote["final_price"]
            # 保留大件单价上限（防异常高价）
            if result["unit_price"] > 12000.0:
                result["unit_price"] = 12000.0
                result["total_price"] = round(12000.0 * qty, 2)
                result["final_price"] = round(result["total_price"] * 1.30, 2)
            result["warning"] = (result.get("warning", "") + " | 大件统一引擎(calc_quote)").strip(" |")
        
        result["status"] = "OK"
        
        # 冲突检测仅对小件（quote变量存在时）
        if weight_kg <= 2 and 'quote' in dir():
            if not quote["valid"]:
                result["warning"] = "; ".join(c["message"] for c in quote["conflicts"])
        
    except Exception as e:
        result["status"] = "异常"
        result["error"] = str(e)[:200]
        result["unit_price"] = 30.0
        result["total_price"] = round(30.0 * qty, 2)
        result["final_price"] = round(result["total_price"] * 1.25, 2)
    
    return result


def main():
    print("=" * 80)
    print("  批量报价引擎 — 400+常规机加工件")
    print("  逐个执行 → STEP解析 → 几何提取 → 材料识别 → 报价计算 → BOM对照 → 验证矫正")
    print("=" * 80)
    
    # 读取BOM
    print("\n[1] 读取BOM数据...")
    bom_items = []
    with open(BOM_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bom_items.append(row)
    print(f"    BOM行数: {len(bom_items)}")
    
    # 统计STEP文件
    step_files = [f for f in os.listdir(BATCH_DIR) if f.upper().endswith(".STEP")]
    pdf_files = [f for f in os.listdir(BATCH_DIR) if f.upper().endswith(".PDF")]
    print(f"    STEP文件: {len(step_files)}个")
    print(f"    PDF文件:  {len(pdf_files)}个")
    
    # 逐个报价
    print(f"\n[2] 逐个执行报价计算 ({len(bom_items)}件)...")
    results = []
    step_count = 0
    no_step_count = 0
    assembly_count = 0
    error_count = 0
    
    start_time = time.time()
    
    for i, item in enumerate(bom_items):
        code = int(item["物料编码"])
        step_path = find_step_file(code, BATCH_DIR)
        
        if step_path:
            step_count += 1
        elif "组装" in item["规格"] or "焊接" in item["规格"] or "无需加工" in item["规格"]:
            assembly_count += 1
        else:
            no_step_count += 1
        
        result = calculate_quote(item, step_path, BATCH_DIR)
        results.append(result)
        
        if result["status"] == "异常":
            error_count += 1
        
        # 进度报告（每50件）
        if (i + 1) % 50 == 0 or i == len(bom_items) - 1:
            elapsed = time.time() - start_time
            print(f"    进度: {i+1}/{len(bom_items)} ({(i+1)/len(bom_items)*100:.1f}%) "
                  f"耗时: {elapsed:.1f}s STEP: {step_count} 无STEP: {no_step_count} 组装: {assembly_count}")
    
    elapsed = time.time() - start_time
    print(f"\n    完成! 总耗时: {elapsed:.1f}s")
    print(f"    有STEP: {step_count} | 无STEP: {no_step_count} | 组装件: {assembly_count} | 异常: {error_count}")
    
    # ══════════════════════════════════════════════════════════
    # 汇总统计
    # ══════════════════════════════════════════════════════════
    print("\n[3] 汇总统计...")
    
    total_final = sum(r["final_price"] for r in results)
    total_qty = sum(r["数量"] for r in results)
    avg_price = total_final / total_qty if total_qty > 0 else 0
    
    # 按状态分类
    status_counts = {}
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    
    # 按材料分类
    mat_stats = {}
    for r in results:
        mk = r["material_key"] or "未知"
        if mk not in mat_stats:
            mat_stats[mk] = {"count": 0, "total": 0, "qty": 0}
        mat_stats[mk]["count"] += 1
        mat_stats[mk]["total"] += r["final_price"]
        mat_stats[mk]["qty"] += r["数量"]
    
    # 价格分布
    prices = [r["final_price"] for r in results if r["final_price"] > 0]
    price_min = min(prices) if prices else 0
    price_max = max(prices) if prices else 0
    price_median = sorted(prices)[len(prices)//2] if prices else 0
    
    print(f"\n    总报价: ¥{total_final:,.2f}")
    print(f"    总数量: {total_qty}件")
    print(f"    平均价: ¥{avg_price:,.2f}/件")
    print(f"    价格范围: ¥{price_min:,.2f} ~ ¥{price_max:,.2f}")
    print(f"    中位价: ¥{price_median:,.2f}")
    
    print(f"\n    状态分布:")
    for s, c in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"      {s}: {c}件")
    
    print(f"\n    材料分布:")
    for mk, st in sorted(mat_stats.items(), key=lambda x: -x[1]["total"]):
        print(f"      {mk}: {st['count']}件, {st['qty']}个, ¥{st['total']:,.2f}")
    
    # ══════════════════════════════════════════════════════════
    # 自查矫正
    # ══════════════════════════════════════════════════════════
    print("\n[4] 自查矫正...")
    corrections = []
    
    for r in results:
        # 检查1: 单价为0
        if r["unit_price"] == 0 and not r["is_assembly"]:
            corrections.append({"序号": r["序号"], "问题": "单价为0", "矫正": "设为默认30元"})
            r["unit_price"] = 30.0
            r["total_price"] = round(30.0 * r["数量"], 2)
            r["final_price"] = round(r["total_price"] * 1.25, 2)
        
        # 检查2: 重量异常大（>10kg）
        if r["weight_kg"] > 10:
            corrections.append({"序号": r["序号"], "问题": f"重量异常{r['weight_kg']}kg", "矫正": "标记待审"})
            r["warning"] = (r.get("warning", "") + " | 重量异常").strip(" |")
        
        # 检查3: 重量异常小（<0.001kg）但有STEP
        if r["weight_kg"] < 0.001 and r["step_file"]:
            corrections.append({"序号": r["序号"], "问题": f"重量过小{r['weight_kg']}kg", "矫正": "可能STEP解析失败"})
            r["warning"] = (r.get("warning", "") + " | 重量过小").strip(" |")
        
        # 检查4: 单价异常高（>500元/件）
        if r["unit_price"] > 500:
            corrections.append({"序号": r["序号"], "问题": f"单价异常高¥{r['unit_price']}", "矫正": "标记待审"})
            r["warning"] = (r.get("warning", "") + " | 单价异常高").strip(" |")
    
    print(f"    矫正项: {len(corrections)}")
    for c in corrections[:20]:
        print(f"      序号{c['序号']}: {c['问题']} → {c['矫正']}")
    if len(corrections) > 20:
        print(f"      ... 还有 {len(corrections)-20} 项")
    
    # 重新计算总价
    total_final_corrected = sum(r["final_price"] for r in results)
    if total_final != total_final_corrected:
        print(f"\n    矫正后总报价: ¥{total_final_corrected:,.2f} (调整: ¥{total_final_corrected-total_final:,.2f})")
    
    # ══════════════════════════════════════════════════════════
    # 导出结果
    # ══════════════════════════════════════════════════════════
    print("\n[5] 导出结果...")
    
    # CSV详细报告
    csv_path = OUTPUT_DIR / "batch_quote_result.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "序号", "物料编码", "名称", "规格", "数量",
            "step_file", "pdf_file", "dim_x", "dim_y", "dim_z",
            "volume_mm3", "volume_cm3", "weight_kg",
            "material_key", "surface", "is_nonmetal", "is_assembly",
            "unit_price", "total_price", "final_price",
            "status", "error", "warning"
        ])
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"    CSV: {csv_path}")
    
    # JSON完整报告
    json_path = OUTPUT_DIR / "batch_quote_result.json"
    report = {
        "summary": {
            "total_items": len(results),
            "total_quantity": total_qty,
            "total_final_price": round(total_final_corrected, 2),
            "avg_price_per_unit": round(avg_price, 2),
            "price_min": round(price_min, 2),
            "price_max": round(price_max, 2),
            "price_median": round(price_median, 2),
            "step_count": step_count,
            "no_step_count": no_step_count,
            "assembly_count": assembly_count,
            "error_count": error_count,
            "correction_count": len(corrections),
            "elapsed_seconds": round(elapsed, 2),
        },
        "status_distribution": status_counts,
        "material_distribution": {k: {**v, "total": round(v["total"], 2)} for k, v in mat_stats.items()},
        "corrections": corrections,
        "items": results,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"    JSON: {json_path}")
    
    # Markdown汇总报告
    md_path = OUTPUT_DIR / "batch_quote_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 批量报价报告 — 400+常规机加工件\n\n")
        f.write(f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## 汇总\n\n")
        f.write(f"| 指标 | 值 |\n|------|----|\n")
        f.write(f"| 总件数 | {len(results)} |\n")
        f.write(f"| 总数量 | {total_qty}件 |\n")
        f.write(f"| 总报价 | ¥{total_final_corrected:,.2f} |\n")
        f.write(f"| 平均价 | ¥{avg_price:,.2f}/件 |\n")
        f.write(f"| 价格范围 | ¥{price_min:,.2f} ~ ¥{price_max:,.2f} |\n")
        f.write(f"| 有STEP | {step_count}件 |\n")
        f.write(f"| 无STEP | {no_step_count}件 |\n")
        f.write(f"| 组装件 | {assembly_count}件 |\n")
        f.write(f"| 异常 | {error_count}件 |\n")
        f.write(f"| 矫正 | {len(corrections)}项 |\n\n")
        
        f.write("## 材料分布\n\n")
        f.write("| 材料 | 件数 | 数量 | 总价 |\n|------|------|------|------|\n")
        for mk, st in sorted(mat_stats.items(), key=lambda x: -x[1]["total"]):
            f.write(f"| {mk} | {st['count']} | {st['qty']} | ¥{st['total']:,.2f} |\n")
        
        f.write("\n## 前50件详细报价\n\n")
        f.write("| 序号 | 编码 | 名称 | 材料 | 表面 | 数量 | 体积cm³ | 重量kg | 单价 | 总价 | 最终价 | 状态 |\n")
        f.write("|------|------|------|------|------|------|---------|--------|------|------|--------|------|\n")
        for r in results[:50]:
            f.write(f"| {r['序号']} | {r['物料编码']} | {r['名称']} | {r['material_key']} | {r['surface']} "
                    f"| {r['数量']} | {r['volume_cm3']} | {r['weight_kg']} "
                    f"| ¥{r['unit_price']} | ¥{r['total_price']} | ¥{r['final_price']} | {r['status']} |\n")
        
        if corrections:
            f.write(f"\n## 矫正记录 ({len(corrections)}项)\n\n")
            f.write("| 序号 | 问题 | 矫正 |\n|------|------|------|\n")
            for c in corrections:
                f.write(f"| {c['序号']} | {c['问题']} | {c['矫正']} |\n")
    print(f"    MD:  {md_path}")
    
    # ══════════════════════════════════════════════════════════
    # 最终验证
    # ══════════════════════════════════════════════════════════
    print("\n[6] 最终验证...")
    
    # 验证1: 所有BOM项都有报价结果
    assert len(results) == len(bom_items), f"结果数{len(results)} ≠ BOM数{len(bom_items)}"
    print(f"    ✓ 结果数 = BOM数 = {len(results)}")
    
    # 验证2: 所有有STEP的项都解析了几何
    step_with_geom = sum(1 for r in results if r["step_file"] and r["volume_mm3"] > 0)
    step_no_geom = sum(1 for r in results if r["step_file"] and r["volume_mm3"] == 0)
    print(f"    ✓ STEP解析成功: {step_with_geom}/{step_count}, 失败: {step_no_geom}")
    
    # 验证3: 所有项都有价格
    no_price = sum(1 for r in results if r["final_price"] == 0)
    print(f"    ✓ 零价格项: {no_price}")
    
    # 验证4: PDF对照
    pdf_match = sum(1 for r in results if r["pdf_file"])
    print(f"    ✓ PDF图纸匹配: {pdf_match}/{len(results)}")
    
    # 验证5: 总价合理性
    print(f"    ✓ 总报价: ¥{total_final_corrected:,.2f}")
    print(f"    ✓ 平均价: ¥{avg_price:,.2f}/件")
    
    print("\n" + "=" * 80)
    print(f"  批量报价完成!")
    print(f"  {len(results)}件 | ¥{total_final_corrected:,.2f} | 耗时{elapsed:.1f}s")
    print(f"  报告: {md_path}")
    print("=" * 80)
    
    return report

if __name__ == "__main__":
    main()
