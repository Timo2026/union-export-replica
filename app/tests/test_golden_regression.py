"""test_golden_regression.py — 冻结验收集 S1-S5 + M1 结构回归.

对齐 ARCHITECTURE.md 第 19 节 Acceptance criteria:
  S1 6061x50 + anodizing  → DONE / PASS
  S2 TC4 x10              → DONE / PASS
  S3 304 + anodizing      → BLOCKED
  S4 304 + passivation    → DONE / PASS
  S5 TC4 + IT5            → HITL
  M1 Email±0.02 + Voice0.05 → HITL / VOICE_EMAIL_CONFLICT

外加结构性验收: context_id 唯一 / 无非法状态转移 / 审计链可验证 /
报价可溯源到确定性引擎 / 外部邮件不自动发送。

真实内核: 在线命中 :7862, 否则离线 import 真实 calc_quote+ConflictChecker (byte-identical)。
本测试是**结构回归**, 不断言具体价格数字 (在线/离线可能有细微差异)。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bootstrap import build_controller
from services.rfq_state_machine import IllegalTransition, RFQStateMachine

_ROOT = Path(__file__).resolve().parent.parent
_SCEN = json.loads((_ROOT / "data" / "golden_scenarios.json").read_text(encoding="utf-8"))["scenarios"]


@pytest.fixture(scope="module")
def ctrl(require_engine):
    c = build_controller()
    yield c
    if c.crm is not None:
        c.crm.close()


def _run(ctrl, sc):
    return ctrl.run(
        email_text=sc["email"],
        customer=sc.get("customer"),
        voice_transcript=sc.get("voice_transcript"),
    )


@pytest.mark.parametrize("sc", _SCEN, ids=[s["id"] for s in _SCEN])
def test_golden_scenario(ctrl, sc):
    r = _run(ctrl, sc)
    # context_id 唯一且规范
    assert r["context_id"].startswith("RFQ-")
    # 审计链必须可验证 (tamper-evident)
    assert r["audit_valid"] is True
    # 状态与验收状态一致
    assert r["state"] == sc["expect_state"], f'{sc["id"]} state {r["state"]} != {sc["expect_state"]}: {r["reasons"]}'
    assert r["verification_status"] == sc["expect_status"]
    # 外部邮件永不自动发送
    assert r["reply"]["auto_send"] is False
    # 报价/DFM 可溯源到确定性引擎
    assert ("live:" in r["engine_source"]) or ("offline:" in r["engine_source"])
    # M1: 必须surface语音冲突
    if sc.get("expect_conflict"):
        assert sc["expect_conflict"] in r["multimodal_conflicts"]


def test_s3_blocked_has_conflict_and_alternative(ctrl):
    sc = next(s for s in _SCEN if s["id"] == "S3")
    r = _run(ctrl, sc)
    assert r["dfm"]["valid"] is False
    assert any("阳极氧化" in c for c in r["dfm"]["conflicts"])
    assert r["state"] == "ARCHIVED"


def test_s5_hitl_reason_is_precision(ctrl):
    sc = next(s for s in _SCEN if s["id"] == "S5")
    r = _run(ctrl, sc)
    assert r["state"] == "HITL"
    assert any("IT5" in x or "精密" in x for x in r["reasons"])


def test_m1_conflict_surfaces_not_silent(ctrl):
    sc = next(s for s in _SCEN if s["id"] == "M1")
    r = _run(ctrl, sc)
    assert "VOICE_EMAIL_CONFLICT" in r["multimodal_conflicts"]
    assert r["verification_status"] == "HITL"
    assert any("多模态" in x or "VOICE" in x for x in r["reasons"])


def test_done_scenarios_have_traceable_quote(ctrl):
    for sid in ("S1", "S4"):
        sc = next(s for s in _SCEN if s["id"] == sid)
        r = _run(ctrl, sc)
        assert r["state"] == "DONE"
        assert r["quote"].get("unit_price") is not None
        assert r["quote"].get("_source", "").startswith(("live:", "offline:"))


# ---------- P0 driver 标记 (方案 D): 真控制器必须接受 driver kwarg ----------
# 回归背景: orchestrator 传 driver= 给 cat.run(), 早期 cat.run() 无此参数,
# MockCAT 的 **kwargs 掩盖了生产 TypeError — 这里用真控制器钉死.
def test_run_accepts_driver_kwarg_and_returns_it(ctrl):
    sc = next(s for s in _SCEN if s["id"] == "S1")
    r = ctrl.run(email_text=sc["email"], customer=sc.get("customer"), driver="agent")
    assert r["driver"] == "agent"


def test_run_driver_defaults_email(ctrl):
    sc = next(s for s in _SCEN if s["id"] == "S1")
    r = _run(ctrl, sc)  # 不传 driver
    assert r["driver"] == "email"


# ---------- 结构性单元测试 ----------
def test_state_machine_blocks_illegal_transition():
    sm = RFQStateMachine("RFQ-TEST")
    with pytest.raises(IllegalTransition):
        sm.transition("DONE")          # NEW -> DONE 非法
    with pytest.raises(IllegalTransition):
        sm.transition("QUOTING")       # NEW -> QUOTING 非法
    sm.transition("INTAKE")
    assert sm.state == "INTAKE"


def test_state_machine_legal_golden_path():
    sm = RFQStateMachine("RFQ-OK")
    for st in ["INTAKE", "STRUCTURING", "DFM", "QUOTING", "VERIFY", "REPLY", "CRM_MEM", "DONE"]:
        sm.transition(st)
    assert sm.is_terminal and sm.state == "DONE"


def test_context_ids_unique(ctrl):
    ids = set()
    for sc in _SCEN:
        ids.add(_run(ctrl, sc)["context_id"])
    assert len(ids) == len(_SCEN)
