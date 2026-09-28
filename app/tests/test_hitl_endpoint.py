"""test_hitl_endpoint.py — v3.0 #45 HITL 审批面板端点 + iron-rule-1 单测.

6 条覆盖 (凭代码核对, mock controller 不依赖外部):
  1) 无 meta.json (无 context_id) → ok=False, can_approve=False, reason='no context_id'
  2) 有 context_id 但 context.json 缺失 → ok=False, reason='context file missing'
  3) 有 context.json + 验证 PASS → locked=true, can_approve=False (仅 HITL 才可批)
  4) 有 context.json + 验证 HITL → can_approve=true (locked=true 时)
  5) 篡改报价: 写入 _meta['quote']['unit_price'] 后, quote_sha16 与 locked 不一致 → locked=false, can_approve=false, banner 触发
  6) SHA16 计算稳定: 同输入两次 → 同 hash

注意: 不真跑 Timo/Quote, 用 monkeypatch build_controller 返回 mock, 确保 verify.run() 返回目标 status.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api_server import app


@pytest.fixture(scope="module")
def api_client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def hitl_mailbox(tmp_path):
    """注入 mailbox + contexts + drafts, 隔离本机 data."""
    import services.mailbox_api as mb
    orig_mb = mb._MAILBOX_DIR
    orig_ctx = mb._CONTEXTS_DIR
    orig_dft = mb._DRAFTS_DIR
    mb._MAILBOX_DIR = tmp_path / "mailbox"
    mb._CONTEXTS_DIR = tmp_path / "contexts"
    mb._DRAFTS_DIR = tmp_path / "drafts"
    mb._MAILBOX_DIR.mkdir(parents=True, exist_ok=True)
    mb._CONTEXTS_DIR.mkdir(parents=True, exist_ok=True)
    mb._DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    yield mb
    mb._MAILBOX_DIR = orig_mb
    mb._CONTEXTS_DIR = orig_ctx
    mb._DRAFTS_DIR = orig_dft


def _write_mail(mb_dir, mail_id, ctx_id=None):
    (mb_dir / f"{mail_id}.eml").write_bytes(
        b"From: alice@acme.com\r\nTo: sales@union.io\r\nSubject: RFQ test\r\n\r\nbody\r\n"
    )
    meta = {"context_id": ctx_id, "badges": ["TEST"]}
    (mb_dir / f"{mail_id}.meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _write_context(ctx_dir, ctx_id, quote=None):
    q = quote or {
        "unit_price": 100.0,
        "final_price": 5000.0,
        "currency": "CNY",
        "lead_time_days": 7,
    }
    ctx = {
        "context_id": ctx_id,
        "rfq": {"material": "6061", "quantity": 50, "destination_country": "US", "shipping_mode": "air", "incoterm": "FOB"},
        "customer": {"name": "Test", "contact_name": "Alice"},
        "manufacturing": {"dfm": {"conflicts": []}},
        "commercial": {"quote": q},
    }
    (ctx_dir / f"{ctx_id}.json").write_text(json.dumps(ctx, ensure_ascii=False), encoding="utf-8")


def _patch_controller(api_client, status="PASS", reasons=None):
    """monkeypatch build_controller().verify.run() 返回固定 status."""
    import services.mailbox_api as mb
    real_build = mb.__dict__.get("build_controller", None)

    class _MockController:
        def __init__(self):
            self.verify = self
        def run(self, ctx):
            return {
                "status": status,
                "reasons": reasons or [f"mock reason for {status}"],
                "conflicts": [],
                "risk_score": 0.0,
                "gate_history": [],
                "checks": [],
            }
    # patch build_controller in bootstrap module (imported lazily inside endpoint)
    import bootstrap
    monkey = __import__("pytest").MonkeyPatch()
    monkey.setattr(bootstrap, "build_controller", lambda: _MockController())
    return monkey  # caller must .undo() or fixture cleanup


# ---------------- tests ----------------
def test_hitl_no_context_id(api_client, hitl_mailbox):
    """mail_id 没有 meta.json → ok=False, can_approve=False, reason='no context_id'."""
    _write_mail(hitl_mailbox._MAILBOX_DIR, "no_cid_mail", ctx_id=None)
    r = api_client.get("/v1/mail/no_cid_mail/context/hitl")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    assert d["can_approve"] is False
    assert "no context_id" in d["reason"].lower()


def test_hitl_context_file_missing(api_client, hitl_mailbox):
    """有 meta 但 context.json 缺 → ok=False, reason='context file missing'."""
    _write_mail(hitl_mailbox._MAILBOX_DIR, "missing_ctx_mail", ctx_id="RFQ-MISSING-12345")
    r = api_client.get("/v1/mail/missing_ctx_mail/context/hitl")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    assert d["can_approve"] is False
    assert "missing" in d["reason"].lower()


def test_hitl_pass_status_no_approve(api_client, hitl_mailbox):
    """PASS 状态 → locked=true 但 can_approve=false (仅 HITL 可批)."""
    import bootstrap
    class _C:
        def __init__(self): self.verify=self
        def run(self,ctx): return {"status":"PASS","reasons":[],"conflicts":[],"risk_score":0.0,"gate_history":[],"checks":[]}
    monkey = pytest.MonkeyPatch()
    monkey.setattr(bootstrap, "build_controller", lambda:_C())
    _write_mail(hitl_mailbox._MAILBOX_DIR, "pass_mail", ctx_id="RFQ-PASS-00001")
    _write_context(hitl_mailbox._CONTEXTS_DIR, "RFQ-PASS-00001")
    r = api_client.get("/v1/mail/pass_mail/context/hitl")
    d = r.json()
    assert d["ok"] is True
    assert d["locked"] is True
    assert d["can_approve"] is False  # status=PASS, not HITL
    assert d["verification_status"] == "PASS"
    assert len(d["quote_sha16"]) == 16
    assert d["quote_sha16"] == d["quote_sha16_locked"]
    monkey.undo()


def test_hitl_status_can_approve(api_client, hitl_mailbox):
    """HITL 状态 + 锁一致 → can_approve=true."""
    import bootstrap
    class _C:
        def __init__(self): self.verify=self
        def run(self,ctx): return {"status":"HITL","reasons":["VOICE_EMAIL_CONFLICT"],"conflicts":[],"risk_score":0.0,"gate_history":[],"checks":[]}
    monkey = pytest.MonkeyPatch()
    monkey.setattr(bootstrap, "build_controller", lambda:_C())
    _write_mail(hitl_mailbox._MAILBOX_DIR, "hitl_mail", ctx_id="RFQ-HITL-00002")
    _write_context(hitl_mailbox._CONTEXTS_DIR, "RFQ-HITL-00002")
    r = api_client.get("/v1/mail/hitl_mail/context/hitl")
    d = r.json()
    assert d["ok"] is True
    assert d["locked"] is True
    assert d["can_approve"] is True
    assert d["verification_status"] == "HITL"
    monkey.undo()


def test_hitl_quote_tampering_detected(api_client, hitl_mailbox, tmp_path):
    """篡改报价: 端点读 context 实时 quote, hash 与 draft 生成时锁的 hash 应不一致 → locked=false, can_approve=false."""
    import bootstrap
    # 1) 写一个 context 含真实 quote, 记下 sha16_locked 应该等于 quote_sha16
    class _C:
        def __init__(self): self.verify=self
        def run(self,ctx): return {"status":"HITL","reasons":["X"],"conflicts":[],"risk_score":0.0,"gate_history":[],"checks":[]}
    monkey = pytest.MonkeyPatch()
    monkey.setattr(bootstrap, "build_controller", lambda:_C())
    _write_mail(hitl_mailbox._MAILBOX_DIR, "tamper_mail", ctx_id="RFQ-TAMPER-00003")
    _write_context(hitl_mailbox._CONTEXTS_DIR, "RFQ-TAMPER-00003")
    # 第一次: 拿 locked hash
    r1 = api_client.get("/v1/mail/tamper_mail/context/hitl").json()
    locked_hash = r1["quote_sha16_locked"]
    # 2) 篡改 context: 把 unit_price 改成不同值, 模拟 LLM 改写
    ctx_path = hitl_mailbox._CONTEXTS_DIR / "RFQ-TAMPER-00003.json"
    ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
    ctx["commercial"]["quote"]["unit_price"] = 99999.0  # 篡改
    ctx_path.write_text(json.dumps(ctx, ensure_ascii=False), encoding="utf-8")
    # 第二次: 当前 quote_sha16 应与 locked 不同 → locked=false, can_approve=false
    r2 = api_client.get("/v1/mail/tamper_mail/context/hitl").json()
    assert r2["ok"] is True
    assert r2["locked"] is False
    assert r2["can_approve"] is False
    assert r2["quote_sha16"] != locked_hash
    # 端点仍报告 locked_hash (草稿生成时的快照) 不变
    assert r2["quote_sha16_locked"] == locked_hash
    monkey.undo()


def test_sha16_stability():
    """_sha16 对同输入输出稳定 hash (端点使用 sort_keys=True)."""
    from services.mailbox_api import _sha16
    payload = {"a":1,"b":2}
    h1 = _sha16(json.dumps(payload, sort_keys=True))
    h2 = _sha16(json.dumps(payload, sort_keys=True))
    assert h1 == h2
    assert len(h1) == 16
    # 顺序无关 (因 sort_keys=True)
    h3 = _sha16(json.dumps({"b":2,"a":1}, sort_keys=True))
    assert h3 == h1