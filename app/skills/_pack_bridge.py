"""_pack_bridge.py — pack skill 在 skills/_runtime 中的注册入口.

这些 id 不在 skills/*/tool.py 磁盘目录, 通过 adapters.skill_pack_adapter 执行.
iron_rule 一律 llm_proposal 或 deterministic(lookup); 终价仍归 Timo calc_quote.
"""
from __future__ import annotations

from typing import Any, Dict

from skills._runtime import register_function


@register_function(
    "unionskill-quote-bridge",
    iron_rule="llm_proposal",
    openshell_policy=["skill-allowlist", "hitl-required"],
)
def unionskill_quote_bridge(ctx=None, **args) -> Dict[str, Any]:
    from adapters.skill_pack_adapter import run
    return run(ctx, skill_id="unionskill-quote-bridge", **args)


@register_function(
    "reference-quote-bridge",
    iron_rule="llm_proposal",
    openshell_policy=["skill-allowlist"],
)
def reference_quote_bridge(ctx=None, **args) -> Dict[str, Any]:
    from adapters.skill_pack_adapter import run
    return run(ctx, skill_id="reference-quote-bridge", **args)


@register_function(
    "ceo-decision-cb-bridge",
    iron_rule="llm_proposal",
    openshell_policy=["skill-allowlist"],
)
def ceo_decision_cb_bridge(ctx=None, **args) -> Dict[str, Any]:
    from adapters.skill_pack_adapter import run
    return run(ctx, skill_id="ceo-decision-cb-bridge", **args)


@register_function(
    "reid-os-bridge",
    iron_rule="llm_proposal",
    openshell_policy=["skill-allowlist"],
)
def reid_os_bridge(ctx=None, **args) -> Dict[str, Any]:
    from adapters.skill_pack_adapter import run
    return run(ctx, skill_id="reid-os-bridge", **args)


@register_function(
    "knowledge-index-lookup",
    iron_rule="deterministic",
    openshell_policy=["local-only", "skill-allowlist"],
)
def knowledge_index_lookup(ctx=None, **args) -> Dict[str, Any]:
    from adapters.skill_pack_adapter import run_lookup
    return run_lookup(ctx, **args)
