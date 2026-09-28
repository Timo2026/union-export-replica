"""metrics.py — 量化评估体系 (维度 7.1): 工具准确率 / 字段准确率 / 任务完成率 / 报价偏差 + 消融 + A/B.

纯函数(可离线单测) + evaluate_controller(需引擎, 供 notebook/demo 用)。
所有指标可复现、可对比; 不依赖 LLM 主观判断。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_ROOT = Path(__file__).resolve().parent.parent

# 参与字段准确率评估的 canonical RFQ 字段
RFQ_FIELDS = ["material", "surface", "quantity", "tolerance_grade"]


# ---------------- 纯指标函数 ----------------
def field_accuracy(pred: Dict[str, Any], gold: Dict[str, Any],
                   fields: Sequence[str] = RFQ_FIELDS) -> Dict[str, Any]:
    """逐字段命中率 (None==None 视为一致)。"""
    per: Dict[str, bool] = {}
    for f in fields:
        p, g = pred.get(f), gold.get(f)
        if isinstance(p, str) and isinstance(g, str):
            per[f] = p.strip().lower() == g.strip().lower()
        else:
            per[f] = (p == g) or (p is None and g is None)
    hit = sum(1 for v in per.values() if v)
    return {"per_field": per, "hit": hit, "total": len(fields),
            "accuracy": round(hit / len(fields), 4) if fields else 0.0}


def quote_deviation(predicted: Optional[float], reference: Optional[float]) -> Dict[str, Any]:
    """报价相对偏差 (%); 任一为空 → None。"""
    if predicted is None or reference in (None, 0):
        return {"abs": None, "pct": None}
    d = float(predicted) - float(reference)
    return {"abs": round(d, 2), "pct": round(d / float(reference) * 100, 2)}


def task_completion_rate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """任务完成率: state 与 status 同时命中期望。"""
    if not rows:
        return {"n": 0, "rate": 0.0}
    ok = sum(1 for r in rows
             if r.get("state") == r.get("expect_state")
             and r.get("verification_status") == r.get("expect_status"))
    return {"n": len(rows), "ok": ok, "rate": round(ok / len(rows), 4)}


def tool_call_accuracy(predicted_seq: Sequence[str], allowed: Sequence[str],
                       expected_seq: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """工具调用准确率: (1) 越界率 (调用不在 allow-list) (2) 与期望序列的 Jaccard。"""
    allowed_set = set(allowed)
    out_of_allow = [t for t in predicted_seq if t not in allowed_set]
    res: Dict[str, Any] = {
        "n_calls": len(predicted_seq),
        "out_of_allowlist": out_of_allow,
        "allowlist_compliance": round(1 - len(out_of_allow) / len(predicted_seq), 4) if predicted_seq else 1.0,
    }
    if expected_seq is not None:
        a, b = set(predicted_seq), set(expected_seq)
        union = a | b
        res["jaccard_vs_expected"] = round(len(a & b) / len(union), 4) if union else 1.0
        res["exact_seq_match"] = list(predicted_seq) == list(expected_seq)
    return res


def ablation_report(base: Dict[str, Any], variants: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """消融: 各 variant 相对 base 的指标 delta (如 去RAG / 去护栏)。"""
    out: Dict[str, Any] = {"base": base, "variants": {}}
    for name, v in variants.items():
        delta = {}
        for k in ("task_completion", "field_accuracy", "hitl_rate", "blocked_rate"):
            if k in base and k in v and isinstance(base[k], (int, float)) and isinstance(v[k], (int, float)):
                delta[k] = round(v[k] - base[k], 4)
        out["variants"][name] = {"metrics": v, "delta_vs_base": delta}
    return out


def ab_report(a: Dict[str, Any], b: Dict[str, Any], a_name: str = "A", b_name: str = "B") -> Dict[str, Any]:
    """A/B 对比 (如 正则抽取 vs LLM 抽取)。"""
    comp = {}
    for k in ("field_accuracy", "task_completion", "avg_latency_ms"):
        if k in a and k in b and isinstance(a[k], (int, float)) and isinstance(b[k], (int, float)):
            comp[k] = {a_name: a[k], b_name: b[k], "delta_B_minus_A": round(b[k] - a[k], 4)}
    winner = None
    if "field_accuracy" in comp:
        winner = b_name if comp["field_accuracy"]["delta_B_minus_A"] > 0 else (
            a_name if comp["field_accuracy"]["delta_B_minus_A"] < 0 else "tie")
    return {"comparison": comp, "field_accuracy_winner": winner}


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把逐场景行聚合成报告。"""
    n = len(rows)
    if not n:
        return {"n": 0}
    fa = [r["field_accuracy"] for r in rows if r.get("field_accuracy") is not None]
    return {
        "n": n,
        "task_completion": task_completion_rate(rows)["rate"],
        "field_accuracy": round(sum(fa) / len(fa), 4) if fa else None,
        "hitl_rate": round(sum(1 for r in rows if r.get("verification_status") == "HITL") / n, 4),
        "blocked_rate": round(sum(1 for r in rows if r.get("verification_status") == "BLOCKED") / n, 4),
        "done_rate": round(sum(1 for r in rows if r.get("state") == "DONE") / n, 4),
    }


# ---------------- 需引擎的评估运行器 ----------------
def evaluate_controller(ctrl, eval_set: List[Dict[str, Any]]) -> Dict[str, Any]:
    """跑评估集, 产出逐场景行 + 聚合报告 (需制造内核)。"""
    rows: List[Dict[str, Any]] = []
    for case in eval_set:
        r = ctrl.run(email_text=case["email"], customer=case.get("customer"),
                     voice_transcript=case.get("voice_transcript"))
        gold = case.get("expected_rfq", {})
        # 从 context 取实际抽取的 rfq
        pred_rfq = {}
        ctx = ctrl.ctx_engine.get(r["context_id"])
        if ctx is not None:
            pred_rfq = ctx.rfq
        fa = field_accuracy(pred_rfq, gold)["accuracy"] if gold else None
        rows.append({
            "id": case.get("id"), "state": r["state"], "expect_state": case.get("expect_state"),
            "verification_status": r["verification_status"], "expect_status": case.get("expect_status"),
            "field_accuracy": fa,
            "unit_price": (r.get("quote") or {}).get("unit_price"),
            "engine_source": r.get("engine_source"),
        })
    return {"rows": rows, "report": aggregate(rows),
            "task_completion": task_completion_rate(rows)}


def load_eval_set(path: Optional[str] = None) -> List[Dict[str, Any]]:
    p = Path(path) if path else _ROOT / "data" / "eval_set.json"
    return json.loads(p.read_text(encoding="utf-8"))["cases"]
