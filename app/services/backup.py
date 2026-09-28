"""services/backup.py — D-P0.2 数据备份 (sqlite 在线一致备份 + retention).

用 sqlite3 在线 backup API (非裸文件 copy) → 即便源库正被写也得到一致快照。
输出 data/backups/<label>/<相对路径>, 附 manifest.json (size + sha256)。
retention 保留最近 N 份, 旧快照清理。

铁律①: 备份只在本机 data/ 下, 不外发; 凭据文件 (credentials.json 等) 不在备份范围
(只备份 *.sqlite3 数据库)。
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

DEFAULT_RETENTION = 5


def discover_databases(root: Path | str) -> List[Path]:
    """发现 root/data 下所有 *.sqlite3 (含子目录), 排除 backups/ 自身。"""
    root = Path(root)
    data_dir = root / "data"
    if not data_dir.exists():
        return []
    found: List[Path] = []
    for p in data_dir.rglob("*.sqlite3"):
        if not p.is_file():
            continue
        # 排除备份目录自身, 避免备份套娃
        try:
            if "backups" in p.relative_to(data_dir).parts:
                continue
        except ValueError:
            pass
        found.append(p)
    return sorted(found)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_database(src: Path, dest: Path) -> Dict[str, Any]:
    """在线一致备份单个 sqlite → dest。返回文件元信息。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(str(src))
    try:
        dst_conn = sqlite3.connect(str(dest))
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    return {
        "src": str(src),
        "dest": str(dest),
        "size": dest.stat().st_size,
        "sha256": _sha256(dest),
    }


def _default_label() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"


def run_backup(root: Path | str, dest_root: Optional[Path | str] = None,
               retention: int = DEFAULT_RETENTION,
               dbs: Optional[List[Path]] = None,
               label: Optional[str] = None) -> Dict[str, Any]:
    """备份 root/data 下数据库 (或显式 dbs) 到 dest_root/<label>/。

    Returns: {ok, backed_up, skipped, failed, files, manifest, snapshot}
    """
    root = Path(root)
    dest_root = Path(dest_root) if dest_root else (root / "data" / "backups")
    label = label or _default_label()
    snapshot = dest_root / label
    snapshot.mkdir(parents=True, exist_ok=True)

    sources = list(dbs) if dbs is not None else discover_databases(root)
    files: List[Dict[str, Any]] = []
    skipped = 0
    failed = 0
    for src in sources:
        src = Path(src)
        if not src.exists():
            skipped += 1
            log.warning("[backup] skip missing: %s", src)
            continue
        try:
            rel = src.relative_to(root)
        except ValueError:
            rel = Path(src.name)
        dest = snapshot / rel
        try:
            info = backup_database(src, dest)
            info["rel"] = str(rel)
            files.append(info)
        except Exception as e:
            failed += 1
            log.warning("[backup] failed %s: %r", src, e)

    manifest = {
        "label": label,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(root),
        "backed_up": len(files),
        "skipped": skipped,
        "failed": failed,
        "files": files,
    }
    manifest_path = snapshot / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    pruned = _prune(dest_root, retention)

    return {
        "ok": failed == 0,
        "backed_up": len(files),
        "skipped": skipped,
        "failed": failed,
        "files": files,
        "manifest": str(manifest_path),
        "snapshot": str(snapshot),
        "pruned": pruned,
    }


def _prune(dest_root: Path, retention: int) -> List[str]:
    """保留最近 retention 份快照, 删除更旧的。返回被删快照名。"""
    if retention <= 0:
        return []
    snaps = sorted([d for d in dest_root.iterdir() if d.is_dir()], key=lambda d: d.name)
    pruned: List[str] = []
    while len(snaps) > retention:
        old = snaps.pop(0)
        shutil.rmtree(old, ignore_errors=True)
        pruned.append(old.name)
    return pruned
