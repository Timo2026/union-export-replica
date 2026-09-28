"""supplier_db.py — v2.3.0 供应商样本库（SQLite）+ CRUD。

schema_version: v1.0
表：suppliers(id, name, region, processes CSV, materials CSV,
              capacity_per_month, lead_time_days, quality_grade,
              rating, contact_email, contact_phone, active)
种子：8-10 家 CNC 加工厂样本，覆盖材料/工艺/地区/质量等级。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_SCHEMA_VERSION = "v1.0"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  region TEXT NOT NULL,                 -- domestic / north_america / europe / asia / other
  processes TEXT NOT NULL DEFAULT '',   -- CSV: milling,turning,grinding,anodizing,heat_treatment
  materials TEXT NOT NULL DEFAULT '',   -- CSV: 6061,304,TC4,45,brass
  capacity_per_month INTEGER DEFAULT 100,
  lead_time_days INTEGER DEFAULT 14,
  quality_grade TEXT DEFAULT 'ISO9001', -- ISO9001 / AS9100 / IATF16949
  rating REAL DEFAULT 4.0,              -- 0..5
  contact_email TEXT DEFAULT '',
  contact_phone TEXT DEFAULT '',
  active INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_suppliers_active ON suppliers(active);
CREATE INDEX IF NOT EXISTS idx_suppliers_region ON suppliers(region);
"""


# 8-10 家样本：覆盖国内/亚洲/欧洲、材料 6061/304/TC4/45/黄铜、工艺铣/车/磨/阳极/热处理、
# 质量 ISO9001/AS9100/IATF16949、产能 30..500、交期 7..30 天、评分 3.5..4.9
_SEED_SUPPLIERS: List[Dict[str, Any]] = [
    {
        "name": "苏州精工 CNC 一厂",
        "region": "domestic",
        "processes": "milling,turning,grinding,anodizing",
        "materials": "6061,304,45",
        "capacity_per_month": 500,
        "lead_time_days": 10,
        "quality_grade": "ISO9001",
        "rating": 4.5,
        "contact_email": "sales@sz-jingong.cn",
        "contact_phone": "13900000001",
    },
    {
        "name": "深圳精密 CNC 二厂",
        "region": "domestic",
        "processes": "milling,turning,anodizing,heat_treatment",
        "materials": "6061,304,brass",
        "capacity_per_month": 400,
        "lead_time_days": 12,
        "quality_grade": "AS9100",
        "rating": 4.7,
        "contact_email": "quote@sz-precision.cn",
        "contact_phone": "13900000002",
    },
    {
        "name": "东莞钛合金 CNC 三厂",
        "region": "domestic",
        "processes": "milling,turning,grinding",
        "materials": "TC4,45",
        "capacity_per_month": 80,
        "lead_time_days": 25,
        "quality_grade": "AS9100",
        "rating": 4.9,
        "contact_email": "ti-alloy@dg-cnc.cn",
        "contact_phone": "13900000003",
    },
    {
        "name": "宁波不锈钢 CNC 四厂",
        "region": "domestic",
        "processes": "milling,turning,grinding,polishing",
        "materials": "304,316",
        "capacity_per_month": 300,
        "lead_time_days": 14,
        "quality_grade": "ISO9001",
        "rating": 4.3,
        "contact_email": "biz@nb-ss.cn",
        "contact_phone": "13900000004",
    },
    {
        "name": "青岛汽车件 CNC 五厂",
        "region": "domestic",
        "processes": "milling,turning,anodizing,heat_treatment",
        "materials": "6061,45",
        "capacity_per_month": 600,
        "lead_time_days": 9,
        "quality_grade": "IATF16949",
        "rating": 4.6,
        "contact_email": "auto@qd-cnc.cn",
        "contact_phone": "13900000005",
    },
    {
        "name": "Vietnam CNC Mfg Co.",
        "region": "asia",
        "processes": "milling,turning",
        "materials": "6061,304",
        "capacity_per_month": 200,
        "lead_time_days": 20,
        "quality_grade": "ISO9001",
        "rating": 4.0,
        "contact_email": "sales@vn-cnc.vn",
        "contact_phone": "+84-900-000-006",
    },
    {
        "name": "India Precision Works",
        "region": "asia",
        "processes": "milling,turning,anodizing",
        "materials": "6061,brass",
        "capacity_per_month": 250,
        "lead_time_days": 22,
        "quality_grade": "ISO9001",
        "rating": 3.8,
        "contact_email": "info@in-precision.in",
        "contact_phone": "+91-900-000-007",
    },
    {
        "name": "Germany Feinmechanik GmbH",
        "region": "europe",
        "processes": "milling,turning,grinding",
        "materials": "TC4,304,45",
        "capacity_per_month": 120,
        "lead_time_days": 28,
        "quality_grade": "AS9100",
        "rating": 4.8,
        "contact_email": "kontakt@feinmech.de",
        "contact_phone": "+49-30-0000-008",
    },
    {
        "name": "Mexico CNC Tier2 S.A.",
        "region": "north_america",
        "processes": "milling,turning,anodizing",
        "materials": "6061,304",
        "capacity_per_month": 350,
        "lead_time_days": 16,
        "quality_grade": "IATF16949",
        "rating": 4.2,
        "contact_email": "ventas@mx-cnc.mx",
        "contact_phone": "+52-55-0000-009",
    },
    {
        "name": "杭州小批量 CNC 十厂",
        "region": "domestic",
        "processes": "milling,turning",
        "materials": "6061,brass",
        "capacity_per_month": 80,
        "lead_time_days": 7,
        "quality_grade": "ISO9001",
        "rating": 4.1,
        "contact_email": "small-batch@hz-cnc.cn",
        "contact_phone": "13900000010",
    },
]


def init_suppliers_db(db_path: Path) -> None:
    """建表（已存在则 noop）。"""
    with sqlite3.connect(db_path) as c:
        c.executescript(_SCHEMA)
        c.commit()


def seed_default_suppliers(db_path: Path) -> None:
    """若表空则插入样本；存在则 noop（幂等）。"""
    with sqlite3.connect(db_path) as c:
        n = c.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
        if n > 0:
            return
        for s in _SEED_SUPPLIERS:
            c.execute(
                """INSERT INTO suppliers
                   (name, region, processes, materials,
                    capacity_per_month, lead_time_days, quality_grade,
                    rating, contact_email, contact_phone, active)
                   VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
                (
                    s["name"], s["region"], s["processes"], s["materials"],
                    s["capacity_per_month"], s["lead_time_days"], s["quality_grade"],
                    s["rating"], s["contact_email"], s["contact_phone"],
                ),
            )
        c.commit()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["processes"] = [x.strip() for x in (d.get("processes") or "").split(",") if x.strip()]
    d["materials"] = [x.strip() for x in (d.get("materials") or "").split(",") if x.strip()]
    d["active"] = bool(d.get("active"))
    return d


def list_suppliers(db_path: Path, active_only: bool = True) -> List[Dict[str, Any]]:
    with sqlite3.connect(db_path) as c:
        c.row_factory = sqlite3.Row
        if active_only:
            rows = c.execute(
                "SELECT * FROM suppliers WHERE active=1 ORDER BY rating DESC, id ASC"
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM suppliers ORDER BY rating DESC, id ASC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_supplier(db_path: Path, supplier_id: int) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(db_path) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    return _row_to_dict(row) if row else None


def filter_by_capability(
    db_path: Path,
    materials: Optional[List[str]] = None,
    processes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """标签筛选：任一材料命中 + 任一工艺命中。空筛选返回全部 active。"""
    suppliers = list_suppliers(db_path, active_only=True)
    out = []
    for s in suppliers:
        if materials and not any(m in s["materials"] for m in materials):
            continue
        if processes and not any(p in s["processes"] for p in processes):
            continue
        out.append(s)
    return out