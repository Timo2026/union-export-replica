"""scripts/backup.py — D-P0.2 数据备份 CLI.

用法:
    python scripts/backup.py                 # 备份 data/ 下所有 sqlite, 保留最近 5 份
    python scripts/backup.py --retention 10  # 自定义保留份数
    python scripts/backup.py --label pre-release
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.backup import run_backup, DEFAULT_RETENTION


def main() -> int:
    ap = argparse.ArgumentParser(description="Backup data/ sqlite databases (online-consistent).")
    ap.add_argument("--retention", type=int, default=DEFAULT_RETENTION)
    ap.add_argument("--dest", default=None, help="backup dest root (default: data/backups)")
    ap.add_argument("--label", default=None, help="snapshot label (default: timestamp)")
    args = ap.parse_args()

    res = run_backup(root=_ROOT, dest_root=args.dest, retention=args.retention, label=args.label)
    print("================ BACKUP RESULT ================")
    print(f"  snapshot   : {res['snapshot']}")
    print(f"  backed_up  : {res['backed_up']}")
    print(f"  skipped    : {res['skipped']}")
    print(f"  failed     : {res['failed']}")
    print(f"  pruned     : {res['pruned']}")
    print(f"  manifest   : {res['manifest']}")
    print("===============================================")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
