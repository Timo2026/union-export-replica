"""scripts/export_demo.py — 干净离线演示包导出 (Track C).

把源仓库的白名单代码 + 离线 demo 产物镜像到目标目录
(默认 data/exports/union-export-demo, 可用 --dest 或 UEA_DEMO_DIR 覆盖),
硬排除一切敏感/瞬时文件 (铁律①: 凭据永不离机; 测试沙箱/审计日志不入库)。

用法:
    python scripts/export_demo.py            # 导出
    python scripts/export_demo.py --dry-run  # 只报告将做什么, 不写盘
    python scripts/export_demo.py --dest /tmp/pkg

退出码 0 = 导出成功且自检无泄漏; 非 0 = 自检发现敏感文件 (拒绝完成)。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent


def _dst(cli_dest: str = "") -> Path:
    """导出目标: --dest > UEA_DEMO_DIR > data/exports/union-export-demo."""
    if cli_dest:
        return Path(cli_dest)
    env = os.environ.get("UEA_DEMO_DIR")
    if env:
        return Path(env)
    return _ROOT / "data" / "exports" / "union-export-demo"


# 顶层代码目录/文件白名单 (整目录镜像)
CODE_DIRS = [
    "adapters", "agents", "config", "css", "js", "openshell",
    "policies", "schemas", "scripts", "services", "skills", "webui",
    "tests", "evaluation", "supplier_module", "skill_catalog", "skill_packs",
    "docs",
]
CODE_FILES = ["bootstrap.py", "requirements.txt", "index.html", "LICENSE", "README.md"]

# data/ 白名单 (相对 data/ 的路径) — 仅离线 demo 必需, 绝不含凭据/数据库
DATA_WHITELIST_FILES = [
    "golden_scenarios.json",
    "eval_set.json",
    "demo/demo_result.json",
]
DATA_WHITELIST_DIRS = ["samples", "golden_core"]

# flywheel demo 产物: 只要 .json/.md, 排除 .sqlite3
FLYWHEEL_DEMO_EXT = {".json", ".md"}

# copytree 忽略模式 — 第一道防线
IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", "*.sqlite3", "*.sqlite3-*",
    ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "credentials.json", "gmail_settings.json", "skill_audit.jsonl",
    "*.log", ".env", "*.pem", "*.key",
)

# 自检: 导出后若发现这些文件名/后缀 → 判定泄漏, 拒绝完成
FORBIDDEN_NAMES = {"credentials.json", "gmail_settings.json", "skill_audit.jsonl"}
FORBIDDEN_SUFFIXES = {".sqlite3", ".pem", ".key"}


def _rmtree(p: Path, dry: bool) -> None:
    if p.exists():
        if dry:
            print(f"  [dry] rm -r {p}")
        else:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)


def _copytree(src: Path, dst: Path, dry: bool) -> None:
    if not src.exists():
        return
    _rmtree(dst, dry)
    if dry:
        print(f"  [dry] cp -r {src.name}/ -> {dst.parent.name}/{dst.name}/")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, ignore=IGNORE, dirs_exist_ok=True)


def _copyfile(src: Path, dst: Path, dry: bool) -> None:
    if not src.exists():
        return
    if dry:
        print(f"  [dry] cp {src.name}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def export(dry: bool = False, dest: Optional[Path] = None) -> int:
    dst = Path(dest) if dest else _dst()
    print(f"SRC = {_ROOT}")
    print(f"dst = {dst}")
    if not dry:
        dst.mkdir(parents=True, exist_ok=True)

    print("\n[1/4] 镜像代码白名单 ...")
    for d in CODE_DIRS:
        _copytree(_ROOT / d, dst / d, dry)
    for f in CODE_FILES:
        _copyfile(_ROOT / f, dst / f, dry)

    print("[2/4] 镜像 data/ 白名单 (排除凭据/数据库/审计) ...")
    _rmtree(dst / "data", dry)  # 清空旧 data, 杜绝 contexts/traces/sqlite 残留
    for rel in DATA_WHITELIST_FILES:
        _copyfile(_ROOT / "data" / rel, dst / "data" / rel, dry)
    for rel in DATA_WHITELIST_DIRS:
        _copytree(_ROOT / "data" / rel, dst / "data" / rel, dry)
    # flywheel demo: 只要 .json/.md
    fw_src = _ROOT / "data" / "flywheel_demo"
    if fw_src.exists():
        for fp in fw_src.iterdir():
            if fp.is_file() and fp.suffix in FLYWHEEL_DEMO_EXT:
                _copyfile(fp, dst / "data" / "flywheel_demo" / fp.name, dry)

    print("[3/4] 清理导出包内任何残留敏感/瞬时文件 ...")
    if not dry and dst.exists():
        for p in list(dst.rglob("*")):
            if p.is_file() and (p.name in FORBIDDEN_NAMES or p.suffix in FORBIDDEN_SUFFIXES):
                p.unlink(missing_ok=True)
                print(f"  removed leaked: {p.relative_to(dst)}")
        for pc in dst.rglob("__pycache__"):
            shutil.rmtree(pc, ignore_errors=True)

    print("[4/4] 自检 (拒绝任何泄漏) ...")
    leaks: list[str] = []
    if not dry and dst.exists():
        for p in dst.rglob("*"):
            if p.is_file() and (p.name in FORBIDDEN_NAMES or p.suffix in FORBIDDEN_SUFFIXES):
                leaks.append(str(p.relative_to(dst)))
    if leaks:
        print("  ❌ 自检失败, 发现敏感文件泄漏:")
        for l in leaks:
            print(f"     - {l}")
        return 2

    # 统计
    n_py = len(list(dst.rglob("*.py"))) if not dry and dst.exists() else 0
    n_skills = len([d for d in (dst / "skills").glob("*/")]) if not dry and (dst / "skills").exists() else 0
    has_fw_pkg = (dst / "services" / "flywheel" / "__init__.py").exists() if not dry else False
    fw_skills = [s for s in ("customer-flywheel", "customer-health", "quote-calibration", "retention-alert")
                 if (dst / "skills" / s).exists()] if not dry else []

    if not dry:
        print("\n================ EXPORT SELF-CHECK PASS ================")
        print(f"  .py files       : {n_py}")
        print(f"  skills folders  : {n_skills}")
        print(f"  v6.2 flywheel   : {'[OK] services/flywheel/' if has_fw_pkg else '[MISS] absent'}")
        print(f"  flywheel skills : {len(fw_skills)}/4 {fw_skills}")
        print(f"  sensitive leaks : 0 (credentials/gmail_settings/sqlite3/key excluded)")
        print("=======================================================")
    else:
        print("\n[dry-run] 未写盘。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="干净离线演示包导出")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dest", default="",
                    help="导出目标目录 (默认 $UEA_DEMO_DIR 或 data/exports/union-export-demo)")
    args = ap.parse_args()
    return export(dry=args.dry_run, dest=Path(args.dest) if args.dest else None)


if __name__ == "__main__":
    sys.exit(main())
