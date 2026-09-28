"""services/quality_scorer.py — v5.0.0 L3 Loop 自迭代评分.

从 FleetCoordinator v4 (QualityCritic + OrchestratorV4) 抽取:
  - parse_score(critique_text) -> int (默认 60)
  - detect_weak_agents(critique_text, agent_names) -> List[str]
  - score_from_experts(expert_results) -> int (本地 fallback, 不依赖 LLM)
  - should_loop(score, loop_count, threshold=60, max_loops=2) -> bool
  - next_action(score, loop_count, ...) -> "loop" | "hitl" | "done"

铁律:
  - 评分阈值与原 v4 完全一致 (60 / max 2) — 与方案文档 §2 (Orchestrator + Loop) 对齐
  - score < 60 二次仍低 → 强制 HITL (不强行通过, 业务真相靠人工)
  - loop_count + scores[] + feedback_reason 写入 audit
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# 与原 FleetCoordinator v4 (DGX_Spark 方案 §2) 完全一致
QUALITY_THRESHOLD = 60
MAX_LOOPS = 2

# Critic Prompt 中常见的评分模式 (允许 -?\d+ 捕获负数)
_SCORE_PATTERNS = [
    re.compile(r"评分[:\s]*(-?\d+)\s*[/／]?\s*100", re.I),
    re.compile(r"score[:\s]*(-?\d+)", re.I),
    re.compile(r"质量[:\s]*(-?\d+)", re.I),
    re.compile(r"\b(-?\d{1,3})\s*/\s*100\b"),
]


def parse_score(text: str, default: int = 60) -> int:
    """从 critic 输出文本提取 0-100 分.

    原 v4 默认 60 (当 critic 没说分时). 我们沿用.
    负数 clamp 到 0; > 100 clamp 到 100.
    """
    if not text:
        return default
    for pat in _SCORE_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                v = int(m.group(1))
                # 负数 ("-5/100" → match 到 "5") clamp 到 0
                if v < 0:
                    return 0
                return min(v, 100)
            except (ValueError, IndexError):
                continue
    return default


def detect_weak_agents(critique_text: str, agent_names: List[str]) -> List[str]:
    """从 critic 输出识别薄弱专家.

    原 v4 逻辑: agent_name.lower() in critique_text.lower().
    改进: 增加 "weakness keyword" 邻近检测, 避免误判.
    """
    if not critique_text or not agent_names:
        return []
    lower = critique_text.lower()
    weak = []
    for name in agent_names:
        nlow = name.lower()
        if nlow in lower:
            # 启发式: 仅在 100 字符内有 "弱/差/不足/不完整/缺" 等关键词时算 weak
            idx = lower.find(nlow)
            context = lower[max(0, idx - 50): idx + 100]
            if any(kw in context for kw in ("弱", "差", "不足", "不完整", "缺", "weak", "poor", "missing")):
                weak.append(name)
    return weak


def score_from_experts(expert_results: Dict[str, Dict[str, Any]]) -> int:
    """本地 fallback 评分 (不依赖 LLM critic).

    策略: 取所有 expert 的 score 字段, 算加权平均 (material/price/dfm 各 1/3).
    若任一 expert score 缺失, 用 60 默认.
    """
    if not expert_results:
        return 60
    scores: List[int] = []
    for name, r in expert_results.items():
        if not isinstance(r, dict):
            continue
        s = r.get("score")
        if s is None:
            # 从 analysis / explanation 推断
            if "score" in str(r):
                # 嵌套
                s = r.get("analysis", {}).get("score") or r.get("explanation", {}).get("score")
        if isinstance(s, (int, float)):
            scores.append(int(s))
        else:
            scores.append(60)
    return sum(scores) // max(len(scores), 1)


def should_loop(score: int, loop_count: int, threshold: int = QUALITY_THRESHOLD,
               max_loops: int = MAX_LOOPS) -> bool:
    """是否需要 Loop 召回薄弱专家.

    条件: score < threshold AND loop_count < max_loops.
    """
    return score < threshold and loop_count < max_loops


def next_action(score: int, loop_count: int, threshold: int = QUALITY_THRESHOLD,
                max_loops: int = MAX_LOOPS) -> str:
    """返回下一步动作: 'loop' / 'hitl' / 'done'."""
    if score < threshold:
        if loop_count < max_loops:
            return "loop"
        else:
            return "hitl"  # 二次仍低 → 强制人工
    return "done"


@dataclass
class QualityVerdict:
    """单次评分结果."""
    score: int
    weak_agents: List[str] = field(default_factory=list)
    critique_text: str = ""
    loop_count: int = 0
    action: str = "done"  # loop / hitl / done
    feedback_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "weak_agents": list(self.weak_agents),
            "critique_text": self.critique_text,
            "loop_count": self.loop_count,
            "action": self.action,
            "feedback_reason": self.feedback_reason,
        }


def evaluate_quality(
    expert_results: Dict[str, Dict[str, Any]],
    synthesis: str = "",
    calc: Optional[Dict[str, Any]] = None,
    loop_count: int = 0,
    critique_text: str = "",
    threshold: int = QUALITY_THRESHOLD,
    max_loops: int = MAX_LOOPS,
) -> QualityVerdict:
    """综合评分 + 决定下一步.

    优先用 LLM critic 输出 (parse_score), 否则本地 fallback (score_from_experts).
    """
    if critique_text:
        score = parse_score(critique_text)
    else:
        score = score_from_experts(expert_results)

    agent_names = list(expert_results.keys())
    weak = detect_weak_agents(critique_text, agent_names) if critique_text else []
    if not weak and score < threshold:
        # LLM 没指出 weak 时, 启发式: 取 score 最低的 1 个
        sorted_by_score = sorted(
            [(n, r.get("score", 60) if isinstance(r, dict) else 60)
             for n, r in expert_results.items()],
            key=lambda x: x[1],
        )
        if sorted_by_score:
            weak = [sorted_by_score[0][0]]

    action = next_action(score, loop_count, threshold, max_loops)
    feedback = (
        f"评分 {score} 低于阈值 {threshold}, 召回薄弱专家 {weak or []}"
        if action == "loop"
        else f"评分 {score} 二次仍低, 强制 HITL (loop_count={loop_count})"
        if action == "hitl"
        else f"评分 {score} >= {threshold}, 通过"
    )
    return QualityVerdict(
        score=score,
        weak_agents=weak,
        critique_text=critique_text,
        loop_count=loop_count,
        action=action,
        feedback_reason=feedback,
    )
