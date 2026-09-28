#!/usr/bin/env python3
"""run_flywheel_demo.py — 双飞轮 + 逐客户沙箱 P0 演示.

场景:
  客户 A: 首单 → Won + 实际成本偏高 → 校准更新 → 第二单带 bias 证据
  客户 B: 沙箱隔离 — 看不到 A 的 postmortem/校准

输出: data/flywheel_demo/ + Documents/demo/union-core-scenario/flywheel/
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _demo_dir(cli_dest: str = "") -> Path:
    """demo 产物拷贝目标: --dest > UEA_DEMO_DIR > data/exports/ (Linux 下可写)."""
    if cli_dest:
        return Path(cli_dest)
    env = os.environ.get("UEA_DEMO_DIR")
    if env:
        return Path(env)
    return _ROOT / "data" / "exports" / "flywheel_demo"


def main() -> int:
    ap = argparse.ArgumentParser(description="双飞轮 + 逐客户沙箱 P0 演示")
    ap.add_argument("--dest", default="",
                    help="demo 产物拷贝目标目录 (默认 $UEA_DEMO_DIR 或 data/exports/flywheel_demo)")
    args = ap.parse_args()

    from services.crm_memory import CRMMemory
    from services.quote_calibration import QuoteCalibration
    from services.customer_flywheel import CustomerFlywheel
    from services.customer_health import CustomerHealthEngine

    out = _ROOT / "data" / "flywheel_demo"
    out.mkdir(parents=True, exist_ok=True)

    # 独立 demo DB, 不污染生产 crm.sqlite3
    db = str(out / "flywheel_demo.sqlite3")
    if Path(db).exists():
        Path(db).unlink()
    crm = CRMMemory(db)
    cal = QuoteCalibration(crm)
    health = CustomerHealthEngine(crm)
    fw = CustomerFlywheel(crm, health, cal)

    report = {"customers": {}, "sandbox_isolation": {}, "ts": time.time()}

    # ---- 客户 A 首单 ----
    a = {"customer_id": "CUST-A", "name": "Alpha Parts", "email": "a@example.com"}
    crm.upsert_customer(a)
    crm.write_rfq({
        "context_id": "RFQ-A1", "state": "DONE",
        "rfq": {"customer": {"customer_id": "CUST-A"}, "material": "6061",
                "surface": "anodizing", "quantity": 10},
    })
    crm.write_quote({
        "context_id": "RFQ-A1",
        "commercial": {"quote": {"unit_price": 10.0, "final_price": 100.0,
                                  "_source": "timo-offline"}},
    }, {"status": "PASS"}, {"subject": "Quote A1"})
    before = fw.before_run(a)
    ev1 = cal.record_outcome(
        context_id="RFQ-A1", customer_id="CUST-A",
        material="6061", surface="anodizing", quantity=10,
        quoted_unit_price=10.0, actual_unit_cost=12.0, outcome="won")
    # 连续 3 单形成置信
    for i in range(2):
        cid = f"RFQ-A{i+2}"
        crm.write_rfq({"context_id": cid, "state": "DONE",
                       "rfq": {"customer": {"customer_id": "CUST-A"},
                               "material": "6061", "surface": "anodizing",
                               "quantity": 10}})
        crm.write_quote({"context_id": cid,
                         "commercial": {"quote": {"unit_price": 10.0, "final_price": 100.0,
                                                   "_source": "timo-offline"}}},
                        {"status": "PASS"}, {"subject": f"Quote A{i+2}"})
        cal.record_outcome(context_id=cid, customer_id="CUST-A",
                           material="6061", surface="anodizing", quantity=10,
                           quoted_unit_price=10.0, actual_unit_cost=11.5,
                           outcome="won")
    adj_a = cal.get_adjustments("CUST-A", material="6061")
    after = fw.before_run(a)
    hist_a = crm.list_customer_history("CUST-A")

    report["customers"]["A"] = {
        "first_outcome_event": ev1,
        "calibration_adjustments": adj_a,
        "flywheel_state_before": {k: before.get(k) for k in
                                  ("customer_id", "health_score", "churn_risk", "price_bias_pct")},
        "flywheel_state_after": {k: after.get(k) for k in
                                 ("customer_id", "health_score", "churn_risk", "price_bias_pct")},
        "history_quote_n": hist_a.get("n"),
        "history_postmortem_notes": [p.get("note") for p in hist_a.get("postmortems", [])],
        "quote_source": "timo-offline (铁律①: overlay 不改 final_price)",
        "overlay_policy": "off — bias 仅作证据/提案注入 Context",
    }

    # 跟进任务 (draft_only)
    fu_id = crm.add_followup(customer_id="CUST-A", context_id="RFQ-A1",
                             scheduled_at=time.time() + 86400,
                             channel="email", intent="gentle_nudge",
                             condition="no_response")
    pending_a = crm.list_pending_followups("CUST-A")
    report["customers"]["A"]["followup_scheduled"] = {"id": fu_id, "pending": pending_a,
                                                       "draft_only": True}

    # ---- 客户 B 沙箱隔离 ----
    b = {"customer_id": "CUST-B", "name": "Beta GmbH", "email": "b@example.com"}
    crm.upsert_customer(b)
    crm.write_rfq({"context_id": "RFQ-B1", "state": "DONE",
                   "rfq": {"customer": {"customer_id": "CUST-B"},
                           "material": "6061", "surface": "anodizing",
                           "quantity": 10}})
    crm.write_quote({"context_id": "RFQ-B1",
                     "commercial": {"quote": {"unit_price": 10.0, "final_price": 100.0,
                                               "_source": "timo-offline"}}},
                    {"status": "PASS"}, {"subject": "Quote B1"})
    hist_b = crm.list_customer_history("CUST-B")
    adj_b = cal.get_adjustments("CUST-B", material="6061")
    state_b = fw.before_run(b)
    report["sandbox_isolation"] = {
        "B_history_n": hist_b.get("n"),
        "B_postmortem_notes": [p.get("note") for p in hist_b.get("postmortems", [])],
        "B_calibration_samples": adj_b.get("sample_count", 0),
        "A_notes_visible_to_B": any(
            (n or "").startswith("A") for n in
            [p.get("note") for p in hist_b.get("postmortems", [])]),
        "B_sees_A_bias": bool(adj_b.get("bias_pct")),
        "pass": (
            hist_b.get("n", 0) <= 1
            and not any((n or "") == "A only" for n in
                        [p.get("note") for p in hist_b.get("postmortems", [])])
            and adj_b.get("sample_count", 0) == 0
        ),
    }

    # 报价精度指标占位
    report["metrics"] = {
        "MAPE_repeat_A": abs(12.0 - 10.0) / 10.0 * 100,
        "note": "A 系统性报价偏低 → bias_pct 应 >0 (提案)",
        "bias_A": adj_a.get("bias_pct"),
        "confidence_A": adj_a.get("confidence"),
        "sample_count_A": adj_a.get("sample_count"),
    }

    report["all_ok"] = bool(
        report["sandbox_isolation"].get("pass")
        and (adj_a.get("bias_pct") or 0) > 0
        and (adj_a.get("sample_count") or 0) >= 3
        and hist_a.get("n", 0) >= 3
        and hist_b.get("n", 0) <= 1
    )

    (out / "flywheel_demo.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / "flywheel_summary.md").write_text(
        "\n".join([
            "# 双飞轮 Demo Summary",
            "",
            f"- all_ok: **{report['all_ok']}**",
            f"- A bias_pct: {adj_a.get('bias_pct')} (期望 >0, 提案非终价)",
            f"- A samples: {adj_a.get('sample_count')}",
            f"- sandbox pass: {report['sandbox_isolation'].get('pass')}",
            f"- overlay policy: off / draft_only followup",
            "",
            "铁律: final_price 始终 `_source=timo-offline`; 校准只作证据与系数提案。",
        ]) + "\n", encoding="utf-8")

    # demo 拷贝 (目标目录可写才拷; 拷不进去不影响主流程结果)
    demo = _demo_dir(args.dest)
    try:
        demo.mkdir(parents=True, exist_ok=True)
        for p in out.iterdir():
            if p.is_file():
                shutil.copy2(p, demo / p.name)
        (demo / "README.md").write_text(
            "# flywheel demo\n\n双飞轮 + 客户沙箱 P0。运行 `python scripts/run_flywheel_demo.py`\n",
            encoding="utf-8")
        print(f" demo → {demo}")
    except Exception as e:
        print(f" demo copy fail: {e!r}")

    print(json.dumps({
        "all_ok": report["all_ok"],
        "bias_A": adj_a.get("bias_pct"),
        "samples_A": adj_a.get("sample_count"),
        "sandbox_pass": report["sandbox_isolation"].get("pass"),
        "B_samples": adj_b.get("sample_count"),
    }, ensure_ascii=False))
    crm.close()
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
