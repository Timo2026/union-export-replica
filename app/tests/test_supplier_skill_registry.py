"""test_supplier_skill_registry.py — v2.3.0 supplier-match Skill 注册 + 交叉校验。

契约：SKILL.md 解析后名字在 TOOL_ALLOWLIST 中；emit 的 function-calling 参数结构合法。
"""
from __future__ import annotations

import pytest

from services.skill_registry import discover, as_openai_tools, cross_check_allowlist
from services.guardrails import TOOL_ALLOWLIST


def test_supplier_match_skill_discovered():
    skills = discover()
    names = [s["name"] for s in skills]
    assert "supplier-match" in names


def test_supplier_match_emits_openai_tool():
    skills = discover()
    s = next(x for x in skills if x["name"] == "supplier-match")
    contract = (s.get("tool_contract") or {}).get("openai_function")
    assert contract is not None
    assert contract["name"] == "supplier_match"
    params = contract["parameters"]
    assert params["type"] == "object"
    assert "rfq" in params["properties"]
    assert "rfq" in params["required"]


def test_supplier_match_in_allowlist():
    assert "supplier-match" in TOOL_ALLOWLIST


def test_cross_check_allowlist_passes():
    result = cross_check_allowlist(set(TOOL_ALLOWLIST))
    assert result["ok"] is True, f"missing from allowlist: {result['not_in_allowlist']}"


def test_as_openai_tools_includes_supplier_match():
    tools = as_openai_tools()
    names = [t["function"]["name"] for t in tools]
    assert "supplier_match" in names


def test_skill_count_increased():
    """v2.2.0 有 4 个 skill，v2.3.0 应 ≥ 5。"""
    skills = discover()
    assert len(skills) >= 5