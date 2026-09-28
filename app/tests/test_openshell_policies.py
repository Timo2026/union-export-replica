"""test_openshell_policies.py — OpenShell YAML 加载 + 铁律① + HITL + 路径沙箱."""
from __future__ import annotations

import copy

import pytest

from services import skill_config as sc
from services.openshell import (
    OpenShell, check_hitl, check_local_paths, check_skill_allowed,
    load_policies, sha256_obj,
)


@pytest.fixture
def policies():
    return load_policies()


def test_load_policies_all_present(policies):
    for pid in ("iron-rule-1", "hitl-required", "local-only", "skill-allowlist"):
        assert pid in policies
    assert policies["iron-rule-1"].get("locked") is True
    assert "calc_quote" in (policies["iron-rule-1"].get("applies_to") or [])
    assert "parse_rfq" in (policies["skill-allowlist"].get("allowed") or [])


def test_iron_rule_1_cannot_be_disabled_in_config(tmp_path):
    cfg = sc.default_config()
    cfg["openshell"]["iron-rule-1"]["enabled"] = False
    errs = sc.validate(cfg)
    assert any("iron-rule-1" in e for e in errs)
    with pytest.raises(ValueError):
        sc.save(cfg, path=tmp_path / "skills.yaml")


def test_save_forces_iron_rule_locked(tmp_path):
    cfg = sc.default_config()
    cfg["openshell"]["iron-rule-1"] = {"enabled": False, "locked": False}
    # validate 会先失败; 用合法配置再强制 locked
    cfg["openshell"]["iron-rule-1"] = {"enabled": True, "locked": False}
    # locked=false 也非法
    with pytest.raises(ValueError):
        sc.save(cfg, path=tmp_path / "skills.yaml")
    cfg["openshell"]["iron-rule-1"] = {"enabled": True, "locked": True}
    saved = sc.save(cfg, path=tmp_path / "skills.yaml")
    assert saved["openshell"]["iron-rule-1"]["locked"] is True
    assert saved["openshell"]["iron-rule-1"]["enabled"] is True


def test_skill_allowlist_blocks_unknown(policies):
    cfg = sc.default_config()
    ok, viols = check_skill_allowed("not_a_skill", policies, cfg)
    assert not ok
    assert viols and viols[0]["policy"] == "skill-allowlist"


def test_skill_allowlist_blocks_disabled(policies):
    cfg = sc.default_config()
    cfg["skills"] = {"calc_quote": {"enabled": False}}
    ok, viols = check_skill_allowed("calc_quote", policies, cfg)
    assert not ok


def test_local_only_blocks_outside_sandbox(policies):
    args = {"path": "C:/Windows/System32/evil.step"}
    viols = check_local_paths(args, policies, sc.default_config())
    assert viols
    assert viols[0]["policy"] == "local-only"


def test_local_only_allows_data_path(policies):
    args = {"path": "data/samples/bracket.step"}
    viols = check_local_paths(args, policies, sc.default_config())
    assert viols == []


def test_hitl_triggers_on_high_total(policies):
    out = {"quote_total_cny": 200000, "unit_price_cny": 100}
    hitl, reasons = check_hitl(out, policies, sc.default_config())
    assert hitl
    assert any(r["field"] == "quote_total_cny" for r in reasons)


def test_hitl_no_trigger_when_normal(policies):
    out = {"quote_total_cny": 5000, "unit_price_cny": 100, "risk_score": 0.2,
           "verification_status": "PASS", "dfm_valid": True}
    hitl, reasons = check_hitl(out, policies, sc.default_config())
    assert not hitl


def test_openshell_blocks_deterministic_override(policies):
    shell = OpenShell(cfg=sc.default_config(), policies=policies)
    original = {"unit_price": 100, "final_price": 5000, "ok": True}
    post = shell.postcheck("calc_quote", original, iron_rule="deterministic")
    assert post["ok"]
    assert post["iron_locked"]
    assert post["output_sha256"] == sha256_obj(original)
    tampered = dict(original)
    tampered["unit_price"] = 999999
    attempt = shell.attempt_override("calc_quote", tampered)
    assert not attempt["allowed"]
    assert attempt["violations"]


def test_openshell_status_lists_policies(policies):
    shell = OpenShell(cfg=sc.default_config(), policies=policies)
    st = shell.status()
    ids = {p["id"] for p in st["policies"]}
    assert {"iron-rule-1", "hitl-required", "local-only", "skill-allowlist"} <= ids
    iron = next(p for p in st["policies"] if p["id"] == "iron-rule-1")
    assert iron["locked"] is True
