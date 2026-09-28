"""T2 补强: /v1/rfq/* 对邮件驱动/重启后 context 的落盘回退 (rehydrate).

场景: demo scenario / 邮件链路的 context 不在 api_server._STORE (仅 intake 写入),
服务器重启也会清空 _STORE。_need 应回退读 data/contexts/{cid}.json 重建 result,
使 RFQ 管线标签对任意历史 context 可用。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _ctx_file(tmp_root: Path, cid: str) -> None:
    d = tmp_root / "data" / "contexts"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cid}.json").write_text(json.dumps({
        "context_id": cid,
        "state": "HITL",
        "customer": {"name": "Northwind", "customer_id": "CUST-0001"},
        "rfq": {"raw_text": "quote 50 pcs brackets", "quantity": 50},
        "decision": {"status": "HITL", "reasons": ["margin below floor"],
                     "next_action": "human_review",
                     "reply": {"subject": "RE: RFQ", "auto_send": False}},
        "risk": {"multimodal_conflicts": ["tolerance"], "customer_signals": []},
        "manufacturing": {"dfm": {"C1": 0, "conflicts": []}},
        "commercial": {"quote": {"unit_price": 12.3, "final_price": 615.0},
                       "margin_pct": 9.1, "source": "offline-kernel",
                       "incoterm": "DDP", "landed_cost": 700.0},
    }, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from services import api_server as api
    monkeypatch.setattr(api, "_ROOT", tmp_path)
    monkeypatch.setattr(api, "_STORE", {})
    return TestClient(api.app), tmp_path


def test_get_rfq_rehydrates_from_disk(client):
    c, tmp_root = client
    _ctx_file(tmp_root, "RFQ-REHY-1")
    r = c.get("/v1/rfq/RFQ-REHY-1")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["state"] == "HITL"
    assert d["verification_status"] == "HITL"
    assert d["quote"]["unit_price"] == 12.3
    assert d["margin_pct"] == 9.1
    assert d["multimodal_conflicts"] == ["tolerance"]
    assert d["reply"]["subject"] == "RE: RFQ"
    assert d["engine_source"] == "offline-kernel"
    assert d["_rehydrated"] is True


def test_analyze_verify_work_on_rehydrated(client):
    c, tmp_root = client
    _ctx_file(tmp_root, "RFQ-REHY-2")
    a = c.post("/v1/rfq/RFQ-REHY-2/analyze")
    assert a.status_code == 200
    assert a.json()["multimodal_conflicts"] == ["tolerance"]
    v = c.post("/v1/rfq/RFQ-REHY-2/verify")
    assert v.status_code == 200
    assert v.json()["status"] == "HITL"
    q = c.post("/v1/rfq/RFQ-REHY-2/quote")
    assert q.json()["quote"]["final_price"] == 615.0


def test_unknown_cid_still_404(client):
    c, _ = client
    assert c.get("/v1/rfq/RFQ-NOPE").status_code == 404
