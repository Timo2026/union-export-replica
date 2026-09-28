"""tests/test_experts.py — T4: 3 专家 Agent 包装 (material/price/dfm) 9 用例.

每个专家 3 用例 + registry 1 用例.  用 importlib 直接加载 tool.py (skills/ 子包
在 Python 3.11 namespace 包场景下不可直接 import, 故绕过包机制).
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_skill_tool(skill_name: str) -> Any:
    """importlib 直接加载 skills/<name>/tool.py 并返回 run() 函数."""
    tool_path = ROOT / "skills" / skill_name / "tool.py"
    spec = importlib.util.spec_from_file_location(f"_test_{skill_name}_tool", tool_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run


# 3 个 expert 的 run 函数 (一次加载, 复用)
material_run = _load_skill_tool("material-expert")
price_run = _load_skill_tool("price-expert")
dfm_run = _load_skill_tool("dfm-expert")


def _ctx():
    class FakeCtx:
        def get_ctrl(self): return None
    return FakeCtx()


# ============ material-expert ============

def test_material_expert_offline_mock() -> None:
    """LLM 离线时返 keyword-based mock 结论, source='mock'."""
    calculation = {
        "material": "6061", "material_name": "6061铝合金",
        "surface": "anodizing", "total_single": 76.53,
        "weight_kg_single": 0.827, "volume_cm3": 306.31,
    }
    r = material_run(_ctx(), calculation=calculation)
    assert r["ok"] is True
    assert r["skill"] == "material-expert"
    assert r["iron_rule"] == "llm_proposal"
    assert r["source"] == "mock"
    assert r["analysis"]["anodizing_ok"] is True
    assert r["analysis"]["compatible"] is True


def test_material_expert_incompatible_304_anodizing() -> None:
    """304 + anodizing 应触发 incompatible (铁基不能阳极)."""
    calculation = {
        "material": "304", "material_name": "304不锈钢",
        "surface": "anodizing", "total_single": 100.0,
    }
    r = material_run(_ctx(), calculation=calculation)
    assert r["analysis"]["compatible"] is False
    assert r["analysis"]["anodizing_ok"] is False
    assert any("304" in risk or "不能阳极" in risk for risk in r["analysis"]["risks"])
    assert r["analysis"]["score"] <= 50


def test_material_expert_missing_calculation() -> None:
    r = material_run(_ctx(), calculation=None)
    assert r["ok"] is False
    assert "calculation required" in r["error"]


# ============ price-expert ============

def test_price_expert_offline_ratios() -> None:
    """LLM 离线时返 ratios 分项占比. 注: total_single 含 20% 毛利, 分项之和 < 100%."""
    calculation = {
        "material_cost_single": 23.78, "machining_cost_single": 40.0,
        "surface_cost_single": 0.0, "total_single": 76.53,
        "total_batch": 3826.62, "quantity": 50,
    }
    r = price_run(_ctx(), calculation=calculation)
    assert r["ok"] is True
    assert r["iron_rule"] == "llm_proposal"
    assert r["source"] == "mock"
    ratios = r["explanation"]["ratios"]
    # 分项占比之和应 < 100% (差额即毛利)
    total_pct = ratios["material_pct"] + ratios["machining_pct"] + ratios["surface_pct"]
    assert 50 < total_pct < 100, f"sum of ratios {total_pct} out of range"
    assert ratios["material_pct"] > 0
    assert ratios["machining_pct"] > 0
    assert "批量" in r["explanation"]["batch_economy"]


def test_price_expert_high_surface_pct_warning() -> None:
    """surface 占比 ≥ 30% 触发建议. mock 算法: surface / total."""
    calculation = {
        "material_cost_single": 20, "machining_cost_single": 30,
        "surface_cost_single": 30, "total_single": 96,  # 80 × 1.20 = 96
        "total_batch": 960, "quantity": 10,
    }
    r = price_run(_ctx(), calculation=calculation)
    surf_pct = r["explanation"]["ratios"]["surface_pct"]
    # 30 / 96 = 31.25% (按 total_single 计, 含毛利)
    assert abs(surf_pct - 31.2) < 0.1
    # ≥ 30 触发建议
    assert any("表面" in s for s in r["explanation"]["suggestions"])


def test_price_expert_missing_calculation() -> None:
    r = price_run(_ctx(), calculation=None)
    assert r["ok"] is False


# ============ dfm-expert ============

def test_dfm_expert_thin_wall_warning() -> None:
    """壁厚 < 1.5mm 触发 high severity."""
    dimensions = {"outer_d": 10.0, "inner_d": 8.0, "length": 50.0}
    r = dfm_run(_ctx(), dimensions=dimensions, shape="bushing")
    assert r["ok"] is True
    assert r["iron_rule"] == "llm_proposal"
    assert r["source"] == "mock"
    wall_risks = [r2 for r2 in r["risks"] if r2["type"] == "min_wall"]
    assert len(wall_risks) >= 1
    assert wall_risks[0]["severity"] == "high"
    assert r["score"] < 100


def test_dfm_expert_deep_hole_warning() -> None:
    """深孔长径比 > 5 触发 high severity."""
    dimensions = {"outer_d": 10.0, "inner_d": 2.0, "length": 20.0}
    r = dfm_run(_ctx(), dimensions=dimensions, shape="bushing")
    deep_risks = [r2 for r2 in r["risks"] if r2["type"] == "deep_hole"]
    assert len(deep_risks) >= 1
    assert deep_risks[0]["severity"] == "high"


def test_dfm_expert_missing_dimensions() -> None:
    r = dfm_run(_ctx(), dimensions=None)
    assert r["ok"] is False


# ============ registry 集成 ============

def test_three_experts_registered() -> None:
    """3 专家 skill 都被 skills._runtime 发现."""
    import skills._runtime as rt
    skills = rt.discover()
    for sid in ("material_expert", "price_expert", "dfm_expert"):
        assert sid in skills, f"{sid} not registered in skills/_runtime"
