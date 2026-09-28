# -*- coding: utf-8 -*-
import re, math
from .step_generator import DENSITY
from ..neuro_core.reasoning_chain import ReasoningChain, StepType
from ..core.material_utils import normalize_material

# material canonical -> (price_kg CNY, density g/cm3)
_MATERIALS = {
    "45钢": 6.0, "45#": 6.0, "q235": 5.2,
    "6061": 22.0, "al6061": 22.0, "7075": 28.0,
    "304": 26.0, "sus304": 26.0, "316l": 34.0, "sus316": 34.0,
    "tc4": 160.0, "钛合金": 160.0, "h59": 55.0, "黄铜": 55.0,
    # v12扩展：注塑件/硬质合金/不锈钢（相对单价，以6061=22.0为基准按MAT_PRICE_PER_KG比例换算）
    "abs": 5.5, "pom": 8.8, "yg8": 88.0, "440c": 63.25,
}

_SURF_COEFS = {"无": 1.0, "发黑": 1.2, "阳极氧化": 1.6, "镀锌": 1.3,
               "镀铬": 1.8, "镀镍": 1.6, "磷化": 1.2, "喷漆": 1.1,
               # v12扩展：与 app/main_lite.py SURF_COEFS 同步（喷砂/钝化/氮化钛/dlc）
               "喷砂": 1.02, "钝化": 1.04, "氮化钛": 1.12, "dlc": 1.15}

# 表面处理固定费（元/件，面积计价模型，与 app/main_lite.py SURF_FIXED_FEE 同步）
_SURF_FIXED_FEE = {
    "无": 0.0, "发黑": 15.0, "阳极氧化": 50.0, "镀锌": 10.0,
    "镀铬": 5.0, "镀镍": 50.0, "磷化": 15.0, "喷漆": 8.0,
    # v12扩展：与 app/main_lite.py SURF_FIXED_FEE 同步
    "喷砂": 5.0, "氮化钛": 30.0, "dlc": 40.0, "钝化": 10.0,
}
# 表面处理面积费率（元/dm²，与 app/main_lite.py SURF_AREA_RATE 同步）
_SURF_AREA_RATE = {
    "无": 0.0, "发黑": 8.0, "阳极氧化": 20.0, "镀锌": 30.0,
    "镀铬": 25.0, "镀镍": 20.0, "磷化": 8.0, "喷漆": 4.0,
    # v12扩展：与 app/main_lite.py SURF_AREA_RATE 同步
    "喷砂": 3.0, "氮化钛": 50.0, "dlc": 60.0, "钝化": 0.0,
}
# 公差系数（与 app/main_lite.py TOL_COEF 同步，中等=基准1.0）
_TOL_COEF = {
    "中等": 1.0, "精细": 1.15, "粗糙": 0.9,
    "未知": 1.0, "ISO2768-其他": 1.0, "其他": 1.0,
}
# 粗糙度系数（基于Ra值，与 app/main_lite.py ROUGH_COEF 同步，Ra3.2=标准基准1.0）
_ROUGH_COEF = {
    3.2: 1.0, 1.6: 1.10, 0.8: 1.25, 0.4: 1.40, 1.0: 1.15,
}
# 螺纹孔附加费（元/孔，与 app/main_lite.py THREAD_FEE_PER_HOLE 同步）
_THREAD_FEE_PER_HOLE = 5.0
# 按材料分档螺纹孔附加费（元/孔，与 app/main_lite.py THREAD_FEE_PER_HOLE_BY_MAT 同步）
_THREAD_FEE_PER_HOLE_BY_MAT = {
    "316l": 2.0, "sus316": 2.0,
}

_PROCESS_COEFS = {"三轴CNC": 1.0, "三轴": 1.0, "四轴": 1.3, "四轴CNC": 1.3,
                  "五轴": 1.8, "五轴CNC": 1.8, "车加工": 0.8, "车": 0.8,
                  "线切割": 1.2, "放电": 1.5, "磨": 1.3}



def _safe_float(v, default=0.0):
    """安全转浮点：非法类型/非有限值(inf/nan)/空值一律回退 default，绝不抛异常。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _safe_int(v, default=10):
    """安全转整数：非法类型/空值回落 default，绝不抛异常。"""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _normalize_surface_for_calc(surface):
    """复合表面串归一化：按 + 拆分，选 _SURF_COEFS 系数最高项传给 calc_quote。

    与 app.main.py _quote_via_calc_quote._normalize_surface 逻辑一致（DRY）：
    单 key 直接返回；复合串选最贵项；空值返回 "无"。
    选最贵项而非累加，是因为 calc_quote 的 surface 参数只接受单 key，
    其表面费由 SURF_FIXED_FEE + SURF_AREA_RATE * area 计算。
    """
    if not surface:
        return "无"
    s = str(surface).strip()
    if s == "无" or s == "":
        return "无"
    parts = [p.strip() for p in re.split(r"[+＋]", s) if p.strip()]
    if not parts:
        return "无"
    if len(parts) == 1:
        return parts[0]
    # 选 _SURF_COEFS 系数最高的（与 _normalize_surface 一致）
    main_surf = parts[0]
    max_coef = _SURF_COEFS.get(main_surf, 1.0)
    for p in parts[1:]:
        c = _SURF_COEFS.get(p, 1.0)
        if c > max_coef:
            max_coef = c
            main_surf = p
    return main_surf


def _extract_dims(params):
    """从 params['dimensions'] 提取 (dim_x, dim_y, dim_z, max_dim_mm)。

    dimensions 键名归一：契约用 length/width/height/thickness/diameter/od，
    calc_quote 需要 dim_x/dim_y/dim_z（毫米）。缺失时回退 0.0，max_dim_mm 回退 100.0。
    """
    dims = params.get("dimensions") or {}

    def _g(*keys):
        for k in keys:
            v = dims.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return 0.0

    dim_x = _g("L", "w", "W", "length", "od", "D")
    dim_y = _g("B", "h", "H", "height", "width")
    dim_z = _g("t", "T", "thickness")
    if dim_z <= 0:  # dimensions 用 h 表示高度而非厚度时兜底
        dim_z = _g("h", "H")
    _max_bb = max(dim_x, dim_y, dim_z)
    max_dim_mm = _max_bb if _max_bb > 0 else 100.0
    return dim_x, dim_y, dim_z, max_dim_mm


class QuoteAdapter:
    def __init__(self):
        self.materials = {k: {"price_kg": v, "density": DENSITY.get(k, 2.8)}
                          for k, v in _MATERIALS.items()}

    def resolve_material(self, material):
        m = normalize_material(material)
        return m if m in _MATERIALS else "6061"

    def calc_weight_from_dimensions(self, shape, dims, mat_code):
        dims = dims or {}
        density = DENSITY.get(mat_code, 2.8)
        shape = (shape or "flat").lower()
        def g(key, default=0.0):
            v = dims.get(key)
            try: return float(v)
            except Exception: return default
        if shape in ("flange", "ring"):
            od = g("od") or g("D") or 100.0
            id_ = g("id", 0.0)
            t = g("thickness") or g("t") or g("h") or 10.0
            vol_mm3 = math.pi / 4.0 * (od * od - id_ * id_) * t
        elif shape in ("round", "cylinder", "shaft"):
            d = g("d") or g("D") or g("od") or 30.0
            l = g("length") or g("l") or g("h") or 100.0
            vol_mm3 = math.pi / 4.0 * d * d * l
        else:  # flat / plate / box
            w = g("w") or g("W") or g("L") or 100.0
            h = g("h") or g("H") or 50.0
            t = g("t") or g("thickness") or 10.0
            vol_mm3 = w * h * t
        vol_cm3 = vol_mm3 / 1000.0
        return vol_cm3 * density / 1000.0  # kg

    def estimate_machining_hours(self, weight_kg, process, shape=None, tolerance=None):
        base = max(0.2, 0.4 * float(weight_kg or 0))
        pcoef = _PROCESS_COEFS.get(process, 1.0)
        tol = str(tolerance or "").upper()
        tcoef = 1.0
        if tol.startswith("IT4"): tcoef = 1.8
        elif tol.startswith("IT5"): tcoef = 1.6
        elif tol.startswith("IT6"): tcoef = 1.4
        return round(base * pcoef * tcoef, 2)

    def extract_params_from_message(self, message):
        p = {"material": None, "quantity": None, "surface_treatment": None,
             "dimensions": {}, "weight_kg": None, "shape": None, "tolerance": None}
        msg = message or ""
        ml = msg.lower()
        for mat in sorted(_MATERIALS.keys(), key=len, reverse=True):
            if mat.lower() in ml:
                p["material"] = mat; break
        for s in ["阳极氧化", "发黑", "镀锌", "镀铬", "镀镍", "磷化", "喷漆", "喷砂", "氮化钛", "dlc", "钝化"]:
            if s in msg:
                p["surface_treatment"] = s; break
        m = re.search(r"(\d+)\s*[件个套]", msg)
        if m: p["quantity"] = int(m.group(1))
        m = re.search(r"(\d+\.?\d*)\s*kg", ml)
        if m: p["weight_kg"] = float(m.group(1))
        m = re.search(r"IT\s*(\d+)", msg, re.I)
        if m: p["tolerance"] = "IT" + m.group(1)
        d = p["dimensions"]
        def _i(pat):
            m = re.search(pat, msg)
            return int(m.group(1)) if m else None
        v = _i(r"外径\s*(\d+)") or _i(r"od\s*(\d+)")
        if v is not None: d["od"] = v
        v = _i(r"内径\s*(\d+)") or _i(r"id\s*(\d+)")
        if v is not None: d["id"] = v
        v = _i(r"厚\s*(\d+)") or _i(r"厚度\s*(\d+)")
        if v is not None: d["thickness"] = v
        v = _i(r"直径\s*(\d+)")
        if v is not None: d["d"] = v
        v = _i(r"长\s*(\d+)") or _i(r"长度\s*(\d+)")
        if v is not None: d["length"] = v
        v = _i(r"宽\s*(\d+)")
        if v is not None: d["w"] = v
        v = _i(r"高\s*(\d+)")
        if v is not None: d["h"] = v
        return p

    def merge_quote_params(self, msg_params, form_params):
        msg = msg_params or {}
        form = form_params or {}
        result = {}
        sources = {}
        def pick(key, default=None):
            if key in msg and msg[key] not in (None, "", {}, []):
                result[key] = msg[key]; sources[key] = "消息"
            elif key in form and form[key] not in (None, "", {}, []):
                result[key] = form[key]; sources[key] = "表单"
            elif default is not None:
                result[key] = default; sources[key] = "默认"
        pick("material", "6061")
        pick("quantity", 10)
        pick("surface_treatment", "无")
        pick("dimensions")
        pick("weight_kg")
        pick("volume_cm3")
        pick("shape")
        pick("tolerance", "IT8")
        pick("process", "三轴CNC")
        pick("profit_rate", 0.30)
        pick("pricing_mode")
        pick("part_name")
        pick("surface_area_dm2")
        pick("roughness_ra")
        pick("thread_count")
        result["_sources"] = sources
        return result

    def quote(self, params):
        """报价计算 — 委托 calc_quote（三路收敛）。

        策略 A：内部委托 app.main_lite.calc_quote，复用其材料映射(MAT_PRICE_PER_KG)、
        表面系数(SURF_FIXED_FEE/SURF_AREA_RATE)、门禁三态(auto/manual_review/pending_material)。
        公开入参/返回结构保持不变，仅扩展返回字段（注入 quote_status/review_reason 等门禁字段）。
        这样 /api/quote、/api/cnc-quick 与 calc_quote/_quote_via_calc_quote 三路真正收敛。
        """
        params = params or {}
        # ── 参数提取（保持原 quote_adapter 入参兼容）──
        # 传原始 material 给 calc_quote，由其判断识别+门禁三态（DRY：材料识别单一来源在 calc_quote）
        # quote_adapter.resolve_material 仍供外部重量估算用，不影响报价收敛
        material_raw = str(params.get("material") or "6061")
        quantity = max(1, _safe_int(params.get("quantity"), 10))
        surface = params.get("surface_treatment") or params.get("surface") or "无"
        # 重量必须为正数：非法/非正/缺失一律回退默认 0.5kg，避免 float() 抛异常或负价格
        weight_kg = _safe_float(params.get("weight_kg"))
        if weight_kg <= 0:
            weight_kg = 0.5
        process = params.get("process", "三轴CNC")
        tolerance = params.get("tolerance") or "未知"
        roughness_ra = _safe_float(params.get("roughness_ra"), 0.0)
        if roughness_ra < 0:
            roughness_ra = 0.0
        thread_count = max(0, _safe_int(params.get("thread_count"), 0))
        surface_area_dm2 = _safe_float(params.get("surface_area_dm2"), 0.0)
        if surface_area_dm2 < 0:
            surface_area_dm2 = 0.0
        pricing_mode = params.get("pricing_mode", "by_quantity")
        profit_rate_param = _safe_float(params.get("profit_rate"), 0.30)

        # ── 尺寸推断 dim_x/y/z 和 max_dim_mm（从 dimensions 提取）──
        dim_x, dim_y, dim_z, max_dim_mm = _extract_dims(params)

        # ── 复合表面处理串归一化（选最贵项传给 calc_quote，与 _quote_via_calc_quote 一致）──
        surface_for_calc = _normalize_surface_for_calc(surface)

        # ── 委托 calc_quote（复用门禁逻辑+材料映射+表面系数）──
        # lazy import 避免循环依赖（app.main_lite 顶部 import src.runtime.* 不含 quote_adapter）
        from app.main_lite import calc_quote, MAT_PRICE_PER_KG, AMOUNT_GATE_THRESHOLD
        cq = calc_quote(
            material=material_raw,
            surface=surface_for_calc,
            quantity=quantity,
            weight_kg=weight_kg,
            max_dim_mm=max_dim_mm,
            surface_area_dm2=surface_area_dm2,
            tolerance=tolerance,
            roughness_ra=roughness_ra,
            thread_count=thread_count,
            dim_x=dim_x, dim_y=dim_y, dim_z=dim_z,
            price_mode="xometry",
        )

        # P0-9: 大件单价上限（与 _quote_via_calc_quote L1281-1292 一致，防异常高价，三路收敛）
        if cq["unit_price"] > 12000.0:
            cq["unit_price"] = 12000.0
            cq["total_price"] = round(12000.0 * quantity, 2)
            cq["final_price"] = round(cq["total_price"] * 1.30, 2)
            # 封顶后同步修正 review_reason 金额，避免与 final_price 矛盾
            if cq.get("quote_status") == "manual_review" and cq.get("review_reason") and "超出门禁阈值" in str(cq["review_reason"]):
                _cap_qty = quantity if quantity > 0 else 1
                cq["review_reason"] = (
                    f"单件报价{cq['final_price'] / _cap_qty:.0f}元超出门禁阈值"
                    f"{AMOUNT_GATE_THRESHOLD:.0f}元，需商务确认"
                )

        # ── 估算工时（保留 quote_adapter 原有方法，calc_quote 不返回 machine_hours）──

        machine_hours = self.estimate_machining_hours(weight_kg, process, params.get("shape"), tolerance)
        # ── 材料单价（从 calc_quote 的 MAT_PRICE_PER_KG 派生，保持与 calc_quote 一致）──
        _cq_mat = cq["material"]
        mat_price = MAT_PRICE_PER_KG.get(_cq_mat.lower(), MAT_PRICE_PER_KG.get(_cq_mat, 383.0))

        # ── 映射回 quote_adapter 返回结构（保留原字段 + 注入门禁字段，三路收敛）──
        cb = cq.get("cost_breakdown", {})
        return {
            # ── calc_quote 核心字段（三路收敛）──
            "material": cq["material"], "surface": cq["surface"],
            "surface_treatment": cq.get("surface", surface),
            "quantity": cq["quantity"], "weight_kg": cq["weight_kg"],
            "unit_price": cq["unit_price"], "total_price": cq["total_price"],
            "profit": cq["profit"], "final_price": cq["final_price"],
            "volume_discount": cq["volume_discount"],
            "valid": cq["valid"], "conflicts": cq["conflicts"], "warnings": cq["warnings"],
            "disclaimer": cq["disclaimer"],
            # ── 门禁字段（从 calc_quote 注入，三路收敛关键）──
            "quote_status": cq.get("quote_status", "auto"),
            "review_reason": cq.get("review_reason"),
            "external_mode": cq.get("external_mode", False),
            "validity_days": cq.get("validity_days"),
            "price_update_date": cq.get("price_update_date"),
            "watermark": cq.get("watermark"),
            "material_recognized": cq.get("material_recognized", True),
            "price_mode": cq.get("price_mode", "xometry"),
            "direct_ratio": cq.get("direct_ratio"),
            # ── quote_adapter 兼容字段（保留公开接口）──
            "profit_rate": profit_rate_param,  # 保留入参的 profit_rate（向后兼容）
            "material_price": mat_price,
            "process": process,
            "machine_hours": machine_hours,
            "part_name": params.get("part_name", "未命名零件"),
            "shape": params.get("shape", "flat"),
            "tolerance": params.get("tolerance", "IT8"),
            "roughness": params.get("roughness", "Ra1.6"),
            "roughness_ra": roughness_ra,
            "thread_count": thread_count,
            "pricing_mode": pricing_mode,
            "delivery_days": 5, "lead_time_days": 5,
            "confidence": 0.85,
            # ── 成本明细（顶层别名，与 quote_adapter 原结构兼容）──
            "material_cost": cb.get("material_cost", 0.0),
            "machining_cost": cb.get("machining_cost", 0.0),
            "surface_cost": cb.get("surface_cost", 0.0),
            "cost_breakdown": {
                **cb,
                "process_coef": _PROCESS_COEFS.get(process, 1.0),  # 保留工艺系数（仅展示用）
                "surf_coef_legacy": _SURF_COEFS.get(surface_for_calc, 1.0),
            },
        }

    def quote_with_reasoning(self, params):
        r = self.quote(params)
        chain = ReasoningChain("quote", "报价计算")
        chain.add_input("material", params.get("material"))
        chain.add_input("quantity", params.get("quantity"))
        chain.add_input("surface_treatment", params.get("surface_treatment"))
        chain.add_feature("weight_kg", r["weight_kg"], "估算重量")
        chain.add_step(StepType.CALCULATION, "成本计算（委托 calc_quote）",
                       "委托 app.main_lite.calc_quote：base=15+mat_cost+machining*tol*rough+setup+qc; unit=base+surface_cost+thread_cost; total=unit*qty*discount; 含门禁三态(auto/manual_review/pending_material)",
                       confidence=0.9, formula="calc_quote(material,surface,qty,weight,max_dim,...)→{unit_price,total_price,quote_status,...}")
        chain.add_conclusion("报价结论", confidence=0.85,
                             rationale="总价 ¥%.2f" % r["final_price"])
        chain.finalize()
        r["reasoning_chain"] = chain.to_dict()
        r["reasoning_chain_id"] = chain.chain_id
        return r
