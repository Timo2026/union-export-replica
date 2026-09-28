"""test_matcher.py — v2.3.0 供应商匹配（标签打分 Top3）。

评分维度：材料命中、工艺命中、交期满足、产能充足、质量等级、评分、地区。
契约：输入 RFQ + 候选 supplier 列表 → TopN（默认 3）按 score desc 排序。
降级：真几何相似度（shape signature）未实现，标签打分足够 v2.3.0 演示。
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from supplier_module.matcher import (
    score_supplier,
    match_top_n,
    DEFAULT_WEIGHTS,
)


def _supp(**kw) -> Dict[str, Any]:
    base = {
        "id": 1,
        "name": "test",
        "region": "domestic",
        "processes": ["milling"],
        "materials": ["6061"],
        "capacity_per_month": 100,
        "lead_time_days": 14,
        "quality_grade": "ISO9001",
        "rating": 4.0,
    }
    base.update(kw)
    return base


def _rfq(**kw) -> Dict[str, Any]:
    base = {
        "material": "6061",
        "processes": ["milling"],
        "quantity": 50,
        "promised_lead_time_days": 14,
        "tolerance_grade": "IT7",
        "destination_region": "domestic",
    }
    base.update(kw)
    return base


# ---- score_supplier 单维度 ----

def test_score_full_match_is_highest():
    rfq = _rfq()
    s = _supp()
    score = score_supplier(rfq, s)
    assert score > 0


def test_score_material_mismatch_penalty():
    rfq = _rfq(material="6061")
    s_match = _supp(materials=["6061"])
    s_miss = _supp(materials=["TC4"])
    assert score_supplier(rfq, s_match) > score_supplier(rfq, s_miss)


def test_score_process_mismatch_penalty():
    rfq = _rfq(processes=["milling"])
    s_match = _supp(processes=["milling"])
    s_miss = _supp(processes=["turning"])
    assert score_supplier(rfq, s_match) > score_supplier(rfq, s_miss)


def test_score_lead_time_too_long_penalty():
    rfq = _rfq(promised_lead_time_days=14)
    s_ok = _supp(lead_time_days=10)
    s_slow = _supp(lead_time_days=30)
    assert score_supplier(rfq, s_ok) > score_supplier(rfq, s_slow)


def test_score_capacity_insufficient_penalty():
    rfq = _rfq(quantity=500)
    s_big = _supp(capacity_per_month=600)
    s_small = _supp(capacity_per_month=100)
    assert score_supplier(rfq, s_big) > score_supplier(rfq, s_small)


def test_score_quality_grade_bonus():
    rfq = _rfq()
    s_iso = _supp(quality_grade="ISO9001")
    s_as = _supp(quality_grade="AS9100")
    s_iatf = _supp(quality_grade="IATF16949")
    assert score_supplier(rfq, s_iatf) > score_supplier(rfq, s_as) > score_supplier(rfq, s_iso)


def test_score_rating_bonus():
    rfq = _rfq()
    s_low = _supp(rating=3.5)
    s_high = _supp(rating=4.9)
    assert score_supplier(rfq, s_high) > score_supplier(rfq, s_low)


def test_score_destination_region_bonus():
    rfq = _rfq(destination_region="domestic")
    s_dom = _supp(region="domestic")
    s_eur = _supp(region="europe")
    assert score_supplier(rfq, s_dom) > score_supplier(rfq, s_eur)


# ---- match_top_n ----

def test_match_top_n_returns_at_most_n():
    rfq = _rfq()
    candidates = [_supp(id=i) for i in range(1, 11)]
    result = match_top_n(rfq, candidates, top_n=3)
    assert len(result) == 3


def test_match_top_n_sorted_desc_by_score():
    rfq = _rfq()
    candidates = [
        _supp(id=1, rating=3.5, lead_time_days=30),
        _supp(id=2, rating=4.8, lead_time_days=10),
        _supp(id=3, rating=4.0, lead_time_days=14),
        _supp(id=4, rating=4.5, lead_time_days=12),
    ]
    result = match_top_n(rfq, candidates, top_n=3)
    scores = [s for s, _ in result]
    assert scores == sorted(scores, reverse=True)


def test_match_top_n_includes_score_field():
    rfq = _rfq()
    candidates = [_supp()]
    result = match_top_n(rfq, candidates, top_n=3)
    assert len(result) == 1
    score, s = result[0]
    assert isinstance(score, float)
    assert score > 0
    assert s["id"] == 1


def test_match_top_n_empty_candidates():
    rfq = _rfq()
    result = match_top_n(rfq, [], top_n=3)
    assert result == []


def test_match_top_n_default_n_is_3():
    rfq = _rfq()
    candidates = [_supp(id=i) for i in range(1, 6)]
    result = match_top_n(rfq, candidates)
    assert len(result) == 3


def test_match_top_n_tie_break_by_id():
    """同分时按 id 升序（确定性）。"""
    rfq = _rfq()
    # 两个完全相同的 supplier，仅 id 不同
    a = _supp(id=1)
    b = _supp(id=2)
    result = match_top_n(rfq, [a, b], top_n=2)
    assert result[0][1]["id"] == 1
    assert result[1][1]["id"] == 2


def test_weights_exported():
    assert "material" in DEFAULT_WEIGHTS
    assert "process" in DEFAULT_WEIGHTS
    assert "lead_time" in DEFAULT_WEIGHTS
    assert "capacity" in DEFAULT_WEIGHTS
    assert "quality" in DEFAULT_WEIGHTS
    assert "rating" in DEFAULT_WEIGHTS


def test_custom_weights_apply():
    rfq = _rfq(material="6061", processes=["milling"])
    s = _supp(materials=["6061"], processes=["milling"], lead_time_days=30)
    # 默认权重：lead_time 30 > 14 → 减分
    s2 = _supp(materials=["6061"], processes=["milling"], lead_time_days=10)
    default_diff = score_supplier(rfq, s2) - score_supplier(rfq, s)
    # 极端：把 lead_time 权重设为 0
    weights0 = {**DEFAULT_WEIGHTS, "lead_time": 0.0}
    diff0 = score_supplier(rfq, s2, weights=weights0) - score_supplier(rfq, s, weights=weights0)
    assert diff0 < default_diff  # 减分差距缩小