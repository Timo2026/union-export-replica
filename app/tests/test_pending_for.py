"""test_pending_for.py — v3.0 #33 pending_for() 单测.

覆盖 4 条:
  1. 空表 → []
  2. 有数据 (NEW/HITL/PASS) → 全部返回，DONE/BLOCKED 排除
  3. 按 customer_id 过滤
  4. limit 生效 + created_at DESC 排序
"""
from __future__ import annotations

import time

import pytest

from services.crm_memory import CRMMemory


@pytest.fixture
def crm(tmp_path):
    db = tmp_path / "test_pending.sqlite3"
    c = CRMMemory(str(db))
    yield c
    c.close()


def _seed(c: CRMMemory, ctx_id: str, cust_id: str, state: str, ts: float):
    """内部 helper: 直接写 rfqs 表 (绕过 write_rfq 因为它要 ctx_dict 完整结构)."""
    c._conn.execute(
        "INSERT INTO rfqs(context_id,customer_id,material,surface,quantity,"
        "tolerance,state,created_at,payload) VALUES(?,?,?,?,?,?,?,?,?)",
        (ctx_id, cust_id, "6061", "as-machined", 100, "IT7", state, ts, "{}"),
    )
    c._conn.commit()


def test_pending_for_empty(crm):
    """空表 → []. 边界 case 1."""
    assert crm.pending_for() == []


def test_pending_for_excludes_done_and_blocked(crm):
    """NEW/HITL/PASS → 全部返回，DONE/BLOCKED 排除. 边界 case 2."""
    _seed(crm, "RFQ-001", "CUST-A", "NEW", time.time() - 100)
    _seed(crm, "RFQ-002", "CUST-A", "HITL", time.time() - 90)
    _seed(crm, "RFQ-003", "CUST-A", "PASS", time.time() - 80)
    _seed(crm, "RFQ-004", "CUST-B", "DONE", time.time() - 70)
    _seed(crm, "RFQ-005", "CUST-B", "BLOCKED", time.time() - 60)

    out = crm.pending_for()
    states = {r["state"] for r in out}
    ctx_ids = {r["context_id"] for r in out}

    assert "DONE" not in states, "DONE 不应出现"
    assert "BLOCKED" not in states, "BLOCKED 不应出现"
    assert {"RFQ-001", "RFQ-002", "RFQ-003"} <= ctx_ids
    assert "RFQ-004" not in ctx_ids
    assert "RFQ-005" not in ctx_ids
    assert len(out) == 3


def test_pending_for_filter_by_customer(crm):
    """按 customer_id 过滤. 边界 case 3."""
    _seed(crm, "RFQ-001", "CUST-A", "NEW", time.time())
    _seed(crm, "RFQ-002", "CUST-A", "HITL", time.time())
    _seed(crm, "RFQ-003", "CUST-B", "NEW", time.time())

    out_a = crm.pending_for(customer_id="CUST-A")
    out_b = crm.pending_for(customer_id="CUST-B")

    assert all(r["customer_id"] == "CUST-A" for r in out_a)
    assert {r["context_id"] for r in out_a} == {"RFQ-001", "RFQ-002"}
    assert all(r["customer_id"] == "CUST-B" for r in out_b)
    assert {r["context_id"] for r in out_b} == {"RFQ-003"}


def test_pending_for_limit_and_desc_order(crm):
    """limit 生效 + created_at DESC. 边界 case 4."""
    now = time.time()
    _seed(crm, "RFQ-OLD", "CUST-A", "NEW", now - 1000)
    _seed(crm, "RFQ-MID", "CUST-A", "HITL", now - 500)
    _seed(crm, "RFQ-NEW", "CUST-A", "PASS", now - 10)

    out = crm.pending_for(limit=2)
    assert len(out) == 2
    # created_at DESC: NEW 在前, MID 居中, OLD 排除
    ctx_ids = [r["context_id"] for r in out]
    assert ctx_ids == ["RFQ-NEW", "RFQ-MID"]
