"""scripts/count_skills.py — Skill 数字单一来源 (README/MANIFEST 只引用本脚本输出).

用法:
    python scripts/count_skills.py          # 人读摘要
    python scripts/count_skills.py --json   # 机器可读 JSON

口径:
    total        = skills/ 下含 SKILL.md 的目录数
    with_tool    = 其中含 tool.py 的数量
    missing_tool = 缺 tool.py 的 skill 列表
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"


def count() -> dict:
    skills = sorted(p for p in SKILLS_DIR.iterdir()
                    if p.is_dir() and not p.name.startswith(("_", "."))
                    and not p.name.startswith("__"))
    entries = []
    for s in skills:
        entries.append({
            "id": s.name,
            "has_skill_md": (s / "SKILL.md").exists(),
            "has_tool_py": (s / "tool.py").exists(),
        })
    named = [e for e in entries if e["has_skill_md"]]
    return {
        "total_dirs": len(entries),
        "total": len(named),
        "with_tool": sum(1 for e in named if e["has_tool_py"]),
        "missing_tool": [e["id"] for e in named if not e["has_tool_py"]],
        "no_skill_md": [e["id"] for e in entries if not e["has_skill_md"]],
    }


if __name__ == "__main__":
    c = count()
    if "--json" in sys.argv:
        print(json.dumps(c, ensure_ascii=False, indent=2))
    else:
        print(f"skills total: {c['total']} (dirs: {c['total_dirs']})")
        print(f"with tool.py: {c['with_tool']}")
        if c["missing_tool"]:
            print(f"missing tool.py: {', '.join(c['missing_tool'])}")
        if c["no_skill_md"]:
            print(f"no SKILL.md: {', '.join(c['no_skill_md'])}")
