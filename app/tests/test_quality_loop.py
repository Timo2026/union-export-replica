"""tests/test_quality_loop.py — T5: Loop 自迭代 (score < 60 召回) 4 用例.

覆盖:
  1. score >= 60 → action=done (不 Loop)
  2. score < 60 + loop_count=0 → action=loop + 召回 weak_agents
  3. score < 60 + loop_count=2 (max) → action=hitl (强制人工)
  4. 解析 critic 文本 "评分: 75/100" + 识别 "dfm 较弱"
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# 加载 quality-loop skill tool (绕过 namespace package)
def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "_test_quality_loop_tool",
        ROOT / "skills" / "quality-loop" / "tool.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run


run = _load_tool()


class FakeCtx:
    def get_ctrl(self): return None


# ---- 1. score >= 60 → done ----
def test_score_high_done() -> None:
    r = run(FakeCtx(), expert_results={
        "material": {"score": 80},
        "price": {"score": 75},
        "dfm": {"score": 65},
    }, loop_count=0)
    assert r["ok"] is True
    assert r["skill"] == "quality-loop"
    assert r["iron_rule"] == "deterministic"
    assert r["score"] >= 60
    assert r["action"] == "done"
    assert r["next_loop_count"] == 0


# ---- 2. score < 60 + loop_count=0 → loop + 召回 weak ----
def test_score_low_loop_with_weak() -> None:
    r = run(FakeCtx(), expert_results={
        "material": {"score": 80},
        "price": {"score": 70},
        "dfm": {"score": 30},  # 最低
    }, critique_text="评分: 55/100. dfm 较弱, 缺深孔分析", loop_count=0)
    assert r["score"] == 55
    assert r["action"] == "loop"
    assert "dfm" in r["weak_agents"]
    assert r["next_loop_count"] == 1
    assert "评分 55" in r["feedback_reason"]


# ---- 3. score < 60 + loop_count=2 → hitl (强制人工) ----
def test_score_low_hitl_after_max_loops() -> None:
    r = run(FakeCtx(), expert_results={
        "material": {"score": 40},
        "price": {"score": 50},
        "dfm": {"score": 35},
    }, loop_count=2)
    assert r["score"] < 60
    assert r["action"] == "hitl"  # 已达 max_loops
    assert r["next_loop_count"] == 2  # 不再 +1
    assert "强制 HITL" in r["feedback_reason"] or "二次仍低" in r["feedback_reason"]


# ---- 4. 解析 critic 文本 + 识别 weak ----
def test_parse_critique_and_detect_weak() -> None:
    from services.quality_scorer import parse_score, detect_weak_agents
    # parse_score
    assert parse_score("评分: 75/100") == 75
    assert parse_score("score: 80") == 80
    assert parse_score("质量 65 分") == 65
    assert parse_score("no score here") == 60  # 默认
    assert parse_score("") == 60
    assert parse_score("评分: 150/100") == 100  # clamp upper
    # 负数: pattern 匹配会抓到 "5" (跳过 "-" 字符), clamp 到 0
    assert parse_score("评分: -5/100") == 0
    assert parse_score("评分: -50/100") == 0

    # detect_weak_agents: 仅当 weak keyword 在 100 字符内时算 weak
    assert "material" not in detect_weak_agents("评分: 75. material 推荐 7075 替代", ["material", "price"])
    assert "material" in detect_weak_agents("评分: 40. material 弱, 推荐 7075 替代", ["material", "price"])
    assert detect_weak_agents("", ["material"]) == []


# ---- 5. 集成: services.quality_scorer 直接调用 ----
def test_evaluate_quality_direct() -> None:
    from services.quality_scorer import evaluate_quality
    # 高分 → done
    v = evaluate_quality({"material": {"score": 80}, "price": {"score": 80}}, loop_count=0)
    assert v.score == 80
    assert v.action == "done"
    # 低分 → loop
    v2 = evaluate_quality({"material": {"score": 80}, "dfm": {"score": 30}}, loop_count=0)
    assert v2.score < 60
    assert v2.action == "loop"
    assert "dfm" in v2.weak_agents
    # 二次仍低 → hitl
    v3 = evaluate_quality({"dfm": {"score": 30}}, loop_count=2)
    assert v3.action == "hitl"
