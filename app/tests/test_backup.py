"""tests/test_backup.py — D-P0.2 数据备份 (sqlite 在线一致备份 + retention).

覆盖:
  - 在线一致备份 (sqlite3 backup API, 非裸 copy) → 目标可打开且数据一致
  - manifest.json (含 size + sha256 + 源/目标路径)
  - retention 保留最近 N 份, 旧的清理
  - 缺失/非 sqlite 源 → 跳过不崩
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


def _make_db(path: Path, rows: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO t (v) VALUES (?)", (f"val-{i}",))
    conn.commit()
    conn.close()
    return path


def test_backup_creates_consistent_copy(tmp_path: Path):
    """备份后目标 sqlite 可打开且行数/内容一致。"""
    from services.backup import run_backup
    src = _make_db(tmp_path / "data" / "crm.sqlite3", rows=5)
    res = run_backup(root=tmp_path, dest_root=tmp_path / "data" / "backups",
                     dbs=[src], label="T1")
    assert res["ok"] is True
    assert res["backed_up"] == 1
    dest = Path(res["files"][0]["dest"])
    assert dest.exists()
    conn = sqlite3.connect(str(dest))
    n = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    vals = [r[0] for r in conn.execute("SELECT v FROM t ORDER BY id").fetchall()]
    conn.close()
    assert n == 5
    assert vals == [f"val-{i}" for i in range(5)]


def test_backup_manifest_written(tmp_path: Path):
    """manifest.json 含 size + sha256 + 源/目标。"""
    from services.backup import run_backup
    src = _make_db(tmp_path / "data" / "crm.sqlite3")
    res = run_backup(root=tmp_path, dest_root=tmp_path / "data" / "backups",
                     dbs=[src], label="T2")
    manifest_path = Path(res["manifest"])
    assert manifest_path.exists()
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m["label"] == "T2"
    assert len(m["files"]) == 1
    f0 = m["files"][0]
    assert f0["sha256"] and len(f0["sha256"]) == 64
    assert f0["size"] > 0
    assert f0["src"].endswith("crm.sqlite3")


def test_backup_retention_prunes_old(tmp_path: Path):
    """retention=2 → 第 3 次备份后只保留最近 2 份。"""
    from services.backup import run_backup
    src = _make_db(tmp_path / "data" / "crm.sqlite3")
    dest_root = tmp_path / "data" / "backups"
    for i in range(3):
        run_backup(root=tmp_path, dest_root=dest_root, dbs=[src],
                   retention=2, label=f"R{i}")
    snaps = sorted([d for d in dest_root.iterdir() if d.is_dir()])
    assert len(snaps) == 2, f"应只保留 2 份, 实得 {len(snaps)}: {[s.name for s in snaps]}"


def test_backup_skips_missing_source(tmp_path: Path):
    """源不存在 → 跳过, 不崩, ok 仍 True (无文件备份)。"""
    from services.backup import run_backup
    missing = tmp_path / "data" / "nope.sqlite3"
    res = run_backup(root=tmp_path, dest_root=tmp_path / "data" / "backups",
                     dbs=[missing], label="SKIP")
    assert res["ok"] is True
    assert res["backed_up"] == 0
    assert res["skipped"] >= 1


def test_discover_databases_finds_nested(tmp_path: Path):
    """discover 找到顶层 + crm_sandboxes 子目录的 sqlite。"""
    from services.backup import discover_databases
    _make_db(tmp_path / "data" / "crm.sqlite3")
    _make_db(tmp_path / "data" / "crm_sandboxes" / "CUST-A.sqlite3")
    (tmp_path / "data" / "notes.txt").write_text("ignore me", encoding="utf-8")
    found = discover_databases(tmp_path)
    names = {p.name for p in found}
    assert "crm.sqlite3" in names
    assert "CUST-A.sqlite3" in names
    assert "notes.txt" not in names
