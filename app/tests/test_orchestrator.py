"""tests/test_orchestrator.py — T6: Orchestrator skill 接入 dispatcher (5 用例).

覆盖:
  1. 指定 workflow_name → 加载 yaml / 默认 workflow
  2. 关键词 "报价+轴套" → keyword_plan → fleet_coordinator shape=bushing
  3. 关键词 "黄金链" → load_workflow('flange_quote')
  4. orchestrator 不直接调 skill, 仅返 plan
  5. orchestrator 被 skills/_runtime discover 注册
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "_test_orchestrator_tool",
        ROOT / "skills" / "orchestrator" / "tool.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tool = _load_tool()


class FakeCtx:
    def get_ctrl(self): return None


# ---- 1. 指定 workflow_name ----
def test_workflow_name_flange_quote() -> None:
    r = tool.run(FakeCtx(), request="6061 法兰 1200 件 报价",
                  workflow_name="flange_quote")
    assert r["ok"] is True
    assert r["source"] == "workflow"
    assert r["skill_sequence"][0] == "parse_rfq"
    assert "fleet_coordinator" in r["skill_sequence"]
    assert r["plan_count"] >= 5


def test_workflow_name_shaft_sleeve() -> None:
    r = tool.run(FakeCtx(), request="轴套", workflow_name="shaft_sleeve_quote")
    assert r["ok"] is True
    assert "fleet_coordinator" in r["skill_sequence"]
    assert r["source"] == "workflow"


# ---- 2. 关键词 routing ----
def test_keyword_axis_sleeve_plan() -> None:
    r = tool.run(FakeCtx(), request="请帮我报一下 6061 轴套 50 件")
    assert r["ok"] is True
    assert r["source"] == "keyword"
    # 含 parse_rfq (邮件) + fleet_coordinator (轴套→bushing) + quality_loop
    skills = r["skill_sequence"]
    assert "fleet_coordinator" in skills
    # 检查 fleet_coordinator args 是否含 shape=bushing
    fc_step = next(s for s in r["plan"] if s["skill"] == "fleet_coordinator")
    assert fc_step["args"].get("shape") == "bushing"


def test_keyword_golden_chain_loads_flange_quote() -> None:
    r = tool.run(FakeCtx(), request="请跑黄金链端到端报价")
    # "黄金链" 触发 load_workflow('flange_quote'), plan 应 ≥ 5 步
    assert r["plan_count"] >= 5
    assert r["skill_sequence"][0] == "parse_rfq"


# ---- 3. 不直接调 skill, 仅返 plan ----
def test_no_direct_skill_call_only_plan() -> None:
    """orchestrator.run() 应只返 plan, 不执行 (plan_count >=1, plan 含 skill+args)."""
    r = tool.run(FakeCtx(), request="轴套 50件")
    assert "plan" in r
    assert all("skill" in step and "args" in step for step in r["plan"])
    assert "skill_sequence" in r
    # 关键: orchestrator 自己不应被包含在 plan 里 (防止无限递归)
    assert "orchestrator" not in r["skill_sequence"]


# ---- 4. empty request 报错 ----
def test_empty_request_error() -> None:
    r = tool.run(FakeCtx(), request="")
    assert r["ok"] is False
    assert "request required" in r["error"]


# ---- 5. registry 注册 ----
def test_orchestrator_registered_in_runtime() -> None:
    import skills._runtime as rt
    skills = rt.discover()
    assert "orchestrator" in skills
