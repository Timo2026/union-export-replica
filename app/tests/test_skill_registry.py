"""test_skill_registry.py — Agent Skills 注册表测试 (NVIDIA Agent Skills 风格 / 维度 1.2/2.1/2.2)."""
from __future__ import annotations

from services import skill_registry as sr
from services.guardrails import TOOL_ALLOWLIST


def test_discover_finds_four_skills():
    names = sr.names()
    for n in ("rfq-extraction", "cnc-quote", "dfm-conflict", "step-analysis"):
        assert n in names, f"缺技能 {n}"


def test_skill_has_standard_fields():
    for s in sr.discover():
        assert s.get("name") and s.get("description"), "SKILL.md 缺 name/description"
        assert s.get("tool_contract", {}).get("openai_function"), "缺 openai_function 工具契约"


def test_as_openai_tools_shape():
    tools = sr.as_openai_tools()
    assert len(tools) >= 4
    for t in tools:
        assert t["type"] == "function"
        fn = t["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"
    names = {t["function"]["name"] for t in tools}
    assert {"cnc_quote", "dfm_conflict", "rfq_extraction", "step_analysis"} <= names


def test_cnc_quote_function_has_material_enum():
    tools = {t["function"]["name"]: t["function"] for t in sr.as_openai_tools()}
    props = tools["cnc_quote"]["parameters"]["properties"]
    assert "6061" in props["material"]["enum"]
    assert "material" in tools["cnc_quote"]["parameters"]["required"]


def test_cross_check_allowlist_all_ok():
    r = sr.cross_check_allowlist(TOOL_ALLOWLIST)
    assert r["ok"] is True, f"技能不在 allow-list: {r['not_in_allowlist']}"


def test_summary_shape():
    s = sr.summary()
    assert s["count"] >= 4
    assert "openai_tools" in s and len(s["openai_tools"]) >= 4
    for sk in s["skills"]:
        assert sk["name"] and sk["version"]
