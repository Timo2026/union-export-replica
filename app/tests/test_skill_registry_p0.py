"""test_skill_registry_p0.py — Skills P0 冒烟.

覆盖:
  - pack skills 均在 TOOL_ALLOWLIST
  - catalog/quarantined 不在 allowlist
  - skill_pack_adapter 不覆盖终价
  - crm list_customer_history postmortems 按 customer_id 过滤 (沙箱)
"""
from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def test_pack_skills_in_allowlist():
    from services.guardrails import TOOL_ALLOWLIST
    from adapters.skill_pack_adapter import allowed_pack_skill_ids
    ids = allowed_pack_skill_ids()
    assert ids, "skill_registry packs empty"
    for sid in ids:
        assert sid in TOOL_ALLOWLIST, f"{sid} missing in TOOL_ALLOWLIST"


def test_catalog_noise_not_in_allowlist():
    from services.guardrails import TOOL_ALLOWLIST
    for bad in ("apple", "1password", "suntime-stock-watchlist-manager",
                "catalog_only", "quarantined"):
        assert bad not in TOOL_ALLOWLIST


def test_pack_adapter_cannot_override_price():
    from adapters.skill_pack_adapter import run
    r = run(None, skill_id="unionskill-quote-bridge", unit_price=999, final_price=1)
    assert r.get("cannot_override_price") is True
    payload = r.get("payload") or {}
    assert "unit_price" not in payload
    assert "final_price" not in payload
    assert r.get("_source", "").startswith("skill_pack:")


def test_pack_adapter_denies_unknown():
    from adapters.skill_pack_adapter import run
    r = run(None, skill_id="not-a-real-skill")
    assert r.get("ok") is False
    assert r.get("role") == "denied"


def test_skill_registry_yaml_loads():
    from adapters.skill_pack_adapter import load_registry, allowed_pack_skill_ids
    reg = load_registry()
    assert reg.get("version") == 1
    assert reg.get("policy", {}).get("catalog_never_executable") is True
    assert "knowledge-index-lookup" in allowed_pack_skill_ids()


def test_crm_history_postmortems_filtered_by_customer():
    import tempfile
    from services.crm_memory import CRMMemory
    td = tempfile.mkdtemp()
    try:
        db = str(Path(td) / "crm.sqlite3")
        crm = CRMMemory(db)
        crm.upsert_customer({"customer_id": "CUST-A", "name": "A"})
        crm.upsert_customer({"customer_id": "CUST-B", "name": "B"})
        crm.write_rfq({"context_id": "RFQ-A1", "customer_id": "CUST-A",
                       "rfq": {"customer": {"customer_id": "CUST-A"},
                               "material": "6061", "quantity": 1},
                       "state": "DONE"})
        crm.write_rfq({"context_id": "RFQ-B1", "customer_id": "CUST-B",
                       "rfq": {"customer": {"customer_id": "CUST-B"},
                               "material": "304", "quantity": 1},
                       "state": "DONE"})
        crm.write_quote({"context_id": "RFQ-A1", "commercial": {"quote": {"unit_price": 10, "final_price": 100}}},
                        {"status": "PASS"}, {"subject": "qA"})
        crm.write_quote({"context_id": "RFQ-B1", "commercial": {"quote": {"unit_price": 20, "final_price": 200}}},
                        {"status": "PASS"}, {"subject": "qB"})
        crm.postmortem("RFQ-A1", "won", 90.0, "A only")
        crm.postmortem("RFQ-B1", "lost", 30.0, "B only")
        hist_a = crm.list_customer_history("CUST-A")
        hist_b = crm.list_customer_history("CUST-B")
        notes_a = [p.get("note") for p in hist_a.get("postmortems", [])]
        notes_b = [p.get("note") for p in hist_b.get("postmortems", [])]
        assert "A only" in notes_a
        assert "B only" not in notes_a
        assert "B only" in notes_b
        assert "A only" not in notes_b
        crm.close()
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


def test_quote_calibration_record_and_adjust():
    import tempfile
    from services.crm_memory import CRMMemory
    from services.quote_calibration import QuoteCalibration
    td = tempfile.mkdtemp()
    try:
        crm = CRMMemory(str(Path(td) / "crm.sqlite3"))
        cal = QuoteCalibration(crm)
        for i in range(3):
            cal.record_outcome(
                context_id=f"RFQ-X{i}", customer_id="CUST-X",
                material="6061", surface="anodizing", quantity=10,
                quoted_unit_price=10.0, actual_unit_cost=12.0,
                outcome="won")
        adj = cal.get_adjustments("CUST-X", material="6061")
        assert adj.get("sample_count", 0) >= 3
        assert adj.get("bias_pct", 0) > 0
        assert adj.get("confidence", 0) > 0
        assert adj.get("cannot_override_price") is True
        crm.close()
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


def test_flywheel_before_run_new_customer():
    import tempfile
    from services.crm_memory import CRMMemory
    from services.customer_health import CustomerHealthEngine
    from services.quote_calibration import QuoteCalibration
    from services.customer_flywheel import CustomerFlywheel
    td = tempfile.mkdtemp()
    try:
        crm = CRMMemory(str(Path(td) / "crm.sqlite3"))
        health = CustomerHealthEngine(crm)
        fw = CustomerFlywheel(crm, health, QuoteCalibration(crm))
        state = fw.before_run({"customer_id": "CUST-NEW", "name": "New Co"})
        assert isinstance(state, dict)
        assert state.get("customer_id") == "CUST-NEW" or state.get("_new_customer") is True
        crm.close()
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)
