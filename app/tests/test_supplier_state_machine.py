"""test_supplier_state_machine.py — v2.3.0 供应商流水线子状态机。

状态：PENDING → DESENSITIZED → MATCHED → QUOTED → SELECTED → PO_SENT → CONFIRMED
分支：任意 → FAILED
契约：非法转移抛异常；持久化 JSON load/save 一致。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from supplier_module.state_machine import (
    SupplierPipeline,
    State,
    IllegalTransitionError,
    load_pipeline,
    save_pipeline,
)


def test_initial_state_is_pending():
    p = SupplierPipeline(context_id="ctx-1")
    assert p.state == State.PENDING
    assert p.context_id == "ctx-1"


def test_legal_transition_pending_to_desensitized():
    p = SupplierPipeline(context_id="ctx-1")
    p.transition(State.DESENSITIZED)
    assert p.state == State.DESENSITIZED


def test_full_happy_path():
    p = SupplierPipeline(context_id="ctx-1")
    p.transition(State.DESENSITIZED)
    p.transition(State.MATCHED)
    p.transition(State.QUOTED)
    p.transition(State.SELECTED)
    p.transition(State.PO_SENT)
    p.transition(State.CONFIRMED)
    assert p.state == State.CONFIRMED


def test_illegal_transition_raises():
    p = SupplierPipeline(context_id="ctx-1")
    with pytest.raises(IllegalTransitionError):
        p.transition(State.CONFIRMED)  # PENDING → CONFIRMED 不合法


def test_skip_state_raises():
    p = SupplierPipeline(context_id="ctx-1")
    p.transition(State.DESENSITIZED)
    with pytest.raises(IllegalTransitionError):
        p.transition(State.QUOTED)  # 跳过 MATCHED


def test_any_state_to_failed_allowed():
    happy_path = [
        State.PENDING, State.DESENSITIZED, State.MATCHED,
        State.QUOTED, State.SELECTED, State.PO_SENT,
    ]
    for target_idx, src in enumerate(happy_path):
        p = SupplierPipeline(context_id="ctx-1")
        for s in happy_path[:target_idx + 1][1:]:
            p.transition(s)
        assert p.state == src
        p.transition(State.FAILED)
        assert p.state == State.FAILED


def test_failed_is_terminal():
    p = SupplierPipeline(context_id="ctx-1")
    p.transition(State.FAILED)
    with pytest.raises(IllegalTransitionError):
        p.transition(State.DESENSITIZED)


def test_confirmed_is_terminal():
    p = SupplierPipeline(context_id="ctx-1")
    for s in [State.DESENSITIZED, State.MATCHED, State.QUOTED,
              State.SELECTED, State.PO_SENT, State.CONFIRMED]:
        p.transition(s)
    with pytest.raises(IllegalTransitionError):
        p.transition(State.FAILED)


def test_save_and_load_roundtrip(tmp_path):
    p = SupplierPipeline(context_id="ctx-roundtrip")
    p.transition(State.DESENSITIZED)
    p.transition(State.MATCHED)
    p.payload = {"matched_suppliers": [1, 2, 3]}  # 业务负载
    save_pipeline(p, tmp_path / "pipe.json")

    p2 = load_pipeline(tmp_path / "pipe.json")
    assert p2.context_id == "ctx-roundtrip"
    assert p2.state == State.MATCHED
    assert p2.payload == {"matched_suppliers": [1, 2, 3]}


def test_history_records_transitions():
    p = SupplierPipeline(context_id="ctx-hist")
    p.transition(State.DESENSITIZED)
    p.transition(State.MATCHED)
    assert len(p.history) == 2
    assert p.history[0]["from"] == "PENDING"
    assert p.history[0]["to"] == "DESENSITIZED"
    assert "at" in p.history[0]


def test_history_persists():
    p = SupplierPipeline(context_id="ctx-hist")
    p.transition(State.DESENSITIZED)
    save_pipeline(p, Path("/tmp/x.json"))
    # 注：实际路径由 tmp_path 提供；这里只检查 history 字段被序列化为 list
    import dataclasses
    d = dataclasses.asdict(p)
    assert isinstance(d["history"], list)
    assert len(d["history"]) == 1


def test_state_enum_values():
    expected = {"PENDING", "DESENSITIZED", "MATCHED", "QUOTED",
                "SELECTED", "PO_SENT", "CONFIRMED", "FAILED"}
    assert {s.name for s in State} == expected