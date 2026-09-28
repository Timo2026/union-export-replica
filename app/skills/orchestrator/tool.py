"""orchestrator skill tool — v5.0.0 编排器 (plan 生成).

被 services.skill_dispatcher 通过 skills/_runtime 自动发现.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKFLOWS_DIR = Path(__file__).resolve().parent / "workflows"


# ---- 4 个预定义 workflow (YAML 简化 JSON) ----
DEFAULT_WORKFLOWS: Dict[str, List[Dict[str, Any]]] = {
    "flange_quote": [
        {"step": 1, "skill": "parse_rfq", "args": {"email_text": "$request"}},
        {"step": 2, "skill": "check_dfm", "args": {"rfq": "$rfq"}},
        {"step": 3, "skill": "fleet_coordinator", "args": {"shape": "flange", "dimensions": "$dimensions"}},
        {"step": 4, "skill": "verify_gate", "args": {"ctx_dict": "$ctx"}},
        {"step": 5, "skill": "write_reply", "args": {"use_llm": False}},
        {"step": 6, "skill": "quality_loop", "args": {"expert_results": "$experts", "loop_count": 0}},
    ],
    "shaft_sleeve_quote": [
        {"step": 1, "skill": "parse_rfq", "args": {"email_text": "$request"}},
        {"step": 2, "skill": "check_dfm", "args": {"rfq": "$rfq"}},
        {"step": 3, "skill": "fleet_coordinator", "args": {"shape": "bushing", "dimensions": "$dimensions"}},
        {"step": 4, "skill": "verify_gate", "args": {"ctx_dict": "$ctx"}},
        {"step": 5, "skill": "write_reply", "args": {"use_llm": False}},
        {"step": 6, "skill": "quality_loop", "args": {"expert_results": "$experts", "loop_count": 0}},
    ],
    "rectangular_quote": [
        {"step": 1, "skill": "parse_rfq", "args": {"email_text": "$request"}},
        {"step": 2, "skill": "check_dfm", "args": {"rfq": "$rfq"}},
        {"step": 3, "skill": "fleet_coordinator", "args": {"shape": "block", "dimensions": "$dimensions"}},
        {"step": 4, "skill": "verify_gate", "args": {"ctx_dict": "$ctx"}},
        {"step": 5, "skill": "write_reply", "args": {"use_llm": False}},
    ],
    "general_quote": [
        {"step": 1, "skill": "chat_understand", "args": {"intent": "$request"}},
        {"step": 2, "skill": "rag_recall", "args": {"query": "$request"}},
        {"step": 3, "skill": "skill_dispatch", "args": {"request": "$request"}},
    ],
}


def load_workflow(name: str) -> Optional[List[Dict[str, Any]]]:
    """从 workflows/<name>.yaml 加载, 不存在则 fallback 默认."""
    yml = _WORKFLOWS_DIR / f"{name}.yaml"
    if yml.exists():
        try:
            import yaml
            return yaml.safe_load(yml.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_WORKFLOWS.get(name)


def keyword_plan(request: str) -> List[Dict[str, Any]]:
    """关键词路由 (无 LLM 时的 fallback)."""
    plan: List[Dict[str, Any]] = []
    text = request.lower()

    # 报价意图 (含中文常用变体)
    quote_keywords = ["报价", "quote", "price", "多少钱", "报一下", "报个价", "报盘", "cost"]
    if any(kw in text for kw in quote_keywords):
        if "法兰" in text or "flange" in text:
            plan.append({"step": 1, "skill": "fleet_coordinator", "args": {"shape": "flange"}})
        elif "轴套" in text or "bushing" in text or "sleeve" in text:
            plan.append({"step": 1, "skill": "fleet_coordinator", "args": {"shape": "bushing"}})
        elif "长方" in text or "block" in text:
            plan.append({"step": 1, "skill": "fleet_coordinator", "args": {"shape": "block"}})
        else:
            # 通用报价: 不指定 shape, 让 fleet-coordinator 自适配
            plan.append({"step": 1, "skill": "fleet_coordinator", "args": {}})
        plan.append({"step": len(plan) + 1, "skill": "quality_loop", "args": {"loop_count": 0}})

    if any(kw in text for kw in ["dfm", "工艺", "可制造", "冲突"]):
        plan.insert(0, {"step": 1, "skill": "check_dfm", "args": {"rfq": "$rfq"}})

    if any(kw in text for kw in ["rfi", "询盘", "rfq", "邮件", "email"]):
        plan.insert(0, {"step": 1, "skill": "parse_rfq", "args": {"email_text": "$request"}})

    if any(kw in text for kw in ["黄金", "golden", "端到端", "e2e", "全流程"]):
        plan = load_workflow("flange_quote") or DEFAULT_WORKFLOWS["flange_quote"]

    if any(kw in text for kw in ["批准", "approve", "通过"]):
        plan.append({"step": len(plan) + 1, "skill": "approve_gate", "args": {"auto": True}})

    if not plan:
        # 默认: general_quote (LLM 路径)
        plan = DEFAULT_WORKFLOWS["general_quote"]

    return plan


def run(ctx, request: str = "", workflow_name: str = "",
        **kwargs) -> Dict[str, Any]:
    """编排: 返 plan, dispatcher 按 plan 顺序执行.

    不直接调 skill, 避免无限递归 (orchestrator → skill → orchestrator).
    """
    if not request:
        return {"ok": False, "skill": "orchestrator", "iron_rule": "llm_proposal",
                "error": "request required"}

    source = "workflow"
    plan: List[Dict[str, Any]] = []
    if workflow_name:
        plan = load_workflow(workflow_name) or []
    if not plan:
        plan = keyword_plan(request)
        source = "keyword"

    # LLM 升级路径 (可选): 若 planner 在线且 plan 为空 → 调 chat_understand
    try:
        ctrl = ctx.get_ctrl() if hasattr(ctx, "get_ctrl") else None
        if ctrl is not None and getattr(ctrl, "planner", None) is not None and ctrl.planner.online():
            # (简化) 直接采用 keyword_plan; 未来可用 planner 升级
            pass
    except Exception:
        pass

    return {
        "ok": True,
        "skill": "orchestrator",
        "iron_rule": "llm_proposal",
        "plan": plan,
        "plan_count": len(plan),
        "skill_sequence": [s["skill"] for s in plan],
        "source": source,
        "workflow_name": workflow_name or "(auto-keyword)",
    }
