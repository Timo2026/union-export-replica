"""test_commercial.py — P1 确定性商业层 (freight/customs/Incoterms → landed cost).

纯确定性, 不依赖任何在线服务。验证:
  计费重 = max(实重, 体积重); 运费/关税/VAT/保险按 config 费率;
  Incoterm 决定卖方承担项 → seller_quote_price; landed_cost = 买方真实到手成本;
  交期 = 生产 + 质检 + 精密额外 + 运输; 缺省与降级可解释。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.commercial import compute_commercial, resolve_region
from services.config import load_commercial

_ROOT = Path(__file__).resolve().parent.parent
CFG = load_commercial(_ROOT)


def _quote(final=10000.0, unit=200.0, lead=3):
    return {"final_price": final, "total_price": final, "unit_price": unit,
            "lead_time_days": lead, "profit": final * 0.23}


def _rfq(qty=50, weight=0.5, dims=(100, 50, 10), material="6061", tol="IT7"):
    return {"quantity": qty, "weight_kg": weight, "dimensions_mm": list(dims),
            "material": material, "tolerance_grade": tol}


def test_region_resolution():
    assert resolve_region("US", CFG) == "north_america"
    assert resolve_region("DE", CFG) == "europe"
    assert resolve_region("JP", CFG) == "asia"
    assert resolve_region("CN", CFG) == "domestic"
    assert resolve_region(None, CFG) == "other"
    assert resolve_country_unknown() == "other"


def resolve_country_unknown():
    return resolve_region("ZZ", CFG)


def test_chargeable_weight_is_max_of_actual_and_volumetric():
    # 致密金属件: 100*50*10mm=50cm3/件 ×50=2500cm3 /6000(air)=0.42kg 体积重 << 25kg 实重 → 实重占优
    r = compute_commercial(_quote(), _rfq(), CFG, destination_country="US", shipping_mode="air")
    w = r["weight"]
    assert w["total_actual_kg"] == 25.0
    assert w["volumetric_kg"] < w["total_actual_kg"]
    assert w["chargeable_kg"] == max(w["total_actual_kg"], w["volumetric_kg"])


def test_bulky_light_part_is_volumetric_dominated():
    # 抛货: 500*400*300mm=60000cm3/件 ×10=600000cm3 /6000=100kg 体积重 >> 1kg 实重 → 体积重占优
    r = compute_commercial(_quote(), _rfq(qty=10, weight=0.1, dims=(500, 400, 300)),
                           CFG, destination_country="US", shipping_mode="air")
    w = r["weight"]
    assert w["volumetric_kg"] > w["total_actual_kg"]
    assert w["chargeable_kg"] == w["volumetric_kg"]


def test_freight_uses_rate_and_min_charge():
    r = compute_commercial(_quote(), _rfq(qty=1, weight=0.1, dims=(10, 10, 10)),
                           CFG, destination_country="US", shipping_mode="express")
    # 极小件 → 触发最低收费
    assert r["breakdown"]["freight"] == CFG["shipping_modes"]["express"]["min_charge"]


def test_ddp_seller_bears_duty_and_all():
    r = compute_commercial(_quote(final=10000.0), _rfq(), CFG,
                           destination_country="US", shipping_mode="air", incoterm="DDP")
    b = r["breakdown"]
    expected_seller = b["product_value"] + b["origin_handling"] + b["freight"] + \
        b["insurance"] + b["dest_handling"] + b["duty"] + b["vat"]
    assert abs(r["seller_quote_price"] - round(expected_seller, 2)) < 0.02
    assert r["incoterm"] == "DDP"


def test_exw_seller_bears_nothing_extra():
    r = compute_commercial(_quote(final=10000.0), _rfq(), CFG,
                           destination_country="US", incoterm="EXW")
    assert r["seller_quote_price"] == 10000.0        # EXW: 仅货值
    assert r["seller_bears"] == []


def test_fob_vs_cif_seller_price_increases():
    fob = compute_commercial(_quote(), _rfq(), CFG, destination_country="DE", incoterm="FOB")
    cif = compute_commercial(_quote(), _rfq(), CFG, destination_country="DE", incoterm="CIF")
    assert cif["seller_quote_price"] > fob["seller_quote_price"]   # CIF 多承担运费+保险


def test_landed_cost_includes_duty_vat_for_eu():
    r = compute_commercial(_quote(final=10000.0), _rfq(), CFG,
                           destination_country="DE", shipping_mode="air", incoterm="DAP")
    b = r["breakdown"]
    # 欧盟有关税 + VAT(20%)
    assert b["duty"] > 0 and b["vat"] > 0
    expected_landed = b["product_value"] + b["freight"] + b["duty"] + b["vat"] + \
        b["insurance"] + b["dest_handling"]
    assert abs(r["landed_cost"] - round(expected_landed, 2)) < 0.02


def test_us_vat_zero():
    r = compute_commercial(_quote(final=10000.0), _rfq(), CFG, destination_country="US", incoterm="DDP")
    assert r["breakdown"]["vat"] == 0.0        # north_america VAT=0


def test_de_minimis_zeroes_duty():
    # 美国 de_minimis=800, 货值低于则关税/VAT=0
    r = compute_commercial(_quote(final=500.0), _rfq(qty=1), CFG,
                           destination_country="US", incoterm="DDP")
    assert r["rates"]["below_de_minimis"] is True
    assert r["breakdown"]["duty"] == 0.0


def test_lead_time_includes_transit_and_precision_extra():
    base = compute_commercial(_quote(lead=3), _rfq(tol="IT7"), CFG,
                              destination_country="US", shipping_mode="air")
    prec = compute_commercial(_quote(lead=3), _rfq(tol="IT5"), CFG,
                              destination_country="US", shipping_mode="air")
    lt = CFG["shipping_modes"]["air"]["transit_days_by_region"]["north_america"]
    qc = CFG["lead_time"]["qc_packing_days"]
    extra = CFG["lead_time"]["it4_it5_extra_days"]
    assert base["lead_time"]["total_days"] == 3 + qc + lt
    assert prec["lead_time"]["total_days"] == 3 + qc + extra + lt


def test_unknown_mode_and_country_fall_back_with_assumptions():
    r = compute_commercial(_quote(), _rfq(), CFG, destination_country=None, shipping_mode="teleport")
    assert r["shipping_mode"] == "air"          # 缺省 mode
    assert r["region"] == "other"
    assert r["assumptions"]                     # 显式标注假设, 不静默
