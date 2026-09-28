"""tests/test_reid_os.py — T9: Reid-OS skill 包装 (3 用例).

覆盖:
  1. 工作路由: "客户投诉" → work 域 + COPC 协议
  2. 家庭路由: "孩子健康" → family 域 + FMH 协议
  3. 拉闸干预: "紧急不可逆" 触发 intervention 警告
  4. registry 注册
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "_test_reid_os_tool",
        ROOT / "skills" / "reid-os" / "tool.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tool = _load_tool()


class FakeCtx:
    def get_ctrl(self): return None


# ---- 1. 工作路由 ----
def test_work_routing_copc() -> None:
    """'客户投诉' → work 域 + COPC 协议."""
    r = tool.run(FakeCtx(), request="怎么处理好客户投诉?")
    assert r["ok"] is True
    assert r["skill"] == "reid-os"
    assert r["iron_rule"] == "llm_proposal"
    assert r["domain"] == "work"
    assert "COPC" in r["action"]
    assert r["intervention"] is None  # 无拉闸


def test_work_rfq() -> None:
    """'报价' 触发 RCF 协议."""
    r = tool.run(FakeCtx(), request="6061 报价")
    assert r["domain"] == "work"
    assert "RCF" in r["action"]


# ---- 2. 家庭路由 ----
def test_family_routing_fmh() -> None:
    """'孩子健康' → family 域 + FMH 协议."""
    r = tool.run(FakeCtx(), request="孩子最近健康不太好, 怎么办?")
    assert r["domain"] == "family"
    assert "FMH" in r["action"]


def test_family_relationship() -> None:
    """'配偶关系' → family + FRT 协议."""
    r = tool.run(FakeCtx(), request="配偶关系紧张")
    assert r["domain"] == "family"
    assert "FRT" in r["action"]


# ---- 3. 拉闸干预 ----
def test_intervention_danger_keyword() -> None:
    """'紧急不可逆' 触发 intervention 警告."""
    r = tool.run(FakeCtx(), request="紧急不可逆, 客户要撤资")
    assert r["intervention"] is not None
    assert "拉闸" in r["intervention"] or "warning" in r["intervention"].lower()


# ---- 4. 价值观校准 ----
def test_values_aligned_positive() -> None:
    """含 '共赢' '长期' 等正向词 → values_aligned=True."""
    r = tool.run(FakeCtx(), request="和客户达成长期共赢的合作")
    assert r["values_aligned"] is True


def test_values_aligned_negative() -> None:
    """无正向词 → values_aligned=False."""
    r = tool.run(FakeCtx(), request="客户着急要货")
    assert r["values_aligned"] is False


# ---- 5. registry 注册 ----
def test_reid_os_registered() -> None:
    import skills._runtime as rt
    skills = rt.discover()
    assert "reid_os" in skills
