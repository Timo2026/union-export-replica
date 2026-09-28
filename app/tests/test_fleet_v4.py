"""tests/test_fleet_v4.py — T3: FleetCoordinator v4 接入 (6 用例).

覆盖:
  1. CalculationEngine 3 种几何 (圆柱/空心/长方体) 精度
  2. calculate_quote 4 种材料 + 4 种表面处理
  3. 方案文档 §5 测试用例 (6061 轴套外径80内径50长度100, 50件) 数字对齐
  4. run_fleet_v4_quote fast_path < 100ms
  5. invalid 输入抛 ValueError (含 message 校验)
  6. Adapter mode=expert_path Ollama 离线 → fallback fast_path
"""
from __future__ import annotations

import math
import time

import pytest


# ---- 1. CalculationEngine 精度 ----
def test_calculation_engine_three_geometries() -> None:
    from services.fleet_v4 import CalculationEngine
    # 空心圆柱 (轴套): V = π × ((8/2)² - (5/2)²) × 10 cm³
    v_bushing = CalculationEngine.cylinder_volume_outer_inner_mm(80.0, 50.0, 100.0)
    expected_bushing = math.pi * ((8 / 2) ** 2 - (5 / 2) ** 2) * 10.0
    assert abs(v_bushing - expected_bushing) < 0.01
    assert abs(v_bushing - 306.31) < 0.05  # 方案文档 §5 对齐

    # 实心圆柱 (d=50mm → r=25mm=2.5cm, length=100mm=10cm) V = π × 2.5² × 10 = 196.35 cm³
    v_solid = CalculationEngine.solid_cylinder_volume_mm(50.0, 100.0)
    expected_solid = math.pi * (2.5 ** 2) * 10.0
    assert abs(v_solid - expected_solid) < 0.01
    assert abs(v_solid - 196.35) < 0.05

    # 长方体: V = (10) × (5) × (2) = 100 cm³
    v_block = CalculationEngine.rectangular_block_volume_mm(100.0, 50.0, 20.0)
    assert abs(v_block - 100.0) < 0.01

    # 重量: V × ρ / 1000 (6061 = 2.70 g/cm³)
    w = CalculationEngine.weight_kg(v_bushing, 2.70)
    expected_w = (306.31 * 2.70) / 1000.0
    assert abs(w - expected_w) < 0.001


# ---- 2. calculate_quote 多材料多表面 ----
def test_calculate_quote_materials_surfaces() -> None:
    from services.fleet_v4 import calculate_quote, MATERIAL_DB, SURFACE_PRICE
    base = {"outer_d": 80.0, "inner_d": 50.0, "length": 100.0}

    # 4 种材料 (每种单价不同)
    for mat in MATERIAL_DB:
        q = calculate_quote(material=mat, shape="bushing",
                            dimensions=dict(base, holes=4),
                            quantity=50, surface="none")
        assert q["material"] == mat
        assert q["total_batch"] > q["total_single"]
        assert q["material_cost_single"] > 0
        assert q["machining_cost_single"] > 0
        assert q["surface_cost_single"] == 0

    # 4 种表面处理 (阳极/PVD/喷涂/电镀 价格不同)
    for surf in SURFACE_PRICE:
        if surf == "none":
            continue
        q = calculate_quote(material="6061", shape="bushing",
                            dimensions=base, quantity=50, surface=surf)
        if SURFACE_PRICE[surf] > 0:
            assert q["surface_cost_single"] > 0
        # anodizing_ok=False 时仍能算 (但下游 verifier 应 HITL)
        assert q["surface"] == surf


# ---- 3. 方案文档 §5 测试用例 ----
def test_dgx_spark_doc_bushing_example() -> None:
    """DGX_Spark 工业经验AI封装方案文档 §5 测试用例:
    6061铝合金轴套, 外径80mm内径50mm长度100mm, CNC车削, 50件报价, 不需要表面处理.

    期望: 体积=306.31 cm³, 单件重量=0.827 kg, 单件工时=0.5 h,
          材料费=¥23.78, 加工费=¥40.00, 单件总价(含20%毛利)=¥76.53.
    """
    from services.fleet_v4 import calculate_quote
    q = calculate_quote(
        material="6061",
        shape="bushing",
        dimensions={"outer_d": 80.0, "inner_d": 50.0, "length": 100.0},
        quantity=50,
        surface="none",
    )
    assert q["volume_cm3"] == 306.31
    assert q["weight_kg_single"] == 0.827
    assert q["machining_hours_single"] == 0.5
    assert q["material_cost_single"] == 23.78
    assert q["machining_cost_single"] == 40.00
    assert q["surface_cost_single"] == 0.00
    assert q["total_single"] == 76.53
    assert q["total_batch"] == 3826.62  # 50 × 76.53 (含损耗已折入单价)


# ---- 4. fast_path 时延 ----
def test_run_fleet_v4_quote_fast_latency() -> None:
    from services.fleet_v4 import run_fleet_v4_quote
    t0 = time.time()
    for _ in range(20):  # 跑 20 次取平均
        r = run_fleet_v4_quote(
            material="6061", shape="bushing",
            dimensions={"outer_d": 80.0, "inner_d": 50.0, "length": 100.0},
            quantity=50, surface="none",
        )
    elapsed = (time.time() - t0) / 20 * 1000  # ms/次
    assert r["ok"] is True
    assert r["calculation"]["total_single"] == 76.53
    assert elapsed < 5.0, f"fast_path too slow: {elapsed:.2f} ms/call (预算 < 5ms)"


# ---- 5. invalid 输入 ----
def test_invalid_inputs_raise() -> None:
    from services.fleet_v4 import calculate_quote
    # 未知材料
    with pytest.raises(ValueError, match="unknown material"):
        calculate_quote(material="titanium", shape="bushing",
                        dimensions={"outer_d": 80.0, "inner_d": 50.0, "length": 100.0},
                        quantity=1, surface="none")
    # 未知形状
    with pytest.raises(ValueError, match="unknown shape"):
        calculate_quote(material="6061", shape="gear",
                        dimensions={"outer_d": 80.0, "inner_d": 50.0, "length": 100.0},
                        quantity=1, surface="none")
    # 缺字段 (flange 缺 thickness)
    with pytest.raises(ValueError, match="flange requires"):
        calculate_quote(material="6061", shape="flange",
                        dimensions={"outer_d": 80.0, "inner_d": 50.0},
                        quantity=1, surface="none")
    # 数量 <= 0
    with pytest.raises(ValueError, match="invalid quantity"):
        calculate_quote(material="6061", shape="bushing",
                        dimensions={"outer_d": 80.0, "inner_d": 50.0, "length": 100.0},
                        quantity=0, surface="none")
    # 几何非法 (outer <= inner)
    with pytest.raises(ValueError, match="invalid dimensions"):
        from services.fleet_v4 import CalculationEngine
        CalculationEngine.cylinder_volume_outer_inner_mm(50.0, 80.0, 100.0)


# ---- 6. Adapter mode=expert_path Ollama 离线 fallback ----
def test_adapter_expert_path_fallback_when_ollama_offline() -> None:
    from services.fleet_v4 import FleetCoordinatorV4Adapter
    # 用一个不存在的 Ollama endpoint
    adapter = FleetCoordinatorV4Adapter(mode="expert_path", ollama_model="nonexistent")
    # 加载失败 (因 _fleet_v4_original 可能不存在 — 但我们已 copy) 或 Ollama 不可达
    # 不管哪种情况: 实际 run_quote 应 fallback 到 fast_path
    r = adapter.run_quote(
        material="6061", shape="bushing",
        dimensions={"outer_d": 80.0, "inner_d": 50.0, "length": 100.0},
        quantity=50, surface="none",
    )
    # 因为 expert_path 调 Ollama 会失败 → 内部 try/except → fast_path
    # 或者 _fleet_v4_original 加载失败 → 模式降级 fast_path
    assert r["ok"] is True
    assert r["calculation"]["total_single"] == 76.53
    assert r["iron_rule"] == "deterministic"
