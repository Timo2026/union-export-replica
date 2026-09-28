"""test_po_generator.py — v2.3.0 采购单（PO）生成。

契约：PO 文本只包含技术字段 + 客户指纹；不含 PII。
"""
from __future__ import annotations

import io
import zipfile

import pytest

from supplier_module.desensitize import DesensitizeRequest, desensitize
from supplier_module.po_generator import generate_po, PO


CUSTOMER = {
    "name": "Acme Industrial Co., Ltd.",
    "contact_person": "John Smith",
    "email": "john.smith@acme-industrial.com",
    "phone": "13800138000",
    "address": "123 Customer Street, New York, NY 10001, USA",
    "project_code": "ACME-2026-001",
}


def _rfq():
    return {
        "material": "6061",
        "processes": ["milling"],
        "quantity": 50,
        "promised_lead_time_days": 14,
        "tolerance_grade": "IT7",
        "dimensions_mm": [100, 50, 10],
    }


def _selected_supplier():
    return {
        "id": 1,
        "name": "苏州精工 CNC 一厂",
        "region": "domestic",
        "lead_time_days": 10,
        "contact_email": "sales@sz-jingong.cn",
    }


def _quote():
    return {"supplier_id": 1, "unit_price_cny": 200.0, "lead_time_days": 10,
            "quality": "ISO9001", "confidence": 0.9}


def test_po_contains_required_fields():
    po = generate_po(context_id="ctx-po-1", customer=CUSTOMER,
                     rfq=_rfq(), supplier=_selected_supplier(), quote=_quote())
    txt = po.text
    assert "PO-" in txt or "PURCHASE ORDER" in txt
    assert "苏州精工 CNC 一厂" in txt
    assert "6061" in txt
    assert "200" in txt  # unit_price_cny


def test_po_text_excludes_customer_pii():
    po = generate_po(context_id="ctx-po-2", customer=CUSTOMER,
                     rfq=_rfq(), supplier=_selected_supplier(), quote=_quote())
    txt = po.text
    # 不应包含客户 PII（指纹代替）
    assert "Acme Industrial" not in txt
    assert "john.smith" not in txt
    assert "13800138000" not in txt
    assert "ACME-2026-001" not in txt
    assert "New York" not in txt
    # 应包含客户指纹占位
    assert "CUSTOMER_FINGERPRINT" in txt or po.customer_fingerprint in txt


def test_po_includes_outsource_markup():
    """PO 单价 × (1 + markup) = 我方对客户的卖价（外协路径独立计算）。"""
    po = generate_po(context_id="ctx-po-3", customer=CUSTOMER,
                     rfq=_rfq(), supplier=_selected_supplier(), quote=_quote(),
                     markup_pct=30.0)
    # 200 × 1.30 = 260
    assert "260" in po.text or "260.00" in po.text


def test_po_markup_zero_keeps_base_price():
    po = generate_po(context_id="ctx-po-4", customer=CUSTOMER,
                     rfq=_rfq(), supplier=_selected_supplier(), quote=_quote(),
                     markup_pct=0.0)
    assert "200" in po.text
    # 不应有 260
    assert "260.00" not in po.text


def test_po_serializes_to_dict():
    po = generate_po(context_id="ctx-po-5", customer=CUSTOMER,
                     rfq=_rfq(), supplier=_selected_supplier(), quote=_quote())
    d = po.to_dict()
    assert d["context_id"] == "ctx-po-5"
    assert d["supplier_id"] == 1
    assert d["customer_fingerprint"] == po.customer_fingerprint
    assert d["unit_price_cny"] == 200.0
    assert "text" in d


def test_po_with_zero_files_still_valid():
    """无文件也能生成 PO（脱敏 ZIP 可选附件）。"""
    po = generate_po(context_id="ctx-po-6", customer=CUSTOMER,
                     rfq=_rfq(), supplier=_selected_supplier(), quote=_quote())
    assert isinstance(po.text, str)
    assert len(po.text) > 50


def test_po_dataclass_construction():
    p = PO(context_id="x", supplier_id=1, customer_fingerprint="abc",
           unit_price_cny=100.0, total_cny=5000.0, lead_time_days=10,
           text="hello", created_at=time_int_now())
    assert p.context_id == "x"


def time_int_now():
    import time
    return int(time.time())