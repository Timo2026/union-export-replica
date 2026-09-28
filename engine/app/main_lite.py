"""Union·由你 — CNC AI 工艺大脑 v12.0.0-fusion Lite
零外部依赖版 (无需Ollama/无AI对话/无专家会议)
报价·画STEP·3D预览·上传·冲突·打包 完整可用
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统"""
import sys, os, json, re, uuid
from pathlib import Path
from datetime import datetime
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 版本号(单一来源：config/version.txt，与完整版统一) ──
with open(PROJECT_ROOT / "config" / "version.txt", encoding="utf-8") as _vf:
    _APP_VERSION = _vf.read().strip()

# ── 服务端点(环境变量兜底，禁止硬编码) ──
_OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import uvicorn

from src.runtime.step_generator_dual import generate_part, get_engine_status
from src.runtime.step_generator import PART_GENERATORS
from src.runtime.step_parser import extract_bbox_from_step, estimate_volume_from_bbox, get_material_density
from src.runtime.export_bundler import create_bundle
from src.core.material_utils import normalize_material

# ══════════════════════════════════════════════════════════
# 阶段0底线防护：对外接单模式（2026-09-07）
# ══════════════════════════════════════════════════════════
# 对外模式开关：EXTERNAL_MODE=1 启用门禁/水印/有效期
EXTERNAL_MODE = os.environ.get("EXTERNAL_MODE", "0") == "1"
# 金额门禁阈值：单件报价超过此值 → 强制人工审核（默认1万元）
AMOUNT_GATE_THRESHOLD = float(os.environ.get("AMOUNT_GATE_THRESHOLD", "10000"))
# 报价有效期（天），材料价格波动期间报价过期自动作废
QUOTE_VALIDITY_DAYS = int(os.environ.get("QUOTE_VALIDITY_DAYS", "14"))
# 材料价格更新日期（人工维护，月度更新有色金属行情）
PRICE_UPDATE_DATE = os.environ.get("PRICE_UPDATE_DATE", "2026-09-07")

# ══════════════════════════════════════════════════════════
# 阶段1双价格体系：直客价格系数（2026-09-07）
# ══════════════════════════════════════════════════════════
try:
    with open(PROJECT_ROOT / "config" / "pricing_direct.json", encoding="utf-8") as _pf:
        _PRICING_DIRECT = json.load(_pf)
    _DIRECT_RATIO_DEFAULT = _PRICING_DIRECT.get("default_ratio", 0.85)
    _DIRECT_RATIO = _PRICING_DIRECT.get("material_ratios", {})
    _DIRECT_PROFIT_RATE = _PRICING_DIRECT.get("profit_margin", {}).get("direct", 0.25)
except Exception:
    _DIRECT_RATIO_DEFAULT = 0.85
    _DIRECT_RATIO = {}
    _DIRECT_PROFIT_RATE = 0.25


# === 报价引擎 (纯数学, 零AI) ===
MAT_COEFS = {
    "45钢": 1.0, "45#": 1.0, "q235": 0.9,
    "6061": 1.3, "al6061": 1.3, "7075": 1.6,
    "304": 1.5, "sus304": 1.5, "316l": 1.8, "sus316": 1.8,
    "tc4": 5.4, "钛合金": 5.4, "h59": 2.0, "黄铜": 2.0,
}
# 按材料分档的材料单价（元/kg，基于杰沃509条数据二次校准）
MAT_PRICE_PER_KG = {
    "6061": 200, "al6061": 200,
    "45钢": 160, "45#": 160,
    "304": 575, "sus304": 575,
    "316l": 626, "sus316": 626,
    "q235": 298,
    "7075": 502,
    "黄铜": 1915, "h59": 1915,
    "tc4": 6267, "钛合金": 6267,
    # v12扩展：注塑件/硬质合金/不锈钢（ABS低单价,POM中单价,YG8硬质合金高单价,440C参考304）
    "abs": 50, "pom": 80, "yg8": 800, "440c": 575,
}
# 按材料分档的固定成本系数（加工难易度，1.0=标准）
MAT_FIXED_COEF = {
    "6061": 0.5, "al6061": 0.5,
    "45钢": 0.5, "45#": 0.5,
    "304": 1.0, "sus304": 1.0,
    "316l": 1.0, "sus316": 1.0,
    "q235": 0.7,
    "7075": 0.8,
    "黄铜": 1.2, "h59": 1.2,
    "tc4": 2.0, "钛合金": 2.0,
    # v12扩展：加工难易度（ABS易注塑,POM中,YG8极难,440C标准）
    "abs": 0.3, "pom": 0.4, "yg8": 1.5, "440c": 1.0,
}
# 原材料基准单价（元/kg，市场参考价，不含加工溢价，用于大件定价）
RAW_MATERIAL_PRICE = {
    "6061": 25, "al6061": 25,
    "45钢": 8, "45#": 8,
    "304": 45, "sus304": 45,
    "316l": 55, "sus316": 55,
    "q235": 6,
    "7075": 35,
    "黄铜": 35, "h59": 35,
    "tc4": 200, "钛合金": 200,
    # v12扩展：原材料基准单价
    "abs": 10, "pom": 15, "yg8": 400, "440c": 45,
}
# 大件专用材料单价（元/kg，介于RAW_MATERIAL_PRICE和MAT_PRICE_PER_KG之间，基于杰沃509条数据反推）
# v8修复：v7大件中位偏差-38.64%，根因是大件用RAW_MATERIAL_PRICE（低单价）导致材料费严重低估。
# 用509条真实数据反推理想大件材料单价（中位数），替代大件定价中的RAW_MATERIAL_PRICE。
BIG_PART_MAT_PRICE = {
    "6061": 170, "al6061": 170,
    "45钢": 48, "45#": 48,
    "304": 130, "sus304": 130,
    "316l": 55, "sus316": 55,
    "q235": 38,
    "7075": 78,
    "黄铜": 266, "h59": 266,
    "tc4": 200, "钛合金": 200,
    # v12扩展：大件专用材料单价
    "abs": 10, "pom": 15, "yg8": 400, "440c": 130,
}
SURF_COEFS = {
    "无": 1.0, "发黑": 1.2, "阳极氧化": 1.6, "镀锌": 1.3,
    "镀铬": 1.8, "镀镍": 1.6, "磷化": 1.2, "喷漆": 1.1,
    # v12扩展：喷砂物理处理低系数/钝化化学处理中低系数/氮化钛高级镀膜高系数/DLC类金刚石镀膜最高系数
    # 系数排序与 SURF_FIXED_FEE 固定费排序一致（喷砂5<钝化10<氮化钛30<dlc40），确保"选最高系数主表面"逻辑正确
    "喷砂": 1.02, "钝化": 1.04, "氮化钛": 1.12, "dlc": 1.15,
}
# 工艺不兼容黑名单（材料, 表面处理）→ 不兼容原因
# 默认 True（兼容），仅显式列出 False（不兼容）组合
# 材料键统一使用 lower() 形式，查询时两侧都做 lower() 比较
# Phase3 改造：白名单→黑名单，36 条（黄铜+发黑已移除，因数据中有1件黄铜+发黑订单）
SURF_INVALID = {
    # ── 铝合金：不做发黑/磷化/镀锌 ──
    ("6061", "发黑"):   "铝合金不做发黑处理（发黑是钢铁氧化层工艺）",
    ("al6061", "发黑"): "铝合金不做发黑处理",
    ("7075", "发黑"):   "铝合金不做发黑处理",
    ("6061", "磷化"):   "铝合金不做磷化处理（磷化为钢铁转化膜）",
    ("al6061", "磷化"): "铝合金不做磷化处理",
    ("7075", "磷化"):   "铝合金不做磷化处理",
    ("6061", "镀锌"):   "铝合金通常阳极氧化而非镀锌",
    ("al6061", "镀锌"): "铝合金通常阳极氧化而非镀锌",
    ("7075", "镀锌"):   "铝合金通常阳极氧化而非镀锌",
    # ── 不锈钢：不做镀锌/磷化/阳极氧化 ──
    ("304", "镀锌"):     "不锈钢本身耐腐蚀，不需镀锌",
    ("sus304", "镀锌"):  "不锈钢本身耐腐蚀，不需镀锌",
    ("316l", "镀锌"):    "不锈钢本身耐腐蚀，不需镀锌",
    ("sus316", "镀锌"):  "不锈钢本身耐腐蚀，不需镀锌",
    ("304", "磷化"):     "不锈钢磷化效果差，不常用",
    ("sus304", "磷化"):  "不锈钢磷化效果差，不常用",
    ("316l", "磷化"):    "不锈钢磷化效果差，不常用",
    ("sus316", "磷化"):  "不锈钢磷化效果差，不常用",
    ("304", "阳极氧化"):   "不锈钢不做阳极氧化（阳极氧化为铝/钛工艺）",
    ("sus304", "阳极氧化"): "不锈钢不做阳极氧化",
    ("316l", "阳极氧化"):  "不锈钢不做阳极氧化",
    ("sus316", "阳极氧化"): "不锈钢不做阳极氧化",
    # ── 钛合金：不做发黑/镀锌/磷化/镀铬 ──
    ("tc4", "发黑"):     "钛合金不做发黑处理",
    ("钛合金", "发黑"):  "钛合金不做发黑处理",
    ("tc4", "镀锌"):     "钛合金不做镀锌",
    ("钛合金", "镀锌"):  "钛合金不做镀锌",
    ("tc4", "磷化"):     "钛合金不做磷化",
    ("钛合金", "磷化"):  "钛合金不做磷化",
    ("tc4", "镀铬"):     "钛合金不做镀铬",
    ("钛合金", "镀铬"):  "钛合金不做镀铬",
    # ── 黄铜：不做阳极氧化/磷化（发黑已移除，因数据中有1件黄铜+发黑）──
    ("黄铜", "阳极氧化"): "黄铜不做阳极氧化",
    ("h59", "阳极氧化"):  "黄铜不做阳极氧化",
    ("黄铜", "磷化"):     "黄铜不做磷化处理",
    ("h59", "磷化"):      "黄铜不做磷化处理",
    # ── q235 碳钢：不做阳极氧化 ──
    ("q235", "阳极氧化"): "钢不做阳极氧化（阳极氧化为铝/钛工艺）",
    # ── 45 钢：不做阳极氧化/喷漆 ──
    ("45钢", "阳极氧化"): "45钢不做阳极氧化",
    ("45#", "阳极氧化"):  "45钢不做阳极氧化",
    ("45钢", "喷漆"):     "45钢通常发黑/镀锌/镀铬/磷化，不做喷漆",
    ("45#", "喷漆"):      "45钢通常发黑/镀锌/镀铬/磷化，不做喷漆",
}
# 表面处理固定费（元/件，基于杰沃509条数据v5校准：反推旧系数模型效果）
SURF_FIXED_FEE = {
    "无": 0.0, "发黑": 15.0, "阳极氧化": 50.0, "镀锌": 10.0,
    "镀铬": 5.0, "镀镍": 50.0, "磷化": 15.0, "喷漆": 8.0,
    # v12扩展：喷砂低固定费/氮化钛涂层高固定费/DLC涂层高固定费/钝化中固定费
    "喷砂": 5.0, "氮化钛": 30.0, "dlc": 40.0, "钝化": 10.0,
}
# 表面处理面积费率（元/dm²，v5校准：固定费覆盖基础工艺，面积费率覆盖面积相关成本）
SURF_AREA_RATE = {
    "无": 0.0, "发黑": 8.0, "阳极氧化": 20.0, "镀锌": 30.0,
    "镀铬": 25.0, "镀镍": 20.0, "磷化": 8.0, "喷漆": 4.0,
    # v12扩展：喷砂面积费率低/氮化钛面积费率高/DLC面积费率高/钝化无面积费
    "喷砂": 3.0, "氮化钛": 50.0, "dlc": 60.0, "钝化": 0.0,
}
# 公差系数（基于ISO 2768标准，中等=基准1.0）
# v17优化：精细公差影响增强（1.15→1.30），粗糙公差折扣减小（0.9→0.85），提升公差模块贡献率
TOL_COEF = {
    "中等": 1.0, "精细": 1.30, "粗糙": 0.85,
    "未知": 1.0, "ISO2768-其他": 1.0, "其他": 1.0,
}
# 粗糙度系数（基于Ra值，Ra3.2=标准基准1.0，Ra越小越精密价格越高）
# v17优化：精密粗糙度影响增强（Ra0.8:1.25→1.40, Ra0.4:1.40→1.60），新增Ra0.2超精密档
ROUGH_COEF = {
    3.2: 1.0, 1.6: 1.15, 0.8: 1.40, 0.4: 1.60, 1.0: 1.20,
    0.2: 1.80,
}
# 螺纹孔附加费（元/孔，覆盖丝锥加工+检测成本）
THREAD_FEE_PER_HOLE = 5.0
# 按材料分档螺纹孔附加费（元/孔，316l基础定价高，螺纹孔费降低）
THREAD_FEE_PER_HOLE_BY_MAT = {
    "316l": 2.0, "sus316": 2.0,
}

def calc_quote(material="6061", surface="无", quantity=10, weight_kg=0.5, max_dim_mm=100, surface_area_dm2=0.0, tolerance="未知", roughness_ra=0.0, thread_count=0, dim_x=0.0, dim_y=0.0, dim_z=0.0, price_mode="xometry"):
    material = normalize_material(material)
    mat_key = material.lower()
    material_recognized = mat_key in MAT_COEFS or material in MAT_COEFS or mat_key in MAT_PRICE_PER_KG
    if not material_recognized:
        material = "6061"
        mat_key = "6061"
    # ── 阶段0：材料识别检测（对外模式下未识别材料→待询客户）──
    mat_coef = MAT_COEFS.get(mat_key, MAT_COEFS.get(material, 1.3))
    surf_coef = SURF_COEFS.get(surface, 1.0)
    # 黑名单查询：默认 True（兼容），命中 SURF_INVALID 则 False（不兼容）
    _mat_key = material.lower()
    _invalid_reason = (
        SURF_INVALID.get((_mat_key, surface))
        or SURF_INVALID.get((material, surface))
    )
    valid = _invalid_reason is None
    conflicts = []
    if not valid:
        conflicts.append({
            "severity": "error",
            "rule": f"{material}+{surface}",
            "message": f"{material}+{surface} 工艺不支持：{_invalid_reason}",
        })
    # 阶段0：保存原始输入值（用于门禁检查，自动修正前）
    _orig_weight_kg = weight_kg
    _orig_max_dim_mm = max_dim_mm
    if quantity <= 0: quantity = 10
    if weight_kg <= 0: weight_kg = 0.5
    if max_dim_mm <= 0: max_dim_mm = 100
    # ── 成本明细（白盒公式，基于杰沃509条数据二次校准·按材料分档） ──
    mat_price = MAT_PRICE_PER_KG.get(mat_key, MAT_PRICE_PER_KG.get(material, 383.0))
    fixed_coef = MAT_FIXED_COEF.get(mat_key, MAT_FIXED_COEF.get(material, 1.0))
    # v12边界修正B：316l中大件材料单价分档（weight>0.5kg或dim>200mm时626→200元/kg）
    if mat_key in ('316l', 'sus316') and (weight_kg > 0.5 or max_dim_mm > 200):
        mat_price = 200  # 介于小件626和大件55之间
    # v12边界修正C：7075/q235加工费分档降低
    if mat_key in ('7075', '7050') and 100 < max_dim_mm <= 200:
        fixed_coef = 0.4  # M档：0.8→0.4
    elif mat_key in ('7075', '7050') and 200 < max_dim_mm <= 500:
        fixed_coef = 0.5  # L档：0.8→0.5
    elif mat_key in ('q235', 'a3') and max_dim_mm > 500:
        fixed_coef = 0.3  # XL档：0.7→0.3
    material_cost = weight_kg * mat_price                # 材料费(按材料分档单价)
    machining_cost = (80.0 + 0.15 * max_dim_mm) * fixed_coef  # 加工工时费×材料难度系数（v10：基础值50→80，尺寸系数0.1→0.15，提升加工费占比）
    setup_cost = (30.0 / quantity) * fixed_coef          # 设置费×材料难度系数
    qc_cost = 20.0 * fixed_coef                          # 质控费×材料难度系数
    # ── 表面处理费（面积计价模型，替代乘全价模型） ──
    surf_fixed = SURF_FIXED_FEE.get(surface, 0.0)
    surf_area_rate = SURF_AREA_RATE.get(surface, 0.0)
    surface_cost = surf_fixed + surf_area_rate * surface_area_dm2
    # v14回调：大件表面费封顶（不超过材料费+加工费的45%，v12的30%过严回调到45%）
    base_cost = material_cost + machining_cost
    if base_cost > 0 and surface_cost > 0.45 * base_cost:
        surface_cost = 0.45 * base_cost

    # ── 公差系数 ──
    tol_coef = TOL_COEF.get(tolerance, 1.0)

    # ── 粗糙度系数 ──
    rough_coef = 1.0
    if roughness_ra > 0:
        rough_coef = ROUGH_COEF.get(roughness_ra, 1.0)

    # ── 螺纹孔附加费（按材料分档：316l基础定价高，螺纹孔费降低） ──
    thread_fee_per_hole = THREAD_FEE_PER_HOLE_BY_MAT.get(mat_key, THREAD_FEE_PER_HOLE_BY_MAT.get(material, THREAD_FEE_PER_HOLE))
    thread_cost = max(0, thread_count) * thread_fee_per_hole

    # ── 最终单价 = 基础费 + 材料费 + 加工费×公差系数×粗糙度系数 + 设置费 + 质控费 + 表面处理费 + 螺纹孔费 ──
    base_price = 15.0 + material_cost + machining_cost * tol_coef * rough_coef + setup_cost + qc_cost
    unit_price = base_price + surface_cost + thread_cost  # 不再乘surf_coef
    # v16 P0：单件溢价按材料分档（6061保持1.5倍，其他材料降至1.2倍，避免过补偿）
    if quantity == 1:
        unit_price *= (1.5 if mat_key.lower() in ('6061', 'al6061') else 1.2)
    # v16 P1.2：薄板件溢价按材料分档（6061保持3.0倍，其他材料降至2.0倍，避免过补偿）
    if dim_x > 0 and dim_y > 0 and dim_z > 0:
        _min_dim = min(dim_x, dim_y, dim_z)
        _max_dim = max(dim_x, dim_y, dim_z)
        if _min_dim <= 3 and _max_dim / _min_dim < 30:
            unit_price *= (3.0 if mat_key.lower() in ('6061', 'al6061') else 2.0)
    volume_discount = 1.0
    # v15 P1.3：激进阶梯折扣（大数量件规模效应更强）
    if quantity >= 100: volume_discount = 0.55
    elif quantity >= 50: volume_discount = 0.65
    elif quantity >= 30: volume_discount = 0.75
    elif quantity >= 20: volume_discount = 0.85
    elif quantity >= 10: volume_discount = 0.95
    elif quantity >= 5: volume_discount = 0.98
    total = unit_price * quantity * volume_discount
    # ── 阶段1：双价格体系（直客模式按材料分档乘以直客系数）──
    direct_ratio = 1.0
    profit_rate = 0.30                               # Xometry模式利润率30%
    if price_mode == "direct":
        direct_ratio = _DIRECT_RATIO.get(mat_key, _DIRECT_RATIO.get(material, _DIRECT_RATIO_DEFAULT))
        profit_rate = _DIRECT_PROFIT_RATE            # 直客模式利润率25%
        total *= direct_ratio                        # 直客价 = Xometry价 × 直客系数
    profit = total * profit_rate                     # 利润率(含物流)
    final = total + profit

    # ══════════════════════════════════════════════════════════
    # 阶段0底线防护：对外模式门禁（2026-09-07）
    # ══════════════════════════════════════════════════════════
    quote_status = "auto"          # auto=自动出价 | manual_review=人工审核 | pending_material=待询客户
    review_reason = None
    if EXTERNAL_MODE:
        # 门禁1：材料未识别 → 待询客户（不猜材料，进人工队列）
        if not material_recognized:
            quote_status = "pending_material"
            review_reason = f"材料'{material}'未识别，需人工确认材料牌号后重新报价"
        # 门禁2：解析失败（重量或尺寸异常）→ 人工审核
        elif _orig_weight_kg <= 0 or _orig_max_dim_mm <= 0:
            quote_status = "manual_review"
            review_reason = "解析失败：重量或尺寸异常，需人工核实图纸"
        # 门禁3：单件金额超阈值 → 人工审核（防大件错价亏损）
        elif quantity > 0 and (final / quantity) > AMOUNT_GATE_THRESHOLD:
            quote_status = "manual_review"
            review_reason = f"单件报价{final/quantity:.0f}元超出门禁阈值{AMOUNT_GATE_THRESHOLD:.0f}元，需商务确认"

    return {
        "material": material, "surface": surface, "quantity": quantity,
        "weight_kg": round(weight_kg, 3), "unit_price": round(unit_price, 2),
        "total_price": round(total, 2), "profit": round(profit, 2),
        "final_price": round(final, 2),
        "volume_discount": volume_discount,
        "cost_breakdown": {
            "base_fee": 15.0, "material_cost": round(material_cost, 2),
            "machining_cost": round(machining_cost, 2),
            "setup_cost": round(setup_cost, 2), "qc_cost": qc_cost,
            "surface_cost": round(surface_cost, 2),
            "tol_coef": tol_coef,
            "rough_coef": rough_coef,
            "thread_cost": round(thread_cost, 2),
            "thread_fee_per_hole": thread_fee_per_hole,
            "surface_area_dm2": surface_area_dm2,
        },
        "valid": len(conflicts) == 0, "conflicts": conflicts, "warnings": [],
        "disclaimer": "以上为AI估算，实际加工前请人工确认。",
        # 阶段0底线防护字段
        "quote_status": quote_status,
        "review_reason": review_reason,
        "external_mode": EXTERNAL_MODE,
        "validity_days": QUOTE_VALIDITY_DAYS,
        "price_update_date": PRICE_UPDATE_DATE,
        "watermark": "AI估价，商务确认后生效" if EXTERNAL_MODE else None,
        "material_recognized": material_recognized,
        # 阶段1双价格体系字段
        "price_mode": price_mode,
        "direct_ratio": round(direct_ratio, 4) if price_mode == "direct" else None,
    }

# === 新手引导机器人 (规则引擎, 无需AI) ===
PART_KEYWORDS = {
    "法兰": "flange", "法兰盖": "flange", "闷盖": "flange",
    "轴套": "sleeve", "衬套": "sleeve",
    "轴": "shaft", "光轴": "shaft",
    "板": "plate", "平板": "plate",
    "箱体": "box", "盒子": "box", "方块": "block",
    "支架": "bracket", "支板": "bracket",
    # 自然语言别名
    "圆盘": "flange", "圆环": "flange", "垫片": "flange",
    "圆筒": "sleeve", "管套": "sleeve", "管子": "sleeve",
    "圆棒": "shaft", "圆柱": "shaft",
    "铁块": "block",
}

def extract_params(msg):
    p = {"material": "6061", "surface": "无", "quantity": 10, "weight_kg": 0.5}
    hit = {"material": False, "surface": False, "quantity": False, "weight_kg": False}
    msg_lower = msg.lower()
    for mat in ["45钢", "6061", "304", "316l", "q235", "tc4", "钛合金"]:
        if mat in msg or mat in msg_lower:
            p["material"] = mat; hit["material"] = True; break
    for s in ["阳极氧化", "发黑", "镀锌", "镀铬", "镀镍", "磷化", "喷漆"]:
        if s in msg:
            p["surface"] = s; hit["surface"] = True; break
    m = re.search(r'(\d+)\s*[件个套]', msg)
    if m: p["quantity"] = int(m.group(1)); hit["quantity"] = True
    m = re.search(r'(\d+\.?\d*)\s*kg', msg_lower)
    if m: p["weight_kg"] = float(m.group(1)); hit["weight_kg"] = True
    return p, any(hit.values())

def bot_reply(message):
    msg = message.strip()
    ml = msg.lower()
    if any(k in msg for k in ["你好", "hi", "hello", "在吗"]):
        return {"reply": "我是Union由你。试试：\n- 画一个法兰 外径100内径50厚20\n- 6061法兰 50件 阳极氧化 报价\n- 帮助", "type": "greeting"}
    if any(k in msg for k in ["帮助", "help", "怎么用", "功能"]):
        return {"reply": (
            "**画图**: 画一个法兰 外径100内径50厚20\n"
            "**报价**: 6061法兰 50件 阳极氧化 多少钱\n"
            "**上传**: 拖拽STEP/STL到上传区\n"
            "**导出**: 一键打包ZIP\n"
            "装Ollama才有: AI对话/专家会议/工艺建议"
        ), "type": "help"}
    has_draw_keyword = any(k in msg for k in ["画", "生成", "创建", "建模"])
    has_part_keyword = any(pt in msg for pt in PART_KEYWORDS)
    is_draw = has_draw_keyword and has_part_keyword
    llm_part_type = None
    if has_draw_keyword and not has_part_keyword and detect_ollama()["available"]:
        llm_r = _llm_parse(msg, '{"part_type": "(flange|sleeve|shaft|plate|box|bracket)", "params": {...}} 用户想画什么零件? 选一个最接近的类型')
        if llm_r and "part_type" in llm_r:
            llm_part_type = llm_r["part_type"]
            is_draw = True
    if is_draw:
        part_type = llm_part_type or "flange"
        if not llm_part_type:
            for cn, en in PART_KEYWORDS.items():
                if cn in msg: part_type = en; break
        params = {"od": 100, "id": 50, "thickness": 20}
        od_m = re.search(r'外径\s*(\d+)', msg) or re.search(r'od\s*(\d+)', ml)
        id_m = re.search(r'内径\s*(\d+)', msg) or re.search(r'id\s*(\d+)', ml)
        th_m = re.search(r'厚\s*(\d+)', msg) or re.search(r'厚度\s*(\d+)', msg)
        len_m = re.search(r'长\s*(\d+)', msg) or re.search(r'长度\s*(\d+)', msg)
        w_m = re.search(r'宽\s*(\d+)', msg) or re.search(r'w\s*(\d+)', ml)
        h_m = re.search(r'高\s*(\d+)', msg) or re.search(r'h\s*(\d+)', ml)
        has_numbers = od_m or id_m or th_m or len_m or w_m or h_m
        if not has_numbers and detect_ollama()["available"]:
            # LLM兜底: 用户可能说自然语言
            llm_schema = f'{{"part_type": "(flange|sleeve|shaft|plate|box|bracket)", "params": {{"od": "mm", "id": "mm"}}}} 可用类型: flange(法兰), sleeve(轴套), shaft(轴), plate(板), box(箱体), bracket(支架)'
            llm_r = _llm_parse(msg, llm_schema)
            if llm_r and "part_type" in llm_r:
                part_type = llm_r["part_type"]
                lp = llm_r.get("params", {})
                params = {"od": int(lp.get("od", 100)), "id": int(lp.get("id", 50)),
                          "thickness": int(lp.get("thickness", 20))}
                if lp.get("length"): params["length"] = int(lp["length"])
                if lp.get("w"): params["w"] = int(lp["w"])
                if lp.get("h"): params["h"] = int(lp["h"])
        if od_m: params["od"] = int(od_m.group(1))
        if id_m: params["id"] = int(id_m.group(1))
        if th_m: params["thickness"] = int(th_m.group(1))
        if len_m: params["length"] = int(len_m.group(1))
        if w_m: params["w"] = int(w_m.group(1))
        if h_m: params["h"] = int(h_m.group(1))
        gen = generate_part(part_type, params)
        if "error" in gen:
            return {"reply": gen["error"]}
        bbox = gen.get("bounding_box_mm", [100, 100, 20])
        lines = [
            "## " + part_type + " 已生成",
            f"尺寸: {bbox[0]}x{bbox[1]}x{bbox[2]} mm",
            f"体积: {gen.get('volume_cm3', '-')} cm3",
            f"预估重量(6061): {gen.get('estimated_weight_g', '-')} g",
            "3D预览: 右侧模型区已加载",
            "继续: 说出材料和数量即可报价",
        ]
        return {"reply": "\n".join(lines), "type": "step", "stl_url": gen.get("stl_url"), "step_file": gen.get("step_file")}
    is_quote = any(k in ml for k in ["报价", "价格", "多少钱", "成本", "价格是"])
    if is_quote:
        params, has_hit = extract_params(msg)
        if not has_hit and detect_ollama()["available"]:
            llm_r = _llm_parse(msg, '{"material": "(6061|304|45钢|tc4|316l|q235)", "quantity": 50, "surface": "(阳极氧化|发黑|镀锌|无)"} 只输出JSON,没有的字段不要.')
            if llm_r:
                if "material" in llm_r: params["material"] = llm_r["material"]
                if "quantity" in llm_r: params["quantity"] = int(llm_r["quantity"])
                if "surface" in llm_r: params["surface"] = llm_r["surface"]
        q = calc_quote(**params)
        lines = [
            "## 报价明细",
            f"材料: {q['material']} | 表面: {q['surface']} | 数量: {q['quantity']}件 | 重量: {q['weight_kg']}kg",
            "",
            f"| 项目 | 金额 |",
            f"|------|------|",
            f"| 单价 | {q['unit_price']:.2f} |",
            f"| 小计 | {q['total_price']:.2f} |",
            f"| 利润 | {q['profit']:.2f} |",
            f"| 总价 | {q['final_price']:.2f} |",
            "",
        ]
        # 阶段0底线防护：展示对外模式字段（水印/审核状态/有效期）
        if q.get("watermark"):
            lines.append(f"⚠️ {q['watermark']}")
        quote_status = q.get("quote_status", "auto")
        if quote_status == "manual_review":
            lines.append(f"🔒 状态: 需人工审核 — {q.get('review_reason', '解析失败或金额超限')}")
        elif quote_status == "pending_material":
            lines.append(f"🔒 状态: 待询客户 — {q.get('review_reason', '材料未识别')}")
        if q.get("validity_days"):
            lines.append(f"有效期: {q['validity_days']}天 | 价格更新: {q.get('price_update_date', 'N/A')}")
        lines.append("以上为AI估算，实际加工前请人工确认。")
        if not q["valid"]:
            for c in q["conflicts"]:
                lines.append("! " + c['message'])
        return {"reply": "\n".join(lines), "type": "quote"}
    return {"reply": (
        "我是离线模式，支持: 画图/报价/上传/打包\n\n"
        "试试:\n"
        "- 画法兰 - 画一个法兰 外径100内径50厚20\n"
        "- 报价 - 6061法兰 50件 阳极氧化 多少钱\n"
        "- 帮助 - 查看全部功能\n\n"
        "装Ollama + qwen2.5:3b 解锁AI专家会议"
    ), "type": "unknown"}

# === 冲突检测 (纯规则) ===
CONFLICT_RULES = [
    ("304", "阳极氧化", False, "304不锈钢自然钝化，不进行阳极氧化"),
    ("316l", "阳极氧化", False, "316L不锈钢不进行阳极氧化"),
    ("tc4", "镀锌", False, "钛合金不进行镀锌处理"),
    ("6061", "镀锌", False, "铝合金不适合镀锌"),
    ("q235", "阳极氧化", False, "碳钢不进行阳极氧化"),
    ("6061", "电镀", True, "铝合金可电镀但附着力需预镀"),
    ("304", "电镀", True, "304可电镀但无必要"),
    ("45钢", "阳极氧化", False, "碳钢不进行阳极氧化"),
]
def check_conflict(material, surface):
    conflicts = []
    for m, s, mild, desc in CONFLICT_RULES:
        if (material.lower() == m.lower()) and \
           (surface in s or s in surface):
            conflicts.append({"severity": "warn" if mild else "error", "rule": m+":"+s, "message": desc})
    return {"valid": len([c for c in conflicts if c["severity"]=="error"])==0, "conflicts": conflicts}

def _llm_parse(prompt: str, schema: str) -> dict:
    """调用本地Ollama解析自然语言→结构化JSON. 返回{}表示失败."""
    try:
        body = json.dumps({
            "model": "qwen2.5:1.5b",
            "prompt": f"从用户描述中提取JSON. 只输出JSON, 不要解释.\n{schema}\n用户: {prompt}",
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 256}
        }).encode()
        req = urllib.request.Request(f"{_OLLAMA_BASE}/api/generate",
                                     data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        text = data.get("response", "").strip()
        # 提取JSON块
        m = re.search(r'\{(?:[^{}]|\{[^{}]*\})*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
        return {}
    except Exception:
        return {}

def detect_ollama():
    try:
        req = urllib.request.Request(f"{_OLLAMA_BASE}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        return {"available": True, "models": [m["name"] for m in data.get("models", [])]}
    except Exception:
        return {"available": False, "models": []}

app = FastAPI(title="Union由你 Lite", version=_APP_VERSION)

with open(PROJECT_ROOT / "app" / "static" / "index_lite.html", encoding="utf-8") as f:
    HTML_PAGE = f.read()

@app.get("/", response_class=HTMLResponse)
async def index(): return HTMLResponse(content=HTML_PAGE)

@app.get("/api/status")
async def status():
    return JSONResponse(content={
        "mode": "lite", "version": _APP_VERSION,
        "parts": list(PART_GENERATORS.keys()),
        "materials": list(MAT_COEFS.keys()),
        "surfaces": list(SURF_COEFS.keys()),
        "ollama": detect_ollama(),
        "engine": get_engine_status(),
    })

@app.get("/api/version")
async def version(): return JSONResponse(content={"version": _APP_VERSION, "codename": "工业炼金术师(Lite)", "mode": "lite"})

@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    msg = body.get("message", "").strip()
    if not msg: return JSONResponse(content={"reply": "请输入需求。"})
    result = bot_reply(msg)
    if result.get("type") not in ("greeting", "help"):
        result["disclaimer"] = "以上为AI估算，实际加工前请人工确认。"
        result["shadow_mode"] = True
    return JSONResponse(content=result)

@app.post("/api/generate-step")
async def generate_step_api(request: Request):
    try: params = await request.json()
    except Exception: return JSONResponse(content={"error": "需要JSON参数"}, status_code=400)
    result = generate_part(params.get("part_type", "flange"), params)
    if "error" in result: return JSONResponse(content=result, status_code=400)
    return JSONResponse(content=result)

@app.get("/api/preview/{filename}")
async def preview_stl(filename: str):
    # 路径穿越防护：禁止目录跳转
    if ".." in filename or "/" in filename or "\\" in filename:
        return JSONResponse(content={"error": "非法文件名"}, status_code=400)
    stl_path = (PROJECT_ROOT / "data" / "step" / filename).resolve()
    expected_dir = (PROJECT_ROOT / "data" / "step").resolve()
    if not str(stl_path).startswith(str(expected_dir)):
        return JSONResponse(content={"error": "非法路径"}, status_code=400)
    if not stl_path.exists():
        return JSONResponse(content={"error": "文件不存在"}, status_code=404)
    return FileResponse(stl_path, media_type="application/octet-stream")

@app.post("/api/upload-step")
async def upload_step_quote(file: UploadFile = File(...), material: str = Form("6061"),
                            quantity: int = Form(10), surface: str = Form("无")):
    upload_dir = PROJECT_ROOT / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / file.filename
    content = await file.read()
    file_path.write_bytes(content)
    bbox = extract_bbox_from_step(str(file_path))
    # Bug修复: step_parser 返回的 bbox 总含 "error": None 键（无错误时），
    # 原 "error" in bbox 判断永远为True导致即使解析成功也返回400。
    # 改为检查 error 值是否为真（None/空字符串表示无错误），与 main.py 一致。
    if not bbox or bbox.get("error"):
        return JSONResponse(content={"error": "STEP解析失败", "detail": bbox}, status_code=400)
    volume_mm3 = estimate_volume_from_bbox(bbox)
    volume_cm3 = volume_mm3 / 1000
    density = get_material_density(material)
    weight_kg = (volume_cm3 * density) / 1000
    q = calc_quote(material=material, surface=surface, quantity=quantity, weight_kg=weight_kg)
    return JSONResponse(content={
        "file_name": file.filename,
        "bounding_box": {"x": round(bbox["dim_x"],1), "y": round(bbox["dim_y"],1), "z": round(bbox["dim_z"],1)},
        "volume_mm3": round(volume_mm3,0), "volume_cm3": round(volume_cm3,2),
        "estimated_weight_kg": round(weight_kg,3),
        "quote": q, "disclaimer": "AI估算，仅供参考",
    })

@app.post("/api/export")
async def export_bundle(request: Request):
    try: params = await request.json()
    except Exception: return JSONResponse(content={"error": "需要JSON参数"}, status_code=400)
    task_id = params.get("task_id", uuid.uuid4().hex[:8])
    files = params.get("files", [])
    files_exist = [f for f in files if os.path.exists(str(PROJECT_ROOT / "data" / f.get("path", ""))) or os.path.exists(f.get("path", ""))]
    result = create_bundle(task_id, files_exist, params.get("quote"), {"task_id": task_id, "created": datetime.now().isoformat()})
    return JSONResponse(content=result)

@app.get("/api/download/{filename}")
async def download_zip(filename: str):
    # 路径穿越防护：禁止目录跳转
    if ".." in filename or "/" in filename or "\\" in filename:
        return JSONResponse(content={"error": "非法文件名"}, status_code=400)
    zip_path = (PROJECT_ROOT / "data" / "exports" / filename).resolve()
    expected_dir = (PROJECT_ROOT / "data" / "exports").resolve()
    if not str(zip_path).startswith(str(expected_dir)):
        return JSONResponse(content={"error": "非法路径"}, status_code=400)
    if not zip_path.exists():
        return JSONResponse(content={"error": "文件不存在"}, status_code=404)
    return FileResponse(zip_path, media_type="application/zip", filename=filename)

@app.get("/api/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content="""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>仪表盘</title>
<style>body{font-family:Arial;background:#0f172a;color:#e2e8f0;padding:24px}
h1{color:#38bdf8;font-size:20px}.v{font-size:24px;color:#38bdf8;font-weight:bold}
.c{background:#1e293b;border-radius:12px;padding:16px;margin:8px 0;border:1px solid #334155}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.l{font-size:11px;color:#94a3b8}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}
th{color:#94a3b8;font-size:11px;text-align:left;padding:6px 0;border-bottom:1px solid #334155}
td{padding:6px 0;border-bottom:1px solid #1e293b}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;margin-right:8px;font-size:10px}
.green{background:#166534;color:#86efac}.red{background:#7f1d1d;color:#fca5a5}
</style></head><body>
<h1>CNC AI Brain Lite v""" + _APP_VERSION + """</h1>
<div class="g">
<div class="c"><div class="l">模式</div><div class="v">Lite</div></div>
<div class="c"><div class="l">报价</div><div class="v">纯规则</div></div>
<div class="c"><div class="l">STEP</div><div class="v">trimesh</div></div>
<div class="c"><div class="l">3D</div><div class="v">Three.js</div></div>
</div>
<h2 style="margin-top:20px">报价梯度</h2>
<table><tr><th>材料</th><th>50件</th><th>倍率</th></tr>
<script>
(function(){let d=[["45钢","5891","基准"],["6061","7656","1.3x"],["304","9063","1.5x"],["316L","10875","1.8x"],["TC4","31719","5.4x"]];
document.write(d.map(r=>"<tr><td>"+r[0]+"</td><td>"+r[1]+"</td><td>"+r[2]+"</td></tr>").join(""));})();
</script></table>
<h2>冲突规则</h2>
<div><span class="tag green">6061+阳极氧化</span></div>
<div><span class="tag green">45钢+发黑</span></div>
<div><span class="tag red" style="">304+阳极氧化</span></div>
<div><span class="tag tag-" style="">TC4+镀锌</span></div>
</body></html>""")

@app.get("/api/health")
async def health():
    return JSONResponse(content={
        "status": "healthy", "mode": "lite", "version": f"{_APP_VERSION}-lite",
        "ollama_available": detect_ollama()["available"],
    })

@app.get("/api/demo")
async def demo():
    scenes = []
    try:
        r = generate_part("flange", {"od": 100, "id": 50, "thickness": 20})
        scenes.append({"scene": "STEP生成", "status": "ok" if "error" not in r else "error", "preview": r.get("stl_url", "")})
    except Exception as e:
        scenes.append({"scene": "STEP生成", "status": "error", "error": str(e)})
    try:
        r = calc_quote("6061", "阳极氧化", 50)
        scenes.append({"scene": "报价", "status": "ok", "price": r.get("final_price", 0)})
    except Exception as e:
        scenes.append({"scene": "报价", "status": "error", "error": str(e)})
    try:
        r = check_conflict("304", "阳极氧化")
        scenes.append({"scene": "冲突检测", "status": "blocked" if not r["valid"] else "ok"})
    except Exception as e:
        scenes.append({"scene": "冲突检测", "status": "error", "error": str(e)})
    return JSONResponse(content={"title": f"v{_APP_VERSION} Lite 演示", "scenes": scenes})

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7862, help="服务端口")
    args = parser.parse_args()
    print(f" Union由你 Lite v{_APP_VERSION} - 离线工业炼金术师")
    print(f" 零AI依赖 | 画图/报价/预览/打包")
    print(f" http://localhost:{args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")
