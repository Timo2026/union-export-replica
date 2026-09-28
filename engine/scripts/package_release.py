#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交付包打包脚本。

生成干净的交付包 CNC-AI-Brain-v12.0.0-fusion.zip，排除 .git/__pycache__/.bak/
output 临时产物/node_modules/.venv 等不需要的文件。

使用 Python zipfile 模块打包（正确处理中文文件名）。

用法:
    python scripts/package_release.py

输出:
    ../CNC-AI-Brain-v12.0.0-fusion.zip
    zip 内部以 Timo_CNC-AI-Brain-v12.0-Fusion/ 为根目录。
"""

from __future__ import annotations

import os
import sys
import zipfile
import fnmatch
from pathlib import Path

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# 项目根目录（本脚本位于 scripts/ 下）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# zip 内部根目录名
ZIP_ROOT_DIR = "Timo_CNC-AI-Brain-v12.0-Fusion"

# 输出 zip 路径（项目父目录）
OUTPUT_ZIP = PROJECT_ROOT.parent / "CNC-AI-Brain-v12.0.0-fusion.zip"

# ---------------------------------------------------------------------------
# 排除规则
# ---------------------------------------------------------------------------

# 任意层级中需要排除的目录名（匹配目录名，任意层级）
EXCLUDE_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".venv",
    "node_modules",
    ".pytest_cache",       # Python 测试缓存（同 __pycache__ 性质）
    # IDE / 工具生成的临时目录（.gitignore 中已声明），不属于交付内容
    ".arts",
    ".codeartsdoer",
    ".codegraph",
    ".function-router",
    # 注意: _skill_extract/ 被 git 跟踪，是项目技能知识库，必须保留
    "logs",                # .gitignore: logs/  运行时日志
}

# 需要排除的根级相对路径（目录或文件）
EXCLUDE_RELATIVE_PATHS = {
    ".merkle-snapshot.json",
    "PPT交付",
    # data/ 下的运行时业务数据（.gitignore 中已声明）
    "data/batch_quote_test2",   # 任务明确排除（测试数据）
    "data/exports",             # 任务 + .gitignore 排除（导出临时 zip）
    "data/uploads",             # .gitignore: 运行时上传
    "data/step",                # .gitignore: 运行时 STEP
    "data/stl",                 # .gitignore: 运行时 STL
    "data/jiewo",               # .gitignore: 客户业务数据
    "data/batch_quote",         # .gitignore: 批量报价运行时数据
    "start_server.py",
    "scripts/verify_start_server.py",
    "config/pricing_direct.json",
    "完整使用说明书.md",
    "docs/交付教程.md",
    "src/runtime/drawing_parser.py",
}

# 需要排除的文件扩展名
EXCLUDE_EXTENSIONS = {
    ".bak",
    ".pyc",
    ".step",   # .gitignore: 运行时 STEP 文件
    ".stl",    # .gitignore: 运行时 STL 文件
    ".log",    # .gitignore: 日志文件
    ".db",     # .gitignore: 运行时数据库（audit.db / orders.db）
}

# 需要排除的文件名模式（glob 风格前缀/后缀匹配）
EXCLUDE_NAME_PATTERNS = {
    # .gitignore: tmp_*.json
    "tmp_*.json",
    # .gitignore: chat_req.json / chat_resp*.json
    "chat_req.json",
    "chat_resp*.json",
}

# output/ 目录下只保留这些文件，其余全部排除
OUTPUT_KEEP_FILES = {
    "门禁回归报告.md",
    "最终整体验证报告.md",
    "ml_training_anchor.md",
    "verify_v7_thread_fee.py",
}

# output/ 目录下需要排除的文件名前缀
OUTPUT_EXCLUDE_PREFIXES = (
    "jiewo_",
    "test2_",
    "v15_",
    "cadquery_fallback_",
    "_",
)

# output/ 目录下需要排除的具体文件名
OUTPUT_EXCLUDE_FILENAMES = {
    "analyze_boundary.py",
    "phase3_design.md",
}

# tests/ 目录下需要排除的文件名（临时验证脚本）
TESTS_EXCLUDE_FILENAMES = {
    "e2e_test.py",
    "e2e_test_v2.py",
    "quick_chat_test.py",
    "test_valid_step_upload.py",
}

# tests/ 目录下需要排除的文件名前缀
TESTS_EXCLUDE_PREFIXES = (
    "verify_",
)


# ---------------------------------------------------------------------------
# 过滤逻辑
# ---------------------------------------------------------------------------

def is_excluded(rel_path: Path) -> bool:
    """判断给定相对路径是否应被排除。

    Args:
        rel_path: 相对项目根目录的路径。

    Returns:
        True 表示排除，False 表示保留。
    """
    parts = rel_path.parts
    if not parts:
        return False

    name = rel_path.name

    # 1) 任意层级的目录名匹配
    for part in parts[:-1]:  # 中间目录
        if part in EXCLUDE_DIR_NAMES:
            return True
    # 末尾若是目录也检查（walk 时调用）
    if parts[-1] in EXCLUDE_DIR_NAMES:
        return True

    # 2) 根级相对路径精确匹配（支持前缀匹配子路径）
    for excl in EXCLUDE_RELATIVE_PATHS:
        excl_parts = Path(excl).parts
        if len(parts) >= len(excl_parts) and parts[: len(excl_parts)] == excl_parts:
            return True

    # 3) 扩展名匹配
    if rel_path.suffix.lower() in EXCLUDE_EXTENSIONS:
        return True

    # 3b) 文件名模式匹配（支持 * 通配符）
    for pattern in EXCLUDE_NAME_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True

    # 4) .bak_* 文件（无扩展名形式，如 file.bak_20240101）
    if ".bak_" in name:
        return True

    # 5) output/ 目录下的临时验证文件
    if parts[0] == "output" and len(parts) == 2:
        # output/ 直接子文件
        if name not in OUTPUT_KEEP_FILES:
            # 先检查具体文件名
            if name in OUTPUT_EXCLUDE_FILENAMES:
                return True
            # 再检查前缀
            for prefix in OUTPUT_EXCLUDE_PREFIXES:
                if name.startswith(prefix):
                    return True
            # 其余非保留文件也排除（output 下只保留白名单）
            return True
        # output/ 深层子目录里的文件一律排除（output 下不应有子目录保留）
    if parts[0] == "output" and len(parts) > 2:
        return True

    # 6) tests/ 目录下的临时验证脚本
    if parts[0] == "tests" and len(parts) == 2:
        if name in TESTS_EXCLUDE_FILENAMES:
            return True
        for prefix in TESTS_EXCLUDE_PREFIXES:
            if name.startswith(prefix):
                return True

    return False


# ---------------------------------------------------------------------------
# 打包
# ---------------------------------------------------------------------------

def build_zip() -> tuple[int, int]:
    """遍历项目目录并打包到 zip。

    Returns:
        (included_count, excluded_count)
    """
    included = 0
    excluded = 0

    # 确保输出目录存在
    OUTPUT_ZIP.parent.mkdir(parents=True, exist_ok=True)

    # 删除已存在的 zip
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    with zipfile.ZipFile(
        OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zf:
        for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
            # 原地修改 dirnames 以跳过排除目录（剪枝，提升效率）
            dirnames[:] = [
                d for d in dirnames
                if not is_excluded(Path(dirpath, d).relative_to(PROJECT_ROOT))
            ]

            for fname in filenames:
                full = Path(dirpath, fname)
                rel = full.relative_to(PROJECT_ROOT)

                if is_excluded(rel):
                    excluded += 1
                    continue

                # zip 内部路径：ZIP_ROOT_DIR/相对路径
                # 使用正斜杠以确保跨平台兼容
                arcname = f"{ZIP_ROOT_DIR}/{rel.as_posix()}"

                zf.write(full, arcname)
                included += 1

    return included, excluded


def verify_zip(included_count: int) -> None:
    """验证生成的 zip 文件。"""
    size_bytes = OUTPUT_ZIP.stat().st_size
    size_mb = size_bytes / (1024 * 1024)

    print("\n" + "=" * 60)
    print("打包完成 - 验证结果")
    print("=" * 60)
    print(f"zip 路径: {OUTPUT_ZIP}")
    print(f"zip 大小: {size_mb:.2f} MB ({size_bytes:,} bytes)")
    print(f"包含文件数: {included_count}")

    # 打开 zip 复核
    with zipfile.ZipFile(OUTPUT_ZIP, "r") as zf:
        names = zf.namelist()

    # 检查排除项
    forbidden_patterns = [".git/", "__pycache__/", ".venv/", "node_modules/",
                          ".pyc", ".bak"]
    violations = []
    for name in names:
        for pat in forbidden_patterns:
            if pat in name:
                violations.append((name, pat))
                break

    print(f"\n[排除验证] 检查 {len(forbidden_patterns)} 类禁止模式...")
    if violations:
        print(f"  ❌ 发现 {len(violations)} 个违规:")
        for name, pat in violations[:20]:
            print(f"     - {name}  (命中: {pat})")
    else:
        print("  ✅ 未发现任何禁止模式，排除规则生效")

    # 检查核心文件
    core_files = [
        "app/main.py",
        "app/main_lite.py",
        "config/version.txt",
        "README.md",
        "LICENSE",
        "requirements.txt",
    ]
    print(f"\n[核心文件验证] 检查 {len(core_files)} 个核心文件...")
    all_core_ok = True
    for core in core_files:
        arc = f"{ZIP_ROOT_DIR}/{core}"
        if arc in names:
            print(f"  ✅ {core}")
        else:
            print(f"  ❌ {core}  缺失!")
            all_core_ok = False

    # 检查保留的 output 文件
    print("\n[output 保留文件验证]...")
    for keep in OUTPUT_KEEP_FILES:
        arc = f"{ZIP_ROOT_DIR}/output/{keep}"
        if arc in names:
            print(f"  ✅ output/{keep}")
        else:
            print(f"  ❌ output/{keep}  缺失!")

    print(f"\nzip 内总条目数: {len(names)}")
    print("=" * 60)

    if violations or not all_core_ok:
        print("\n⚠️  验证发现问题，请检查上方输出。")
        sys.exit(1)
    else:
        print("\n✅ 所有验证通过。")


def main() -> None:
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"输出 zip:    {OUTPUT_ZIP}")
    print(f"zip 内根目录: {ZIP_ROOT_DIR}/")
    print("\n开始打包...")

    included, excluded = build_zip()
    print(f"已包含 {included} 个文件，排除 {excluded} 个文件。")

    verify_zip(included)


if __name__ == "__main__":
    main()