"""test_evaluation.py — 评估体系 (metrics) + RAG 评测 (rag_eval) 纯函数测试 (维度 7.1/4.3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation import metrics as M
from evaluation import rag_eval as R

_ROOT = Path(__file__).resolve().parent.parent


# ---------------- metrics ----------------
def test_field_accuracy_full_and_partial():
    gold = {"material": "6061", "surface": "阳极氧化", "quantity": 50, "tolerance_grade": "IT7"}
    assert M.field_accuracy(gold, gold)["accuracy"] == 1.0
    pred = {"material": "6061", "surface": "无", "quantity": 50, "tolerance_grade": "IT7"}
    r = M.field_accuracy(pred, gold)
    assert r["accuracy"] == 0.75 and r["per_field"]["surface"] is False


def test_field_accuracy_case_insensitive():
    assert M.field_accuracy({"material": "tc4"}, {"material": "TC4"}, ["material"])["accuracy"] == 1.0


def test_quote_deviation():
    assert M.quote_deviation(115, 100) == {"abs": 15.0, "pct": 15.0}
    assert M.quote_deviation(None, 100)["pct"] is None
    assert M.quote_deviation(100, 0)["pct"] is None


def test_task_completion_rate():
    rows = [{"state": "DONE", "expect_state": "DONE", "verification_status": "PASS", "expect_status": "PASS"},
            {"state": "HITL", "expect_state": "DONE", "verification_status": "HITL", "expect_status": "PASS"}]
    assert M.task_completion_rate(rows)["rate"] == 0.5


def test_tool_call_accuracy_allowlist_and_jaccard():
    allowed = ["rfq-extraction", "dfm-conflict", "cnc-quote"]
    r = M.tool_call_accuracy(["rfq-extraction", "dfm-conflict", "rm-rf"], allowed,
                             expected_seq=["rfq-extraction", "dfm-conflict"])
    assert r["out_of_allowlist"] == ["rm-rf"]
    assert r["allowlist_compliance"] < 1.0
    assert r["jaccard_vs_expected"] == round(2 / 3, 4)   # 交2/并3


def test_ablation_and_ab_reports():
    base = {"task_completion": 1.0, "field_accuracy": 0.9, "hitl_rate": 0.2, "blocked_rate": 0.1}
    ab = M.ablation_report(base, {"no_rag": {"task_completion": 1.0, "field_accuracy": 0.75,
                                             "hitl_rate": 0.2, "blocked_rate": 0.1}})
    assert ab["variants"]["no_rag"]["delta_vs_base"]["field_accuracy"] == -0.15
    abr = M.ab_report({"field_accuracy": 0.80}, {"field_accuracy": 0.92}, "regex", "llm")
    assert abr["field_accuracy_winner"] == "llm"
    assert abr["comparison"]["field_accuracy"]["delta_B_minus_A"] == 0.12


def test_aggregate():
    rows = [{"state": "DONE", "expect_state": "DONE", "verification_status": "PASS",
             "expect_status": "PASS", "field_accuracy": 1.0},
            {"state": "ARCHIVED", "expect_state": "ARCHIVED", "verification_status": "BLOCKED",
             "expect_status": "BLOCKED", "field_accuracy": 1.0}]
    agg = M.aggregate(rows)
    assert agg["n"] == 2 and agg["task_completion"] == 1.0 and agg["blocked_rate"] == 0.5


def test_eval_set_loads():
    cases = M.load_eval_set()
    assert len(cases) >= 6
    assert all("expected_rfq" in c for c in cases)


# ---------------- rag_eval ----------------
def test_faithfulness_supported_answer():
    ctx = ["304/316L 不锈钢自然钝化, 不做阳极氧化, 推荐钝化或电解抛光。"]
    f = R.faithfulness("304 不锈钢不做阳极氧化, 推荐钝化", ctx)
    assert f["method"] == "lexical_proxy" and f["score"] > 0.5


def test_faithfulness_unsupported_low():
    ctx = ["铝合金适合阳极氧化。"]
    f = R.faithfulness("钛合金必须镀锌处理否则生锈", ctx)
    assert f["score"] < 0.5


def test_context_precision_ranks_relevant_first():
    q = "304 阳极氧化 冲突"
    good = R.context_precision(q, ["304 不锈钢不做阳极氧化", "无关的运费说明"])
    bad = R.context_precision(q, ["无关的运费说明", "304 不锈钢不做阳极氧化"])
    assert good["score"] >= bad["score"]


def test_context_recall_and_relevancy():
    ctx = ["钛合金 IT4/IT5 超常规 CNC 经济公差, 需精密磨削/慢走丝, 强制人工复核。"]
    assert R.context_recall("钛合金 IT5 需精密磨削 强制人工复核", ctx)["score"] > 0.5
    assert R.answer_relevancy("TC4 IT5 公差", "TC4 IT5 超经济公差需复核")["score"] >= 0


def test_evaluate_set_average_and_llm_judge_override():
    cases = json.loads((_ROOT / "data" / "eval_set.json").read_text(encoding="utf-8"))["rag_golden"]

    def retrieve(q):
        # 返回上下文字符串列表 (命中则用该样例的 context, 否则用首条)
        for c in cases:
            if any(tok in c["query"] for tok in q.split()):
                return list(c["context"])
        return list(cases[0]["context"])

    out = R.evaluate_set(cases, retrieve_fn=retrieve)
    assert out["n"] == len(cases)
    assert set(out["average"].keys()) == {"faithfulness", "context_precision", "context_recall", "answer_relevancy"}
    assert out["method"] == "lexical_proxy"
    assert out["average"]["faithfulness"] > 0          # 检索到正确上下文 → 答案被支撑

    # LLM judge 覆盖
    out2 = R.evaluate_set(cases, retrieve_fn=lambda q: ["x"], llm_judge=lambda *a: 0.99)
    assert out2["method"] == "llm_judge"
    assert out2["average"]["faithfulness"] == 0.99
