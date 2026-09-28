"""test_postmortem.py — P3 闭环复盘 + 客户记忆召回.

用临时 SQLite CRM, 不污染主库。验证:
  record_outcome 计算成本/交期偏差 → 产出 knowledge_updates;
  won/lost 校验; 客户记忆召回给出 repeat_customer / historical_margin / past_loss 信号。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from services.crm_memory import CRMMemory
from services.postmortem import recall_customer_memory, record_outcome


@pytest.fixture()
def crm(tmp_path):
    c = CRMMemory(str(tmp_path / "test_crm.sqlite3"))
    yield c
    c.close()


def _seed_quote(crm, cid, customer, name, final=10000.0, unit=200.0, margin=23.0, lead=10):
    crm.upsert_customer({"customer_id": customer, "name": name})
    crm.write_rfq({"context_id": cid, "rfq": {"customer": {"customer_id": customer}}, "state": "DONE"})
    crm.write_quote({"context_id": cid,
                     "commercial": {"quote": {"unit_price": unit, "final_price": final,
                                              "lead_time_days": lead}, "margin_pct": margin}},
                    {"status": "PASS"}, {"subject": "q", "auto_send": False})


def test_record_won_with_cost_overrun(crm):
    _seed_quote(crm, "RFQ-1", "CUST-1", "Acme", final=10000.0, lead=10)
    a = record_outcome(crm, "RFQ-1", "won", actual_cost=11500.0, actual_leadtime_days=14)
    assert a["outcome"] == "won"
    assert a["deviation"]["cost_pct"] == 15.0
    assert a["deviation"]["leadtime_days"] == 4
    types = [k["type"] for k in a["knowledge_updates"]]
    assert "price_underestimate" in types and "leadtime_overrun" in types


def test_record_won_cost_underrun(crm):
    _seed_quote(crm, "RFQ-2", "CUST-2", "Beta", final=10000.0)
    a = record_outcome(crm, "RFQ-2", "won", actual_cost=9000.0)
    assert a["deviation"]["cost_pct"] == -10.0
    assert any(k["type"] == "price_overestimate" for k in a["knowledge_updates"])


def test_record_lost(crm):
    _seed_quote(crm, "RFQ-3", "CUST-3", "Gamma", final=10000.0)
    a = record_outcome(crm, "RFQ-3", "lost")
    assert any(k["type"] == "loss_review" for k in a["knowledge_updates"])


def test_invalid_outcome_raises(crm):
    _seed_quote(crm, "RFQ-4", "CUST-4", "Delta")
    with pytest.raises(ValueError):
        record_outcome(crm, "RFQ-4", "maybe")


def test_customer_memory_recall_new_then_repeat(crm):
    cust = {"customer_id": "CUST-9", "name": "Northwind"}
    # 新客户
    m0 = recall_customer_memory(crm, cust)
    assert m0["recall"] is True and m0["is_new"] is True and m0["signals"] == []
    # 写两条历史
    _seed_quote(crm, "RFQ-A", "CUST-9", "Northwind", final=8000.0, margin=22.0)
    _seed_quote(crm, "RFQ-B", "CUST-9", "Northwind", final=9000.0, margin=24.0)
    m1 = recall_customer_memory(crm, cust)
    assert m1["is_new"] is False
    sig = [s["type"] for s in m1["signals"]]
    assert "repeat_customer" in sig and "historical_margin" in sig


def test_customer_memory_recall_flags_past_loss(crm):
    _seed_quote(crm, "RFQ-L", "CUST-5", "LostCo", final=5000.0)
    record_outcome(crm, "RFQ-L", "lost")
    m = recall_customer_memory(crm, {"customer_id": "CUST-5", "name": "LostCo"})
    # 丢单信号来自全局 postmortems 召回
    assert m["recall"] is True


def test_recall_disabled_without_crm():
    m = recall_customer_memory(None, {"name": "X"})
    assert m["recall"] is False
