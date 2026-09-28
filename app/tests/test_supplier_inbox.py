"""test_supplier_inbox.py — v2.3.0 供应商收件箱（mock 实现 + IMAP 占位）。

契约：mock 返回结构化报价；IMAP 必须显式开启（默认 raise NotImplementedError）。
"""
from __future__ import annotations

import pytest

from supplier_module.supplier_inbox import (
    SupplierInbox,
    MockInbox,
    IMAPInbox,
    SupplierQuote,
)


def test_mock_inbox_returns_quote_per_supplier():
    inbox = MockInbox(responses={
        1: SupplierQuote(supplier_id=1, unit_price_cny=200.0,
                         lead_time_days=12, quality="ISO9001", confidence=0.9),
        2: SupplierQuote(supplier_id=2, unit_price_cny=210.0,
                         lead_time_days=14, quality="AS9100", confidence=0.85),
    })
    quotes = inbox.fetch_quotes(pipeline_id="pipe-1", supplier_ids=[1, 2, 3])
    assert len(quotes) == 3
    assert quotes[0].supplier_id == 1
    assert quotes[0].unit_price_cny == 200.0
    # 未配置的供应商用 fallback
    assert quotes[2].supplier_id == 3
    assert quotes[2].unit_price_cny == 0.0  # fallback 默认


def test_mock_inbox_custom_fallback():
    inbox = MockInbox(responses={}, fallback_unit_price=180.0,
                      fallback_lead_time_days=20)
    q = inbox.fetch_quotes("pipe-1", supplier_ids=[99])[0]
    assert q.unit_price_cny == 180.0
    assert q.lead_time_days == 20


def test_mock_inbox_empty_list():
    inbox = MockInbox()
    assert inbox.fetch_quotes("pipe-1", supplier_ids=[]) == []


def test_mock_inbox_simulate_failure():
    """可模拟某个供应商未响应。"""
    inbox = MockInbox(responses={1: None})  # None = 未响应
    quotes = inbox.fetch_quotes("pipe-1", supplier_ids=[1, 2])
    assert len(quotes) == 2
    # None 占位 → 转 fallback
    assert quotes[0].supplier_id == 1
    assert quotes[0].unit_price_cny == 0.0  # 未响应 → 价格 0


def test_imap_inbox_default_raises():
    """默认 IMAPInbox 必须 raise，避免数据意外外发。"""
    inbox = IMAPInbox()
    with pytest.raises(NotImplementedError, match="egress"):
        inbox.fetch_quotes("pipe-1", supplier_ids=[1])


def test_imap_inbox_explicit_enabled_runs():
    """显式 enabled=True 后才能用（模拟，避免生产意外外发）。"""
    inbox = IMAPInbox(enabled=True)
    quotes = inbox.fetch_quotes("pipe-1", supplier_ids=[1, 2])
    assert len(quotes) == 2
    assert all(q.unit_price_cny > 0 for q in quotes)


def test_supplier_quote_to_dict_roundtrip():
    q = SupplierQuote(supplier_id=5, unit_price_cny=300.0,
                      lead_time_days=10, quality="AS9100", confidence=0.95)
    d = q.to_dict()
    assert d["supplier_id"] == 5
    assert d["unit_price_cny"] == 300.0
    q2 = SupplierQuote.from_dict(d)
    assert q2 == q