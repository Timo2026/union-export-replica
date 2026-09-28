#!/usr/bin/env python3
"""inventory_skills.py — 扫描外部 skill 包, 生成目录/隔离分类.

输出:
  skill_catalog/index.json
  skill_catalog/quarantined.md
  docs/skill-catalog.md
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 外部 skill 包扫描根: 优先 UEA_SKILL_ROOTS (os.pathsep 分隔), 否则命令行参数,
# 最后回落仓库内 skills/ (本机自带的 33 个)。原先硬编码的 Windows 路径在 Linux 上
# 只会扫出空结果, 故不再作为默认值; 需要扫源机语料时显式传参。
DEFAULT_ROOTS = [
    p for p in os.environ.get("UEA_SKILL_ROOTS", "").split(os.pathsep) if p
] or [_ROOT / "skills"]

# 与 config/skill_registry.yaml.quarantine 对齐
QUARANTINE_PATTERNS = [
    re.compile(r"^material-\$", re.I),
    re.compile(r"^(apple|github|1password|travel|spotify|notion|obsidian|discord|sonos)", re.I),
    re.compile(r"^suntime-", re.I),
    re.compile(r"^(blogwatcher|bluebubbles|blucli|gifgrep|gog|goplaces|peekaboo|himalaya)", re.I),
    re.compile(r"^(tmux|things-mac|smart-home|tcm-prescriber|qq-notifier|hospital-booking)", re.I),
    re.compile(r"^material-['\"].*", re.I),
    re.compile(r"^part-【", re.I),
]

# 可调度能力关键词 → 候选 pack
PACK_HINTS = {
    "quote-pack": re.compile(r"(quote|报价|price|cost)", re.I),
    "cad-pack": re.compile(r"(cad|step|occ|dxf|geometry|factory)", re.I),
    "decision-pack": re.compile(r"(ceo|reid|orchestr|decision|fleet)", re.I),
    "knowledge-router": re.compile(r"(knowledge|material-|process-|dfm|rfq)", re.I),
}

EXTRACTED_PACK_IDS = {
    "unionskill-quote", "opc-quote-engine-v2", "reference-quote", "unified-quote",
    "quote-ptuning", "step-factory", "dxf-engineer-draw", "orchestrator",
    "ceo-decision-cb", "reid-operating-system", "output-bundler",
    "quote-doc-generator", "knowledge-querier", "order-history-db",
    "opc-api", "opc-unified-api", "opc-fusion-quote",
}

CORE_SKILL_IDS = {
    "parse_rfq", "extract_specs", "check_dfm", "calc_quote", "verify_gate",
    "write_reply", "submit_feedback", "render_thumbnail", "supplier_match",
    "golden_chain", "fleet-coordinator", "material-expert", "price-expert",
    "dfm-expert", "quality-loop", "orchestrator", "ceo-decision", "reid-os",
    "rfq-extraction", "dfm-conflict", "cnc-quote", "step-analysis",
    "reply-draft", "verification", "freight-customs",
}


def classify(name: str, path: Path, has_skill_md: bool) -> dict:
    if not has_skill_md:
        status, reason = "quarantined", "no SKILL.md"
    elif any(p.search(name) for p in QUARANTINE_PATTERNS):
        status, reason = "quarantined", "noise/irrelevant pattern"
    elif name in CORE_SKILL_IDS:
        status, reason = "core", "livekernel core skill id"
    elif name in EXTRACTED_PACK_IDS:
        status, reason = "pack_candidate", "skills_extracted curated"
    else:
        # 默认知识/目录：不热调度
        tags = []
        for pack, pat in PACK_HINTS.items():
            if pat.search(name):
                tags.append(pack)
        if re.search(r"(knowledge|工艺|技术|材料|part-|process-|ds-\d|industry-)", name, re.I):
            status, reason = "catalog_only", "knowledge/dataset slice"
        elif tags:
            status, reason = "pack_candidate", "capability keywords: " + ",".join(tags)
        else:
            status, reason = "catalog_only", "default catalog (not hot-dispatched)"
    tags = []
    for pack, pat in PACK_HINTS.items():
        if pat.search(name):
            tags.append(pack)
    return {
        "id": name,
        "path": str(path),
        "has_skill_md": has_skill_md,
        "tags": tags,
        "proposed_status": status,
        "reason": reason,
    }


def scan_root(root: Path) -> list[dict]:
    items = []
    if not root.exists():
        return items
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        has_md = (child / "SKILL.md").exists()
        items.append(classify(child.name, child, has_md))
    return items


def write_catalog_md(index: dict, out: Path) -> None:
    lines = [
        "# Skill Catalog (P0 inventory)",
        "",
        f"Generated: {index['generated_at']}",
        "",
        "## Counts",
        "",
        "| Status | N |",
        "|--------|---|",
    ]
    for k, v in sorted(index["counts"].items()):
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Policy", "",
              "- `core`: livekernel iron-rule skills (dispatcher default)",
              "- `pack_enabled`: only if listed in `config/skill_registry.yaml`",
              "- `catalog_only`: knowledge index, never in TOOL_ALLOWLIST",
              "- `quarantined`: never load", ""]
    by: dict[str, list] = {}
    for it in index["items"]:
        by.setdefault(it["proposed_status"], []).append(it)
    for status in ("core", "pack_candidate", "catalog_only", "quarantined"):
        rows = by.get(status, [])
        lines.append(f"## {status} ({len(rows)})")
        lines.append("")
        for it in rows[:80]:
            lines.append(f"- `{it['id']}` — {it['reason']}")
        if len(rows) > 80:
            lines.append(f"- … +{len(rows)-80} more (see skill_catalog/index.json)")
        lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


def write_quarantine_md(index: dict, out: Path) -> None:
    q = [i for i in index["items"] if i["proposed_status"] == "quarantined"]
    lines = ["# Quarantined skills", "",
             "These ids must NEVER enter TOOL_ALLOWLIST / skill_registry pack_enabled.", ""]
    for it in q:
        lines.append(f"- `{it['id']}` — {it['reason']}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    roots = [Path(p) for p in DEFAULT_ROOTS]
    if len(sys.argv) > 1:
        roots = [Path(p) for p in sys.argv[1:]]
    all_items: list[dict] = []
    for r in roots:
        all_items.extend(scan_root(r))
    counts: dict[str, int] = {}
    for it in all_items:
        counts[it["proposed_status"]] = counts.get(it["proposed_status"], 0) + 1
    counts["total"] = len(all_items)
    index = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "roots": [str(r) for r in roots],
        "counts": counts,
        "items": all_items,
    }
    cat_dir = _ROOT / "skill_catalog"
    cat_dir.mkdir(exist_ok=True)
    (cat_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    write_quarantine_md(index, cat_dir / "quarantined.md")
    write_catalog_md(index, _ROOT / "docs" / "skill-catalog.md")
    print(json.dumps(counts, ensure_ascii=False))
    print(f"wrote {cat_dir/'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
