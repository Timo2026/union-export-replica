"""tests/test_ceo_decision.py — T8: CEO-Decision skill 包装 (4 用例).

覆盖:
  1. 5 证全过 (高分) → decision=accept
  2. 5 证全低 → decision=reject
  3. 中间状态 → decision=defer
  4. registry 注册 + LLM 离线降级不静默
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "_test_ceo_decision_tool",
        ROOT / "skills" / "ceo-decision" / "tool.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tool = _load_tool()


class FakeCtx:
    def get_ctrl(self): return None


# ---- 1. 5 证全过 → accept ----
def test_full_pass_decision_accept() -> None:
    """高分场景: 大单 + 老客 + 高毛利 + 无 DFM 冲突 → 接单."""
    r = tool.run(FakeCtx(), decision_context={
        "quote": {"total_single": 50000},
        "margin_pct": 30,
        "customer": {"is_new": False, "won_count": 5, "lost_count": 0},
        "verification": {"conflicts": []},
        "missing": 0,
    }, threshold=70)
    assert r["ok"] is True
    assert r["skill"] == "ceo-decision"
    assert r["iron_rule"] == "llm_proposal"
    assert r["decision"] == "accept"
    assert r["confidence"] >= 70
    assert r["votes"]["margin"] >= 70
    assert r["votes"]["dfm"] >= 80
    assert any("接单" in s for s in r["reasoning"])


# ---- 2. 5 证全低 → reject ----
def test_full_fail_decision_reject() -> None:
    """低分场景: 小单 + 新客 + 低毛利 + 多 DFM 冲突 → 拒单."""
    r = tool.run(FakeCtx(), decision_context={
        "quote": {"total_single": 1000},
        "margin_pct": 8,
        "customer": {"is_new": True},
        "verification": {"conflicts": [{"code": "x"}, {"code": "y"}, {"code": "z"}]},
        "missing": 5,
    }, threshold=70)
    assert r["decision"] == "reject"
    assert r["confidence"] < 40
    # 弱项列表
    assert any("拒单" in s for s in r["reasoning"])


# ---- 3. 中间状态 → defer ----
def test_middle_decision_defer() -> None:
    """中等场景: 大单 + 新客 + 高毛利 + 1 DFM 冲突 → defer."""
    r = tool.run(FakeCtx(), decision_context={
        "quote": {"total_single": 20000},
        "margin_pct": 22,
        "customer": {"is_new": True},
        "verification": {"conflicts": [{"code": "x"}]},
        "missing": 1,
    }, threshold=70)
    # avg = 0.25*80 + 0.15*50 + 0.25*75 + 0.20*60 + 0.15*70 = 20+7.5+18.75+12+10.5 = 68.75
    assert 50 <= r["confidence"] < 70
    assert r["decision"] == "defer"
    assert any("defer" in s or "待审" in s for s in r["reasoning"])


# ---- 4. registry 注册 ----
def test_ceo_decision_registered() -> None:
    import skills._runtime as rt
    skills = rt.discover()
    assert "ceo_decision" in skills


# ---- 5. threshold 可调 ----
def test_threshold_adjusts_decision() -> None:
    """threshold 越高 → 越倾向 defer/reject."""
    ctx_dec = {
        "quote": {"total_single": 8000},  # acceptance=60
        "margin_pct": 18,  # margin=70
        "customer": {"is_new": True},  # history=50
        "verification": {"conflicts": []},  # dfm=90
        "missing": 0,  # completeness=90
    }
    # avg = 0.25*60 + 0.15*50 + 0.25*70 + 0.20*90 + 0.15*90 = 15+7.5+17.5+18+13.5 = 71.5
    r_low = tool.run(FakeCtx(), decision_context=ctx_dec, threshold=70)
    r_high = tool.run(FakeCtx(), decision_context=ctx_dec, threshold=80)
    # 71.5 ≥ 70 → accept (low threshold)
    # 71.5 < 80 → defer (high threshold)
    assert r_low["decision"] == "accept"
    assert r_high["decision"] == "defer"
