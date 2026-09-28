"""test_observability.py — OTEL 风格 trace/span + metrics 单元测试."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.observability import Tracer


def test_trace_ids_and_parenting(tmp_path):
    t = Tracer("RFQ-TRACE-1", export_dir=str(tmp_path))
    root = t.start_span("agent_run", kind="server")
    t._push(root)
    child = t.start_span("skill:cnc-quote", kind="client")
    assert child.parent_id == root.span_id
    assert child.trace_id == root.trace_id == t.trace_id
    child.end = child.start + 0.01; child.status = "OK"
    root.end = root.start + 0.02; root.status = "OK"
    d = t.export()
    assert d["trace_id"] == t.trace_id
    assert len(d["spans"]) == 2
    # JSONL 落盘
    p = Path(d["export_path"])
    assert p.exists()
    lines = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2


def test_span_context_manager_sets_status(tmp_path):
    t = Tracer("RFQ-TRACE-2", export_dir=str(tmp_path))
    with t.start_span("verification") as sp:
        sp.set(status="PASS")
    assert sp.status == "OK" and sp.end is not None
    assert sp.to_dict()["attributes"]["status"] == "PASS"


def test_span_context_manager_marks_error(tmp_path):
    t = Tracer("RFQ-TRACE-3", export_dir=str(tmp_path))
    with pytest.raises(ValueError):
        with t.start_span("boom"):
            raise ValueError("x")
    sp = t.spans[-1]
    assert sp.status == "ERROR" and "error" in sp.attrs


def test_metrics_bump(tmp_path):
    t = Tracer("RFQ-TRACE-4", export_dir=str(tmp_path))
    t.bump("tool_calls", 3); t.bump("hitl_triggers"); t.bump("retrievals", 2)
    assert t.metrics["tool_calls"] == 3
    assert t.metrics["hitl_triggers"] == 1
    assert t.metrics["retrievals"] == 2


def test_correlation_chain(tmp_path):
    t = Tracer("RFQ-TRACE-5", export_dir=str(tmp_path))
    root = t.start_span("agent_run"); t._push(root)
    t.start_span("skill:dfm-conflict").status = "OK"
    t.start_span("verification").status = "OK"
    corr = t.correlation()
    assert corr[0].startswith("agent_run")
    assert any("dfm-conflict" in c for c in corr)


def test_otlp_failure_degrades_not_raises(tmp_path):
    # 指向不可达 OTLP endpoint → 显式降级, 不抛异常
    t = Tracer("RFQ-TRACE-6", export_dir=str(tmp_path), otlp_endpoint="http://127.0.0.1:59998/v1/traces")
    t.start_span("agent_run").status = "OK"
    d = t.export()
    assert d["otlp"]["exported"] is False
    assert "degraded" in d["otlp"]
