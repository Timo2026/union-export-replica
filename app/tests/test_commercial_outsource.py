"""test_commercial_outsource.py — v2.3.0 外协 markup（与自产报价分轨）。

关键：markup 只作用于外协路径 SELL = PO 成本 ×(1+markup)，
与引擎 final_price（已含 30% 利润）**不双算**。
"""
from __future__ import annotations

import pytest

from services.commercial import compute_outsource_markup


def test_markup_30pct():
    sell = compute_outsource_markup(po_unit_price=200.0, markup_pct=30.0)
    assert sell == 260.0  # 200 × 1.30


def test_markup_0pct_returns_base():
    assert compute_outsource_markup(po_unit_price=200.0, markup_pct=0.0) == 200.0


def test_markup_negative_pct_discount():
    """负 markup 表示折扣（v2.3.0 不主推，但契约允许）。"""
    sell = compute_outsource_markup(po_unit_price=200.0, markup_pct=-10.0)
    assert sell == 180.0  # 200 × 0.90


def test_markup_100pct_doubles():
    assert compute_outsource_markup(po_unit_price=200.0, markup_pct=100.0) == 400.0


def test_markup_2_decimals():
    sell = compute_outsource_markup(po_unit_price=199.99, markup_pct=15.0)
    assert sell == round(199.99 * 1.15, 2)
    assert isinstance(sell, float)


def test_markup_zero_base_returns_zero():
    assert compute_outsource_markup(po_unit_price=0.0, markup_pct=30.0) == 0.0