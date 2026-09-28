"""test_agent_spec.py — agent.yaml (nemo-agents-spec-v1) 加载与自洽校验."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from services.agent_spec import load_agent_spec, validate

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def spec():
    return load_agent_spec(_ROOT)


def test_agent_yaml_loads(spec):
    assert spec["kind"] == "Agent"
    assert spec["apiVersion"].startswith("nemo.agents/")


def test_agent_spec_is_valid(spec):
    r = validate(spec)
    assert r["valid"] is True, r["errors"]
    assert r["errors"] == []


def test_spec_covers_model_mesh_roles(spec):
    roles = set(spec["spec"]["models"]["roles"].keys())
    assert {"FAST", "VISION", "REASON", "EMBED", "ASR", "DETERMINISTIC"}.issubset(roles)


def test_spec_deterministic_points_to_timo(spec):
    det = spec["spec"]["models"]["roles"]["DETERMINISTIC"]
    assert det["backend"] == "timo-kernel"


def test_spec_tools_within_allowlist(spec):
    from services.guardrails import TOOL_ALLOWLIST
    names = {t["name"] for t in spec["spec"]["tools"]}
    assert names.issubset(TOOL_ALLOWLIST)
    assert "cnc-quote" in names and "freight-customs" in names


def test_spec_memory_five_layers(spec):
    mem = set(spec["spec"]["memory"].keys())
    assert {"working", "fact", "semantic", "artifact", "episodic"}.issubset(mem)


def test_spec_guardrails_three_stages(spec):
    gr = spec["spec"]["guardrails"]
    assert {"input", "tool", "output"}.issubset(gr.keys())


def test_spec_external_send_draft_only(spec):
    assert spec["spec"]["security"]["external_send"]["default"] == "draft_only"


def test_spec_deployment_profiles(spec):
    assert set(spec["spec"]["deployment"]["profiles"]) == {"A", "B", "C", "D"}


# ---- 负例: 破坏契约应被校验器抓出 ----
def test_validate_catches_missing_tool(spec):
    bad = copy.deepcopy(spec)
    bad["spec"]["tools"] = [{"name": "not-in-allowlist"}]
    r = validate(bad)
    assert r["valid"] is False
    assert any("allow-list" in e for e in r["errors"])


def test_validate_catches_missing_memory_layer(spec):
    bad = copy.deepcopy(spec)
    del bad["spec"]["memory"]["episodic"]
    assert validate(bad)["valid"] is False


def test_validate_catches_bad_profile(spec):
    bad = copy.deepcopy(spec)
    bad["spec"]["deployment"]["profiles"] = ["A", "Z"]
    assert validate(bad)["valid"] is False
