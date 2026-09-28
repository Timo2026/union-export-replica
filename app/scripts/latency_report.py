"""latency_report.py — 全链路时延分析 (维度 6.3).

聚合 data/traces/*.jsonl 的 span duration_ms, 产出:
  每技能 P50/P95/max 时延、端到端 agent_run 时延、按 context 的链路分解。
真实数据来自 observability 落的 span; 无 trace 时提示先跑 demo。
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parent.parent
_TRACES = _ROOT / "data" / "traces"


def _pct(vals: List[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round(p / 100 * (len(s) - 1)))))
    return round(s[k], 2)


def load_spans(trace_dir: Path = _TRACES) -> List[Dict[str, Any]]:
    spans: List[Dict[str, Any]] = []
    if not trace_dir.exists():
        return spans
    for f in trace_dir.glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    spans.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return spans


def report(trace_dir: Path = _TRACES) -> Dict[str, Any]:
    spans = load_spans(trace_dir)
    if not spans:
        return {"n_spans": 0, "hint": "无 trace; 先跑 python scripts/run_demo.py 或调用 /v1/rfq/intake"}
    by_name: Dict[str, List[float]] = defaultdict(list)
    e2e: List[float] = []
    for s in spans:
        d = s.get("duration_ms")
        if d is None:
            continue
        by_name[s.get("name", "?")].append(float(d))
        if s.get("name") == "agent_run":
            e2e.append(float(d))
    per_skill = {}
    for name, vals in by_name.items():
        per_skill[name] = {"n": len(vals), "p50": _pct(vals, 50), "p95": _pct(vals, 95),
                           "max": round(max(vals), 2), "mean": round(statistics.mean(vals), 2)}
    return {
        "n_spans": len(spans),
        "n_traces": len(list(trace_dir.glob("*.jsonl"))) if trace_dir.exists() else 0,
        "e2e_agent_run_ms": {"p50": _pct(e2e, 50), "p95": _pct(e2e, 95),
                             "max": round(max(e2e), 2) if e2e else 0, "n": len(e2e)},
        "per_skill": per_skill,
        "bottleneck": max(((k, v["p95"]) for k, v in per_skill.items() if k != "agent_run"),
                          key=lambda x: x[1], default=(None, 0))[0],
    }


def main():
    rep = report()
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if rep.get("n_spans"):
        print("\n=== 全链路时延摘要 ===")
        e = rep["e2e_agent_run_ms"]
        print(f"端到端 agent_run: P50={e['p50']}ms P95={e['p95']}ms max={e['max']}ms (n={e['n']})")
        print(f"瓶颈技能(P95 最高): {rep['bottleneck']}")
        for k, v in sorted(rep["per_skill"].items(), key=lambda x: -x[1]["p95"]):
            print(f"  {k:<26} P50={v['p50']:>7}ms P95={v['p95']:>7}ms max={v['max']:>7}ms n={v['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
