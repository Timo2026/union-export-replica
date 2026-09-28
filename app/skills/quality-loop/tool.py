"""quality-loop skill tool — v5.0.0 Loop 自迭代评分.

被 services.skill_dispatcher 通过 skills/_runtime 自动发现注册.
"""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, expert_results: Dict[str, Any] = None, synthesis: str = "",
        critique_text: str = "", loop_count: int = 0, **kwargs) -> Dict[str, Any]:
    """评分 + 决定下一步.

    Args:
        ctx: SkillContext (来自 dispatcher)
        expert_results: {agent_name: {score, analysis/explanation}} 字典
        synthesis: Orchestrator 综合结论 (可选)
        critique_text: LLM critic 评分文本 (可选, 含 "评分: X/100")
        loop_count: 已 Loop 次数 (0-2)

    Returns:
        {ok, skill, score, weak_agents, action, feedback_reason, iron_rule}
    """
    from services.quality_scorer import evaluate_quality, QUALITY_THRESHOLD, MAX_LOOPS

    if expert_results is None:
        return {"ok": False, "skill": "quality-loop", "iron_rule": "deterministic",
                "error": "expert_results required"}

    verdict = evaluate_quality(
        expert_results=expert_results,
        synthesis=synthesis,
        critique_text=critique_text,
        loop_count=loop_count,
    )
    out = verdict.to_dict()
    out.update({
        "ok": True,
        "skill": "quality-loop",
        "iron_rule": "deterministic",
        "threshold": QUALITY_THRESHOLD,
        "max_loops": MAX_LOOPS,
        "next_loop_count": loop_count + (1 if verdict.action == "loop" else 0),
    })
    # 落 audit (铁律① 守护: deterministic)
    try:
        ctrl = ctx.get_ctrl() if hasattr(ctx, "get_ctrl") else None
        if ctrl is not None and hasattr(ctrl, "audit"):
            ctrl.audit.log("quality_loop",
                           {"score": verdict.score, "action": verdict.action,
                            "weak": verdict.weak_agents, "loop_count": loop_count},
                           actor="quality-loop")
    except Exception:
        pass
    return out
