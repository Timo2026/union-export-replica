"""commercial.py — P1 确定性商业层: Freight / Customs / Incoterms → Landed Cost.

全部为确定性计算, 费率来自 config/commercial.yaml (商业真相), LLM 不参与数字。
产出: 计费重、运费、关税、VAT、保险、操作费、landed cost(买方真实到手成本)、
      seller_quote_price(按 Incoterm 卖方应收)、总交期(生产+质检+运输)。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

_DEFAULT_MODE = "air"
_DEFAULT_REGION = "other"


def resolve_region(country: Optional[str], cfg: Dict[str, Any]) -> str:
    if not country:
        return _DEFAULT_REGION
    c = country.strip().upper()
    rmap = cfg.get("region_map", {})
    for region, codes in rmap.items():
        for code in (codes or []):
            if str(code).upper() == c or str(code).upper() == country.strip().upper():
                return region
    return _DEFAULT_REGION


def _num(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def compute_commercial(quote: Dict[str, Any], rfq: Dict[str, Any], cfg: Dict[str, Any],
                       destination_country: Optional[str] = None,
                       shipping_mode: Optional[str] = None,
                       incoterm: Optional[str] = None,
                       hs_code: Optional[str] = None) -> Dict[str, Any]:
    """由确定性报价 + RFQ + 商业配置计算 landed cost 与卖方报价。"""
    modes = cfg.get("shipping_modes", {})
    mode = shipping_mode if shipping_mode in modes else _DEFAULT_MODE
    m = modes.get(mode, modes.get(_DEFAULT_MODE, {}))
    region = resolve_region(destination_country, cfg)
    incoterm = (incoterm or cfg.get("incoterms", {}).get("default", "FOB")).upper()
    inc = cfg.get("incoterms", {}).get(incoterm, cfg.get("incoterms", {}).get("FOB", {}))

    qty = max(1, int(_num(rfq.get("quantity"), 1)))
    unit_weight = _num(rfq.get("weight_kg"), 0.5)
    total_actual_weight = round(unit_weight * qty, 4)

    # 体积重 (计费重 = max(实重, 体积重))
    dims = rfq.get("dimensions_mm") or []
    vol_divisor = _num(m.get("vol_divisor"), 5000) or 5000
    total_vol_cm3 = 0.0
    if len(dims) >= 3 and all(_num(d) > 0 for d in dims[:3]):
        unit_vol_cm3 = (_num(dims[0]) * _num(dims[1]) * _num(dims[2])) / 1000.0
        total_vol_cm3 = round(unit_vol_cm3 * qty, 3)
    vol_weight = round(total_vol_cm3 / vol_divisor, 4) if total_vol_cm3 else 0.0
    chargeable_weight = round(max(total_actual_weight, vol_weight), 4)

    # 运费
    rate = _num((m.get("rate_by_region", {}) or {}).get(region, m.get("rate_by_region", {}).get("other", 40)))
    min_charge = _num(m.get("min_charge"), 0)
    freight = round(max(min_charge, rate * chargeable_weight), 2)

    # 货值 (引擎 final_price 为整批含利润总价)
    product_value = round(_num(quote.get("final_price") or quote.get("total_price"), 0.0), 2)

    # 关税 / VAT (含小额免税)
    material = rfq.get("material") or "_default"
    tariff_tbl = cfg.get("tariff_by_material_region", {})
    tariff_rate = _num((tariff_tbl.get(material) or tariff_tbl.get("_default", {})).get(region, 0.0))
    vat_rate = _num(cfg.get("vat_by_region", {}).get(region, 0.0))
    de_minimis = _num(cfg.get("de_minimis_by_region", {}).get(region, 0.0))
    below_de_minimis = product_value < de_minimis if de_minimis else False
    duty = 0.0 if below_de_minimis else round(product_value * tariff_rate, 2)
    vat = 0.0 if below_de_minimis else round((product_value + duty) * vat_rate, 2)

    # 保险 / 操作费
    insurance = round((product_value + freight) * _num(cfg.get("insurance_pct_of_cif"), 0.003), 2)
    origin_handling = round(_num(cfg.get("handling", {}).get("origin_handling"), 0.0), 2)
    dest_handling = round(_num(cfg.get("handling", {}).get("dest_handling"), 0.0), 2)
    inland_freight = 0.0  # FOB 内陆运输占位 (可后续按起运地扩展)

    # Landed cost = 买方真实到手成本 (无论谁付, 经济上都计入)
    landed_cost = round(product_value + freight + duty + vat + insurance + dest_handling, 2)

    # 卖方报价 (按 Incoterm 卖方承担项加到货值上)
    cost_map = {
        "origin_handling": origin_handling, "inland_freight": inland_freight,
        "freight": freight, "insurance": insurance, "dest_handling": dest_handling,
        "duty": duty, "vat": vat,
    }
    seller_bears = inc.get("seller_bears", [])
    seller_added = round(sum(cost_map.get(k, 0.0) for k in seller_bears), 2)
    seller_quote_price = round(product_value + seller_added, 2)

    # 交期 = 生产 + 质检包装 + 精密额外 + 运输
    prod_lead = int(_num(quote.get("lead_time_days"), cfg.get("lead_time", {}).get("production_base_days", 3)))
    qc = int(_num(cfg.get("lead_time", {}).get("qc_packing_days"), 2))
    tol = (rfq.get("tolerance_grade") or "").upper()
    extra = int(_num(cfg.get("lead_time", {}).get("it4_it5_extra_days"), 5)) if tol in ("IT4", "IT5") else 0
    transit = int(_num((m.get("transit_days_by_region", {}) or {}).get(region, 7)))
    total_lead_time = prod_lead + qc + extra + transit

    return {
        "incoterm": incoterm, "incoterm_note": inc.get("note", ""),
        "shipping_mode": mode, "destination_country": destination_country,
        "region": region, "hs_code": hs_code,
        "currency": cfg.get("currency", "CNY"),
        "quantity": qty,
        "weight": {"unit_kg": unit_weight, "total_actual_kg": total_actual_weight,
                   "total_volume_cm3": total_vol_cm3, "volumetric_kg": vol_weight,
                   "chargeable_kg": chargeable_weight},
        "breakdown": {
            "product_value": product_value, "freight": freight, "duty": duty, "vat": vat,
            "insurance": insurance, "origin_handling": origin_handling,
            "dest_handling": dest_handling, "inland_freight": inland_freight,
        },
        "rates": {"freight_rate_per_kg": rate, "tariff_rate": tariff_rate,
                  "vat_rate": vat_rate, "below_de_minimis": below_de_minimis,
                  "de_minimis": de_minimis},
        "seller_bears": seller_bears,
        "seller_quote_price": seller_quote_price,
        "landed_cost": landed_cost,
        "landed_cost_per_unit": round(landed_cost / qty, 2) if qty else landed_cost,
        "lead_time": {"production_days": prod_lead, "qc_packing_days": qc,
                      "precision_extra_days": extra, "transit_days": transit,
                      "total_days": total_lead_time},
        "assumptions": ([] if destination_country else ["destination 缺省 → region=other"]) +
                       ([] if shipping_mode in modes else [f"shipping_mode 缺省/未知 → {_DEFAULT_MODE}"]),
        "_source": "deterministic:commercial.yaml",
    }


def compute_outsource_markup(po_unit_price: float, markup_pct: float) -> float:
    """v2.3.0 外协 markup：仅作用于外协路径（PO 成本 → 我方对客户卖价）。

    关键契约：**不与引擎 final_price（已含 ~30% 利润）双算**。
    两条定价路径：
      - 自产报价（final_price）：引擎已含利润
      - 外协报价（SELL）：PO 成本 × (1 + markup_pct/100)
    """
    return round(float(po_unit_price) * (1.0 + float(markup_pct) / 100.0), 2)
