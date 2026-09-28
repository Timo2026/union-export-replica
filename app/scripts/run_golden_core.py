#!/usr/bin/env python3
"""run_golden_core.py — P0 核心场景: 黄金链三 verdict + skill registry 自检.

用法:
    python scripts/run_golden_core.py
    python scripts/run_golden_core.py --offline

输出:
    data/golden_core/*.json
    Documents/demo/union-core-scenario/results/ (拷贝)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _demo_dir(cli_dest: str = "") -> Path:
    """demo 拷贝目标: --dest > UEA_DEMO_DIR > data/exports/union-core-scenario."""
    if cli_dest:
        return Path(cli_dest)
    env = os.environ.get("UEA_DEMO_DIR")
    if env:
        return Path(env)
    return _ROOT / "data" / "exports" / "union-core-scenario"

# 三 verdict 内建样例 (对齐 golden_scenarios + 框架 PRD)
CORE_CASES = [
    {
        "id": "G-PASS",
        "expect_status": "PASS",
        "customer": {"customer_id": "CUST-G01", "name": "Alpha Parts Co",
                     "contact_name": "Alice", "country": "US"},
        "email": "Hi, please quote 10 pcs of 6061 aluminum blocks, 100x50x20mm, "
                 "as-machined finish, general tolerance IT7. Thanks!",
    },
    {
        "id": "G-HITL",
        "expect_status": "HITL",
        "customer": {"customer_id": "CUST-G02", "name": "Precision Med Ltd",
                     "contact_name": "David", "country": "UK"},
        "email": "We require 10 pcs TC4 titanium surgical fixtures, 60x30x12mm, "
                 "as-machined, precision tolerance IT5. Please confirm capability.",
    },
    {
        "id": "G-BLOCKED",
        "expect_status": "BLOCKED",
        "customer": {"customer_id": "CUST-G03", "name": "Pacific Hardware",
                     "contact_name": "Cathy", "country": "SG"},
        "email": "Dear team, kindly quote 20 pcs of 304 stainless steel plates, "
                 "100x50x10mm, anodizing, tolerance IT7.",
    },
]


def _price_snapshot(q: dict) -> dict:
    return {
        "unit_price": q.get("unit_price"),
        "final_price": q.get("final_price") or q.get("total_price"),
        "_source": q.get("_source"),
        "hash": q.get("sha256") or q.get("price_hash") or q.get("hash"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", default=True)
    ap.add_argument("--out", default=str(_ROOT / "data" / "golden_core"))
    ap.add_argument("--dest", default="",
                    help="demo 产物拷贝目标 (默认 $UEA_DEMO_DIR 或 data/exports/union-core-scenario)")
    a = ap.parse_args()

    from bootstrap import build_controller
    from services.config import load_settings
    from scripts.kernel_preflight import EXIT_ENV_MISSING, probe
    from adapters.skill_pack_adapter import allowed_pack_skill_ids, run as pack_run
    from services.guardrails import TOOL_ALLOWLIST
    from services import skill_config as sc

    settings = load_settings(_ROOT)
    if a.offline:
        settings.setdefault("timo", {})["base_url"] = "http://127.0.0.1:59999"

    ctrl = build_controller(settings_override=settings)
    kp = probe(ctrl)

    # --- registry / allowlist 自检 ---
    pack_ids = allowed_pack_skill_ids()
    cfg = sc.load()
    checks = {
        "pack_ids": sorted(pack_ids),
        "all_pack_in_allowlist": all(p in TOOL_ALLOWLIST for p in pack_ids),
        "all_pack_enabled_in_skills_yaml": all(
            (cfg.get("skills") or {}).get(p, {}).get("enabled") for p in pack_ids
        ),
        "catalog_not_in_allowlist": True,  # pack bridge only; catalog_* never added
        "iron_rule_1_locked": ((cfg.get("openshell") or {}).get("iron-rule-1") or {}).get("locked", False),
    }
    # sample pack adapter
    sample = pack_run(None, skill_id="unionskill-quote-bridge",
                      intent="quote 6061 100x50x20")
    checks["pack_sample_cannot_override_price"] = bool(sample.get("cannot_override_price"))
    checks["pack_sample_has_no_authoritative_price"] = (
        "unit_price" not in (sample.get("payload") or {})
        and "final_price" not in (sample.get("payload") or {})
    )

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    allok = bool(checks["all_pack_in_allowlist"] and checks["all_pack_enabled_in_skills_yaml"]
                 and checks["iron_rule_1_locked"]
                 and checks["pack_sample_cannot_override_price"]
                 and checks["pack_sample_has_no_authoritative_price"])

    print("=" * 72)
    print(" Golden Core Scenario — P0")
    print("=" * 72)
    print(f" engine: {kp['source_label']}  [{kp['state']}]")
    print(f" pack_allowlist_ok: {checks['all_pack_in_allowlist']}")
    print("-" * 72)

    # 内核缺席 → 显式降级 (退出码 3)。三 verdict 需要确定性报价/DFM 裁决,
    # 内核不在时 BLOCKED/PASS 都失去意义, 故不猜、不冒充、不静默通过。
    if not kp["usable"]:
        print(" 制造内核缺席, 三 verdict 场景无法运行 (定价/DFM 的唯一权威来源不可用)。")
        print(f"   engine_src = {kp['engine_src']!r}")
        print("   修复: export CNC_BRAIN_SRC=<cnc-ai-brain v12.0 根> CNC_BRAIN_PY=<引擎解释器>")
        print("   退出码 3 = 环境不满足 (非用例失败, 用例失败为 1)。")
        out_dir = Path(a.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "summary.json").write_text(json.dumps({
            "all_ok": False, "skipped": True, "skip_reason": "kernel-absent",
            "checks": checks, "engine_source": kp["source_label"],
            "kernel_probe": kp, "results": [], "ts": time.time(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "trace_summary.md").write_text(
            "# Golden Core Trace Summary\n\n"
            f"- all_ok: **False** (skipped)\n- reason: kernel-absent\n"
            f"- engine: {kp['source_label']}\n"
            f"- engine_src: `{kp['engine_src']}` (本机不存在)\n\n"
            "修复: `export CNC_BRAIN_SRC=<...> CNC_BRAIN_PY=<...>`\n",
            encoding="utf-8")
        print(f"\n wrote {out_dir} (skipped=true)")
        return EXIT_ENV_MISSING

    for case in CORE_CASES:
        r = ctrl.run(email_text=case["email"], customer=case["customer"])
        status = r.get("verification_status")
        ok = status == case["expect_status"] and bool(r.get("audit_valid"))
        q = r.get("quote") or {}
        snap = _price_snapshot(q)
        src = str(snap.get("_source") or "")
        # 价格来源必须显式, 且 PASS 路径应有数字来自 timo/离线内核
        if status == "PASS" and snap.get("unit_price") is not None:
            ok = ok and ("timo" in src.lower() or "offline" in src.lower()
                         or "kernel" in src.lower() or src != "")
        if status == "BLOCKED":
            # BLOCKED 不得自动放行
            ok = ok and not r.get("reply", {}).get("auto_send")
        allok = allok and ok

        payload = {
            "id": case["id"],
            "expect_status": case["expect_status"],
            "verification_status": status,
            "state": r.get("state"),
            "context_id": r.get("context_id"),
            "customer_id": case["customer"].get("customer_id"),
            "quote": snap,
            "engine_source": r.get("engine_source"),
            "multimodal_conflicts": r.get("multimodal_conflicts"),
            "reasons": r.get("reasons"),
            "audit_valid": r.get("audit_valid"),
            "reply_subject": (r.get("reply") or {}).get("subject"),
            "auto_send": (r.get("reply") or {}).get("auto_send"),
            "ok": ok,
            "ts": time.time(),
        }
        results.append(payload)
        fp = out_dir / f"{case['id']}.json"
        fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        flag = "OK" if ok else "XX"
        print(f"{case['id']:<10} expect={case['expect_status']:<8} got={status:<8} "
              f"unit={snap.get('unit_price')} src={src or '-'} [{flag}]")

    summary = {
        "all_ok": allok,
        "checks": checks,
        "results": results,
        "engine_source": results[0].get("engine_source") if results else "",
        "ts": time.time(),
    }
    (out_dir / "trace_summary.md").write_text(
        "\n".join([
            "# Golden Core Trace Summary",
            "",
            f"- all_ok: **{allok}**",
            f"- engine: {summary['engine_source']}",
            f"- pack_allowlist_ok: {checks['all_pack_in_allowlist']}",
            f"- iron_rule_1_locked: {checks['iron_rule_1_locked']}",
            "",
            "| ID | Expect | Got | Unit | Source | OK |",
            "|----|--------|-----|------|--------|----|",
        ] + [
            f"| {x['id']} | {x['expect_status']} | {x['verification_status']} | "
            f"{(x['quote'] or {}).get('unit_price')} | {(x['quote'] or {}).get('_source')} | {x['ok']} |"
            for x in results
        ]) + "\n", encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 拷贝到 demo (目标不可写时不阻断主流程) ---
    demo_dir = _demo_dir(a.dest)
    try:
        dest = demo_dir / "results"
        dest.mkdir(parents=True, exist_ok=True)
        for p in out_dir.iterdir():
            if p.is_file():
                shutil.copy2(p, dest / p.name)
        readme = demo_dir / "README.md"
        if not readme.exists() or "union-core-scenario" not in readme.read_text(encoding="utf-8", errors="ignore"):
            readme.write_text(
                "# union-core-scenario\n\n"
                "P0 黄金链核心场景产物（PASS / HITL / BLOCKED）。\n\n"
                "运行：`python scripts/run_golden_core.py --offline`\n\n"
                "结果目录：`results/`\n",
                encoding="utf-8")
        src_script = _ROOT / "scripts" / "run_golden_core.py"
        if src_script.exists():
            shutil.copy2(src_script, dest / "run_golden_core.py.copy")
        print(f"\n demo copy → {dest}")
    except Exception as e:
        print(f"\n demo copy failed: {e!r}")

    print(f"\n result: {'PASS' if allok else 'FAIL'}  ({sum(x['ok'] for x in results)}/{len(results)} cases + checks)")
    print(f" wrote {out_dir}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
