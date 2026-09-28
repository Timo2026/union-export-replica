"""T1 (UI 全接线): POST /v1/demo/scenario/{sid} — 黄金场景一键装载.

修复 webui 6 个死按钮 (index.html:694-699 → /v1/demo/scenario, 端点此前不存在 #35).
链路: data/golden_scenarios.json → 写 data/mailbox/DEMO-{sid}-{ts}.eml (+meta badges=NEW)
      → MailPuller._enqueue_pending_from_mailbox (driver=email)
      → MailOrchestrator.run_pipeline (同步, CAT stub) → {ok, mail_id, state, context_id}.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parent.parent


class StubCAT:
    """最小 CAT 替身: run() 返回可预测 verdict."""

    def __init__(self, verdict: str = "PASS"):
        self.verdict = verdict
        self.calls = []

    def run(self, email_text="", customer=None, driver="email", **kwargs):
        self.calls.append({"email_text": email_text, "customer": customer, "driver": driver})
        return {
            "state": self.verdict,
            "verification_status": self.verdict,
            "context_id": "RFQ-DEMO-TEST",
            "audit_valid": True,
            "quote": {"unit_price": 1.0, "final_price": 2.0},
            "reply": {"subject": "s", "auto_send": False},
            "reasons": [],
        }


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from services import api_server as api

    # 隔离根: 真 golden_scenarios.json 拷入, mailbox/pending 全空
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy(_ROOT / "data" / "golden_scenarios.json",
                tmp_path / "data" / "golden_scenarios.json")
    (tmp_path / "data" / "mailbox").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(api, "_ROOT", tmp_path)
    monkeypatch.setattr(api, "_mail_bg", {})
    stub = StubCAT("PASS")
    monkeypatch.setattr(api, "ctrl", lambda: stub)
    c = TestClient(api.app)
    c.stub = stub          # type: ignore[attr-defined]
    c.tmp_root = tmp_path  # type: ignore[attr-defined]
    return c


def test_scenario_s1_full_chain(client):
    r = client.post("/v1/demo/scenario/S1")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["scenario"] == "S1"
    assert d["state"] == "DONE"
    assert d["mail_id"].startswith("DEMO-S1-")
    assert d["context_id"] == "RFQ-DEMO-TEST"
    # CAT 收到真场景邮件正文 + driver=email (方案 D 标记)
    assert len(client.stub.calls) == 1
    call = client.stub.calls[0]
    assert "motor bracket" in call["email_text"]
    assert call["driver"] == "email"
    # eml + meta 落盘 mailbox
    eml = client.tmp_root / "data" / "mailbox" / f'{d["mail_id"]}.eml'
    assert eml.exists()
    meta = json.loads((eml.with_suffix(".meta.json")).read_text(encoding="utf-8"))
    assert "NEW" in meta["badges"]
    # pending.jsonl 有 DONE 条目 (driver=email)
    pend = (client.tmp_root / "data" / "mail_puller" / "pending.jsonl").read_text(encoding="utf-8")
    row = next(json.loads(l) for l in pend.splitlines() if d["mail_id"] in l)
    assert row["state"] == "DONE"
    assert row["driver"] == "email"


def test_scenario_hitl_verdict(client, monkeypatch):
    from services import api_server as api
    monkeypatch.setattr(api, "ctrl", lambda: StubCAT("HITL"))
    r = client.post("/v1/demo/scenario/S2")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["state"] == "HITL"
    assert d["mail_id"].startswith("DEMO-S2-")


def test_scenario_unknown_404(client):
    r = client.post("/v1/demo/scenario/XX")
    assert r.status_code == 404


def test_stale_new_pending_does_not_steal_claim(client):
    """pending.jsonl 有陈年 NEW 条目时, claim_next_new(FIFO) 会拿错信 —
    端点必须先 mark_state(PROCESSING) 占租约 (真服务器冒烟抓到的 claim race)."""
    pend_dir = client.tmp_root / "data" / "mail_puller"
    pend_dir.mkdir(parents=True, exist_ok=True)
    (pend_dir / "pending.jsonl").write_text(
        json.dumps({"mail_id": "OLD-STALE-1", "state": "NEW", "driver": "email"}) + "\n",
        encoding="utf-8")
    r = client.post("/v1/demo/scenario/S3")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True and d["state"] == "DONE", d
    assert d["mail_id"].startswith("DEMO-S3-")
    assert "claim race" not in (d.get("reason") or "")
    # 陈年条目没被动过
    rows = [json.loads(l) for l in
            (pend_dir / "pending.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    old = next(x for x in rows if x["mail_id"] == "OLD-STALE-1")
    assert old["state"] == "NEW"


def test_scenario_all_ids_valid(client):
    ids = json.loads((client.tmp_root / "data" / "golden_scenarios.json")
                     .read_text(encoding="utf-8"))["scenarios"]
    for sc in ids:
        r = client.post(f'/v1/demo/scenario/{sc["id"]}')
        assert r.status_code == 200, f'{sc["id"]}: {r.text}'
        assert r.json()["mail_id"].startswith(f'DEMO-{sc["id"]}-')
