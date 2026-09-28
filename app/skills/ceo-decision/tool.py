"""ceo-decision skill tool — v5.0.0 CEO 智能决策引擎 (简化版, 离线可跑).

完整版 (ceo_engine.py 78KB) 在 skills_extracted, 含多模型蜂群 + 墨家五证 + 5 联动集成.
本实现核心 5 证 + 投票 + 阈值决策, LLM 在线可扩展润色 reasoning.
"""
from __future__ import annotations

from typing import Any, Dict, List


# 5 证权重 (加权和 = 1.0)
_WEIGHTS = {
    "acceptance": 0.25,
    "history": 0.15,
    "margin": 0.25,
    "dfm": 0.20,
    "completeness": 0.15,
}


def _score_acceptance(ctx: Dict[str, Any]) -> int:
    quote = ctx.get("quote", {})
    total = quote.get("total_single", 0) or quote.get("total_batch", 0)
    if total >= 10000:
        return 80
    if total >= 5000:
        return 60
    if total > 0:
        return 40
    return 20  # 没报价


def _score_history(ctx: Dict[str, Any]) -> int:
    cust = ctx.get("customer", {})
    if cust.get("is_new"):
        return 50
    won = cust.get("won_count", 0)
    lost = cust.get("lost_count", 0)
    if lost >= 2:
        return 30
    if won >= 3:
        return 80
    if won >= 1:
        return 65
    return 50


def _score_margin(ctx: Dict[str, Any]) -> int:
    margin = ctx.get("margin_pct", 0)
    if margin >= 25:
        return 90
    if margin >= 20:
        return 75
    if margin >= 15:
        return 70
    if margin >= 10:
        return 50
    return 30


def _score_dfm(ctx: Dict[str, Any]) -> int:
    verif = ctx.get("verification", {})
    conflicts = verif.get("conflicts", []) or []
    if len(conflicts) == 0:
        return 90
    if len(conflicts) == 1:
        return 60
    return 30


def _score_completeness(ctx: Dict[str, Any]) -> int:
    missing = ctx.get("missing", 0) or 0
    if missing == 0:
        return 90
    if missing <= 2:
        return 70
    if missing <= 4:
        return 50
    return 30


def _decide(votes: Dict[str, int], threshold: int) -> str:
    avg = sum(votes.values()) / max(len(votes), 1)
    if avg >= threshold:
        return "accept"
    if avg < 40:
        return "reject"
    return "defer"


def _build_reasoning(votes: Dict[str, int], avg: float, decision: str,
                     context: Dict[str, Any]) -> List[str]:
    """返人类可读 reasoning."""
    rs = [f"5 证综合 {avg:.1f}/100"]
    cust = context.get("customer", {})
    if cust.get("is_new"):
        rs.append(f"客户为新客, 历史信号中性")
    elif cust.get("won_count", 0) >= 3:
        rs.append(f"客户老客, {cust.get('won_count')} 次合作 won")
    margin = context.get("margin_pct", 0)
    rs.append(f"毛利 {margin}%")
    n_conflicts = len(context.get("verification", {}).get("conflicts", []))
    rs.append(f"DFM 冲突 {n_conflicts} 条")
    if decision == "accept":
        rs.append(f"≥ 阈值 {context.get('threshold', 70)}, 建议接单")
    elif decision == "reject":
        # 列出 < 50 的证
        weak = [k for k, v in votes.items() if v < 50]
        rs.append(f"< 40, 建议拒单 (弱项: {', '.join(weak) or '无'})")
    else:
        weak = [k for k, v in votes.items() if v < 70]
        rs.append(f"40-阈值, 建议 defer 待审 (待强项: {', '.join(weak) or '无'})")
    return rs


def run(ctx, decision_context: Dict[str, Any] = None, threshold: float = 70,
        **kwargs) -> Dict[str, Any]:
    """CEO 决策: 5 证评分 + 投票 + 阈值."""
    if decision_context is None:
        return {"ok": False, "skill": "ceo-decision", "iron_rule": "llm_proposal",
                "error": "decision_context required"}

    threshold = float(threshold)

    # 5 证评分 (mock 离线可跑, LLM 在线可润色)
    votes = {
        "acceptance": _score_acceptance(decision_context),
        "history": _score_history(decision_context),
        "margin": _score_margin(decision_context),
        "dfm": _score_dfm(decision_context),
        "completeness": _score_completeness(decision_context),
    }
    avg = sum(votes[k] * _WEIGHTS[k] for k in votes) * 1.0  # 加权
    decision = _decide(votes, threshold)
    reasoning = _build_reasoning(votes, avg, decision, decision_context)

    # LLM 在线扩展: 润色 reasoning (此处保留 mock, 未来接 planner)
    try:
        ctrl = ctx.get_ctrl() if hasattr(ctx, "get_ctrl") else None
        if ctrl is not None and getattr(ctrl, "planner", None) is not None and ctrl.planner.online():
            # 未来: prompt = "基于以下 5 证评分, 润色决策解释: ..." → 调 LLMPlanner
            pass  # 不阻塞主链
    except Exception:
        pass

    return {
        "ok": True,
        "skill": "ceo-decision",
        "iron_rule": "llm_proposal",
        "decision": decision,
        "confidence": round(avg, 1),
        "threshold": threshold,
        "votes": votes,
        "reasoning": reasoning,
        "source": "mock",  # 离线 mock; 未来 LLM 在线时改 "llm"
    }
