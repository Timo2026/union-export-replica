"""test_v12_status_api.py — v3.0 #42/#44 V12 内核状态 + 3 个 API 端点单测.

9 条覆盖 (凭代码核对, traces 隔离 tmp_path):
  V12Status (5):
    1) 空 traces_dir → calc_quote_total=0, dfm 全 0, kernel_online 由 TimoAdapter 决定
    2) 写入 3 条 calc_quote span + 2 条 dfm conflict span → calc_quote_total=3, dfm_total=2
    3) DFM rule 含 'C1'/'C2' → dfm_c1_c6_counts 桶正确
    4) calc_quote duration_ms p50/p95 正确计算
    5) audit(limit=5) 返回首条 trace 的 sha256_16 前 16
  API 端点 (4):
    6) GET /v1/v12/status 返回 version + kernel_online + source_label + counts
    7) GET /v1/v12/audit?limit=8 → hashes[] (≤8) + count
    8) GET /v1/v12/dfm → 仅 DFM 字段
    9) GET /v1/v12/status 不会因 traces_dir 缺失而 500
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services import v12_status as v12
from services.api_server import app


def _write_trace(trace_dir: Path, name: str, spans: list, trace_idx: int = 0):
    """写一条 trace_id_<idx>.jsonl, 每行一个 span dict."""
    p = trace_dir / f"trace_{trace_idx}.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for s in spans:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return p


@pytest.fixture
def traces_dir(tmp_path):
    return tmp_path / "traces"


@pytest.fixture
def fake_timo():
    class _FakeTimo:
        def health(self): return True
        def source_label(self): return "online:fake-timo"
        kernel_available = True
    return _FakeTimo()


# ---------------- V12Status ----------------
def test_status_empty_traces(traces_dir, fake_timo):
    """traces_dir 不存在 → 全 0, kernel_online=True (fake timo)."""
    s = v12.V12Status(timo=fake_timo, traces_dir=traces_dir)
    out = s.status()
    assert out["version"] == v12.V12_VERSION
    assert out["kernel_online"] is True
    assert out["source_label"] == "online:fake-timo"
    assert out["calc_quote_total"] == 0
    assert out["dfm_conflicts_total"] == 0
    for b in v12.DFM_BUCKETS:
        assert out["dfm_c1_c6_counts"][b] == 0
    assert out["trace_count"] == 0


def test_aggregate_calc_quote_and_dfm(traces_dir, fake_timo):
    """3 条 calc_quote + 2 条 dfm conflict → 计数正确."""
    traces_dir.mkdir()
    _write_trace(traces_dir, "t1", [
        {"name": "skill:cnc-quote", "duration_ms": 10, "trace_id": "t1s1", "attributes": {}, "status": "OK"},
        {"name": "skill:cnc-quote", "duration_ms": 20, "trace_id": "t1s2", "attributes": {}, "status": "OK"},
        {"name": "skill:cnc-quote", "duration_ms": 30, "trace_id": "t1s3", "attributes": {}, "status": "OK"},
        {"name": "skill:dfm-conflict", "trace_id": "t1s4", "attributes": {"rule": "C1_tolerance"}, "status": "ERROR"},
        {"name": "skill:dfm-conflict", "trace_id": "t1s5", "attributes": {"rule": "C5_material"}, "status": "ERROR"},
    ])
    out = v12.V12Status(timo=fake_timo, traces_dir=traces_dir).status()
    assert out["calc_quote_total"] == 3
    assert out["dfm_conflicts_total"] == 2
    assert out["dfm_c1_c6_counts"]["C1"] == 1
    assert out["dfm_c1_c6_counts"]["C5"] == 1
    assert out["dfm_c1_c6_counts"]["C2"] == 0
    assert out["span_count"] == 5


def test_calc_quote_p50_p95(traces_dir, fake_timo):
    """p50 = 中位, p95 = 第 95% (≥20 取该位置)."""
    traces_dir.mkdir()
    durations = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    _write_trace(traces_dir, "t1", [
        {"name": "skill:cnc-quote", "duration_ms": d, "trace_id": f"t1s{i}", "attributes": {}, "status": "OK"}
        for i, d in enumerate(durations)
    ])
    out = v12.V12Status(timo=fake_timo, traces_dir=traces_dir).status()
    assert out["calc_quote_total"] == 10
    # 10 个数, 中位 index 5 → duration 60
    assert out["calc_quote_p50_ms"] == 60
    # <20 → p95 = max = 100
    assert out["calc_quote_p95_ms"] == 100


def test_audit_limit(traces_dir, fake_timo):
    """audit(limit=5) → 每文件首行 trace_id 前 16 作 sha256_16."""
    traces_dir.mkdir()
    for i in range(8):
        _write_trace(traces_dir, f"t{i}", [
            {"trace_id": f"abc{i:02d}_xx_full", "context_id": f"RFQ-{i}", "start_time": 1000+i},
            {"trace_id": "ignore_second_line", "context_id": "ignored"},
        ], trace_idx=i)
    out = v12.V12Status(timo=fake_timo, traces_dir=traces_dir).audit(limit=5)
    assert out["count"] <= 5
    assert len(out["hashes"]) <= 5
    for h in out["hashes"]:
        assert len(h["sha256_16"]) == 16
        assert h["trace_id"].startswith("abc")


def test_status_timo_failure(traces_dir):
    """TimoAdapter.health() 抛异常 → kernel_online=False, source_label=offline fallback."""
    class _BadTimo:
        def health(self): raise RuntimeError("boom")
        def source_label(self): return "should_not_be_called"
        kernel_available = False
    s = v12.V12Status(timo=_BadTimo(), traces_dir=traces_dir)
    out = s.status()
    assert out["kernel_online"] is False
    assert "offline" in out["source_label"].lower()


# ---------------- API 端点 ----------------
@pytest.fixture(scope="module")
def api_client():
    with TestClient(app) as c:
        yield c


def test_api_v12_status(api_client):
    """GET /v1/v12/status 返回完整结构."""
    r = api_client.get("/v1/v12/status")
    assert r.status_code == 200
    d = r.json()
    assert "version" in d
    assert "kernel_online" in d
    assert "source_label" in d
    assert "calc_quote_total" in d
    assert "dfm_c1_c6_counts" in d
    assert set(d["dfm_c1_c6_counts"].keys()) == {"C1","C2","C3","C4","C5","C6"}


def test_api_v12_audit(api_client):
    """GET /v1/v12/audit?limit=8 → hashes[]."""
    r = api_client.get("/v1/v12/audit?limit=8")
    assert r.status_code == 200
    d = r.json()
    assert "hashes" in d
    assert "count" in d
    assert isinstance(d["hashes"], list)


def test_api_v12_dfm(api_client):
    """GET /v1/v12/dfm → dfm_c1_c6_counts."""
    r = api_client.get("/v1/v12/dfm")
    assert r.status_code == 200
    d = r.json()
    assert "dfm_c1_c6_counts" in d
    assert "dfm_conflicts_total" in d
    assert "span_count" in d


def test_api_v12_status_no_500_on_empty_traces(api_client, tmp_path, monkeypatch):
    """即使 traces_dir 不存在, 也不应 500."""
    from services import v12_api
    monkeypatch.setattr(v12_api._V12, "traces_dir", tmp_path / "nonexistent")
    r = api_client.get("/v1/v12/status")
    assert r.status_code == 200
    d = r.json()
    assert d["calc_quote_total"] == 0
    assert d["trace_count"] == 0