"""run_demo.py — 比赛演示脚本: 一键跑通黄金链 S1-S5 + M1.

用法:
    python scripts/run_demo.py            # 自动: 在线优先 :7862, 离线兜底
    python scripts/run_demo.py --offline  # 强制离线内核 (byte-identical)

内核缺席 (engine_src 不在本机) → 显式降级并返回退出码 3, 不用别的引擎冒充。
    export CNC_BRAIN_SRC=/path/to/Timo_CNC-AI-Brain-v12.0-Fusion
    export CNC_BRAIN_PY=/path/to/engine-venv/bin/python

输出: 控制台表格 + data/demo/demo_result.json + 每条 context 的审计链文件。
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

# Windows 控制台默认 gbk，emoji/中文会 UnicodeEncodeError；与 e2e_l3.py 同款规避
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bootstrap import build_controller                     # noqa: E402
from services.config import load_settings                  # noqa: E402
from scripts.kernel_preflight import EXIT_ENV_MISSING, probe   # noqa: E402

_SCEN = json.loads((_ROOT / "data" / "golden_scenarios.json").read_text(encoding="utf-8"))["scenarios"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="强制离线内核 (指向死端口触发降级)")
    a = ap.parse_args()

    settings = load_settings(_ROOT)
    if a.offline:
        settings["timo"]["base_url"] = "http://127.0.0.1:59999"
    ctrl = build_controller(settings_override=settings)

    kp = probe(ctrl)

    print("=" * 78)
    print(" Union Manufacturing Export Agent — Golden Path Demo (S1-S5 + M1)")
    print("=" * 78)
    print(f" 制造内核 : {kp['source_label']}  [{kp['state']}]")
    print(f" 多模态层 : {ctrl.funasr.source_label()}")
    print(f" 离线模式 : {a.offline}")
    print("-" * 78)

    # 内核缺席 → 显式降级 (退出码 3), 绝不用别的引擎冒充报价/DFM
    if not kp["usable"]:
        print(" 制造内核缺席, 黄金链无法进行 (报价与 DFM 裁决的唯一权威来源不可用)。")
        print(f"   engine_src = {kp['engine_src']!r}")
        print("   修复: export CNC_BRAIN_SRC=<cnc-ai-brain v12.0 根> CNC_BRAIN_PY=<引擎解释器>")
        print("   本机未装内核属环境不满足 (退出码 3), 非用例失败 (退出码 1)。")
        out = _ROOT / "data" / "demo"
        out.mkdir(parents=True, exist_ok=True)
        (out / "demo_result.json").write_text(
            json.dumps({"engine_source": kp["source_label"], "all_ok": False,
                        "skipped": True, "skip_reason": "kernel-absent",
                        "kernel_probe": kp, "results": []},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f'\n 已写入: {out / "demo_result.json"} (skipped=true, 原因 kernel-absent)')
        return EXIT_ENV_MISSING

    results = []
    hdr = f'{"ID":<4}{"STATE":<10}{"VERIFY":<9}{"UNIT":>10}{"FINAL":>11}{"MARGIN":>8}  CONFLICT'
    print(hdr)
    print("-" * 78)
    allok = True
    for sc in _SCEN:
        r = ctrl.run(email_text=sc["email"], customer=sc.get("customer"),
                     voice_transcript=sc.get("voice_transcript"))
        ok = (r["state"] == sc["expect_state"] and r["verification_status"] == sc["expect_status"]
              and r["audit_valid"])
        if sc.get("expect_conflict"):
            ok = ok and sc["expect_conflict"] in r["multimodal_conflicts"]
        allok = allok and ok
        q = r["quote"]
        unit = f'{q.get("unit_price"):.1f}' if q.get("unit_price") is not None else "-"
        final = f'{q.get("final_price"):.1f}' if q.get("final_price") is not None else "-"
        marg = f'{r["margin_pct"]:.1f}%' if r.get("margin_pct") is not None else "-"
        conf = ",".join(r["multimodal_conflicts"]) or "-"
        flag = "OK" if ok else "XX"
        print(f'{sc["id"]:<4}{r["state"]:<10}{r["verification_status"]:<9}{unit:>10}{final:>11}{marg:>8}  {conf}  [{flag}]')
        results.append({"id": sc["id"], "expect_state": sc["expect_state"],
                        "state": r["state"], "verification_status": r["verification_status"],
                        "context_id": r["context_id"], "unit_price": q.get("unit_price"),
                        "final_price": q.get("final_price"), "margin_pct": r.get("margin_pct"),
                        "engine_source": r["engine_source"], "multimodal_conflicts": r["multimodal_conflicts"],
                        "reply_subject": r["reply"]["subject"], "auto_send": r["reply"]["auto_send"],
                        "audit_valid": r["audit_valid"], "reasons": r["reasons"], "ok": ok})

    print("-" * 78)
    print(f' 结果: {"全部通过 ✅" if allok else "存在失败 ❌"}  ({sum(x["ok"] for x in results)}/{len(results)})')

    # hero moment: M1 语音↔邮件冲突
    m1 = next(x for x in results if x["id"] == "M1")
    print("\n [HERO MOMENT] M1 多模态冲突处理:")
    print(f'   Email 关键公差 ±0.02mm, Voice 声称可放宽到 ±0.05mm')
    print(f'   → 系统未静默采纳任一方, 冲突 {m1["multimodal_conflicts"]} → 状态 {m1["state"]} (人工复核)')
    print(f'   → 外部邮件 auto_send={m1["auto_send"]} (仅草稿)')

    out = _ROOT / "data" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    (out / "demo_result.json").write_text(
        json.dumps({"engine_source": results[0]["engine_source"] if results else "",
                    "all_ok": allok, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f'\n 已写入: {out / "demo_result.json"}')
    if ctrl.crm is not None:
        print(f' CRM/Memory: {ctrl.crm.stats()}')
        ctrl.crm.close()
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
