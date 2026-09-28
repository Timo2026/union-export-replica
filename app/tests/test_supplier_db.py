"""test_supplier_db.py — v2.3.0 供应商样本库 + CRUD。

样本数据：8-10 家 CNC 加工厂，覆盖材料/工艺/地区/质量等级。
约束：schema 字段稳定，列表/筛选按 RFQ 标签打 tap。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from supplier_module.supplier_db import (
    init_suppliers_db,
    seed_default_suppliers,
    list_suppliers,
    get_supplier,
    filter_by_capability,
    DB_SCHEMA_VERSION,
)


def _fresh_db(tmp_path: Path) -> Path:
    db = tmp_path / "suppliers.sqlite3"
    init_suppliers_db(db)
    seed_default_suppliers(db)
    return db


def test_init_creates_table_with_expected_columns(tmp_path):
    db = _fresh_db(tmp_path)
    with sqlite3.connect(db) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(suppliers)").fetchall()]
    for col in ("id", "name", "region", "processes", "materials",
                "capacity_per_month", "lead_time_days", "quality_grade",
                "rating", "active"):
        assert col in cols, f"missing column: {col}"


def test_seed_loads_at_least_8_suppliers(tmp_path):
    db = _fresh_db(tmp_path)
    with sqlite3.connect(db) as c:
        n = c.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
    assert n >= 8


def test_seed_is_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    seed_default_suppliers(db)  # 再跑一次
    seed_default_suppliers(db)
    with sqlite3.connect(db) as c:
        n = c.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
    assert n >= 8  # 不应翻倍


def test_seed_covers_materials_and_processes(tmp_path):
    db = _fresh_db(tmp_path)
    with sqlite3.connect(db) as c:
        rows = c.execute(
            "SELECT DISTINCT materials FROM suppliers"
        ).fetchall()
        proc_rows = c.execute(
            "SELECT DISTINCT processes FROM suppliers"
        ).fetchall()
    all_mats = set()
    for (m,) in rows:
        all_mats.update([x.strip() for x in (m or "").split(",") if x.strip()])
    all_procs = set()
    for (p,) in proc_rows:
        all_procs.update([x.strip() for x in (p or "").split(",") if x.strip()])
    # 至少覆盖常见 CNC 材料
    for mat in ("6061", "304", "TC4", "45"):
        assert mat in all_mats, f"missing material seed: {mat}"
    # 至少覆盖常见工艺
    for proc in ("milling", "turning"):
        assert proc in all_procs, f"missing process seed: {proc}"


def test_list_suppliers_returns_active_only(tmp_path):
    db = _fresh_db(tmp_path)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE suppliers SET active = 0 WHERE id = 1")
    active = list_suppliers(db)
    assert all(s["active"] for s in active)


def test_get_supplier_by_id(tmp_path):
    db = _fresh_db(tmp_path)
    s = get_supplier(db, 1)
    assert s is not None
    assert s["id"] == 1
    assert isinstance(s["processes"], list)
    assert isinstance(s["materials"], list)


def test_get_supplier_missing_returns_none(tmp_path):
    db = _fresh_db(tmp_path)
    assert get_supplier(db, 99999) is None


def test_filter_by_capability_material_match(tmp_path):
    db = _fresh_db(tmp_path)
    matched = filter_by_capability(db, materials=["6061"], processes=None)
    assert len(matched) >= 1
    assert any("6061" in s["materials"] for s in matched)


def test_filter_by_capability_process_match(tmp_path):
    db = _fresh_db(tmp_path)
    matched = filter_by_capability(db, materials=None, processes=["milling"])
    assert len(matched) >= 1
    assert any("milling" in s["processes"] for s in matched)


def test_filter_by_capability_combined(tmp_path):
    db = _fresh_db(tmp_path)
    matched = filter_by_capability(
        db, materials=["TC4"], processes=["milling", "turning"]
    )
    # 至少有 TC4 + (milling or turning) 的供应商
    for s in matched:
        assert "TC4" in s["materials"]
        assert any(p in ("milling", "turning") for p in s["processes"])


def test_filter_by_capability_no_match(tmp_path):
    db = _fresh_db(tmp_path)
    matched = filter_by_capability(db, materials=["Unobtainium"], processes=None)
    assert matched == []


def test_schema_version_constant():
    assert isinstance(DB_SCHEMA_VERSION, str)
    assert DB_SCHEMA_VERSION.startswith("v")