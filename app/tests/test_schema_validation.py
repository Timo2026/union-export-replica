"""test_schema_validation.py — 运行时 JSON-Schema 校验 (维度 6.2: schema mismatch → fail fast)."""
from __future__ import annotations

import pytest

from services import schema_validator as sv


def test_valid_rfq_passes():
    r = sv.validate_rfq({"material": "6061", "quantity": 50, "process": "CNC",
                         "surface": "阳极氧化", "tolerance_grade": "IT7"})
    assert r["valid"] is True and r["errors"] == []


def test_rfq_missing_required_flagged():
    r = sv.validate_rfq({"process": "CNC"})          # 缺 material/quantity
    assert r["valid"] is False
    assert any("material" in e for e in r["errors"])


def test_rfq_bad_tolerance_enum():
    r = sv.validate_rfq({"material": "6061", "quantity": 10, "process": "CNC",
                         "tolerance_grade": "IT99"})
    assert r["valid"] is False                       # 不在 IT4..IT10 枚举


def test_strict_raises():
    with pytest.raises(sv.SchemaValidationError):
        sv.validate_rfq({"process": "CNC"}, strict=True)


def test_quote_valid_and_invalid():
    assert sv.validate_quote({"unit_price": 222.8, "final_price": 9413.3, "quantity": 50})["valid"]
    bad = sv.validate_quote({"unit_price": -5})
    assert bad["valid"] is False
    assert sv.validate_quote(None)["valid"] is True    # 无报价(BLOCKED)不算违规


def test_context_validation():
    ctx = {"context_id": "RFQ-20260917-ABC123", "state": "DONE",
           "evidence": [{"evidence_id": "EV-1", "source_type": "email", "checksum": "sha256:abc"}]}
    r = sv.validate_context(ctx)
    assert r["valid"] is True


def test_context_bad_state_enum():
    r = sv.validate_context({"context_id": "RFQ-x", "state": "FLYING"})
    assert r["valid"] is False


def test_engine_is_jsonschema_when_available():
    r = sv.validate_rfq({"material": "6061", "quantity": 1, "process": "CNC"})
    assert r["engine"] in ("jsonschema", "light")
