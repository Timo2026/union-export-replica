"""fleet-coordinator skill tool — v5.0.0 fleet_v4 适配器入口.

被 services.skill_dispatcher.SkillDispatcher 通过 skills._runtime.discover() 自动注册.
"""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, material: str = "6061", shape: str = "bushing",
        dimensions: Dict[str, Any] = None, quantity: int = 1,
        surface: str = "none", mode: str = "fast_path", **kwargs) -> Dict[str, Any]:
    """fleet-coordinator skill run.

    Args:
        ctx: SkillContext (含 ctrl/policy/dispatch_id, 由 _runtime 注入)
        material: 材料牌号 (6061/7075/304/carbon_steel)
        shape: 零件形状 (flange/bushing/block)
        dimensions: 尺寸字典 (mm), 按 shape 不同字段:
            - flange: outer_d/inner_d/thickness (可选 holes)
            - bushing: outer_d/inner_d/length (可选 holes)
            - block: width/height/thickness (可选 holes)
        quantity: 数量
        surface: 表面处理 (none/anodizing/pvd/spray/electroplating)
        mode: fast_path (仅计算) / expert_path (计算+3 专家+Orchestrator+Critic)

    Returns:
        标准 skill envelope: {ok, skill, calculation, iron_rule, _latency_ms, _source}
    """
    from services.fleet_v4 import FleetCoordinatorV4Adapter

    if dimensions is None:
        return {"ok": False, "skill": "fleet-coordinator", "iron_rule": "deterministic",
                "error": "dimensions required", "_source": "fleet_v4.adapter"}

    # 落审计 (iron-rule-1 守护: deterministic)
    audit_tag = f"fleet_v4.{mode}"
    try:
        ctrl = ctx.get_ctrl() if hasattr(ctx, "get_ctrl") else None
        if ctrl is not None and hasattr(ctrl, "audit"):
            ctrl.audit.log("fleet_v4_quote",
                           {"material": material, "shape": shape, "quantity": quantity,
                            "surface": surface, "mode": mode, "dispatch_id": ctx.dispatch_id},
                           actor="fleet-coordinator")
    except Exception:
        pass  # audit 失败不阻塞

    adapter = FleetCoordinatorV4Adapter(mode=mode)
    result = adapter.run_quote(
        material=material, shape=shape, dimensions=dimensions,
        quantity=quantity, surface=surface,
    )
    # iron-rule-1 标记: 即使 expert_path 也保护 calculation 不被 LLM 改写
    result.setdefault("iron_rule", "deterministic")
    result.setdefault("skill", "fleet-coordinator")
    return result
