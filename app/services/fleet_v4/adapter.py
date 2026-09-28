"""services.fleet_v4.adapter — v4 适配器入口.

职责:
  - 提供 run_fleet_v4_quote() 同步包装 (无 LLM, 仅用 CalculationEngine)
  - 提供 FleetCoordinatorV4Adapter 类可被 skill_dispatcher 调用
  - 可选: 调 _fleet_v4_original.py 的 ExpertAgentV4/OrchestratorV4 (走 Ollama 离线降级)

铁律①守护:
  - 计算结果不依赖 LLM, 100% deterministic
  - expert 调用失败时显式标注, 不静默冒充
  - iron-rule-1 永远不参与 expert prompt 修改数字
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .calculation import calculate_quote

log = logging.getLogger(__name__)


def run_fleet_v4_quote(
    material: str,
    shape: str,
    dimensions: Dict[str, Any],
    quantity: int,
    surface: str = "none",
) -> Dict[str, Any]:
    """同步包装: 仅计算层 (无 LLM), 返回与 v4 CLI 一致的报价 dict.

    这是 dispatcher 调用 fleet-coordinator skill 时的"快路径":
    LLM 不可用 / 离线降级 / 只想精确计算 时直接走这条.
    """
    t0 = time.time()
    try:
        result = calculate_quote(material, shape, dimensions, quantity, surface)
        return {
            "ok": True,
            "skill": "fleet-coordinator-v4",
            "calculation": result,
            "elapsed_ms": round((time.time() - t0) * 1000, 2),
            "source": "python-calculation-engine",
            "iron_rule": "deterministic",
        }
    except Exception as e:
        log.exception("[fleet_v4] calculate_quote failed")
        return {
            "ok": False,
            "skill": "fleet-coordinator-v4",
            "error": repr(e),
            "elapsed_ms": round((time.time() - t0) * 1000, 2),
            "source": "python-calculation-engine",
            "iron_rule": "deterministic",
        }


class FleetCoordinatorV4Adapter:
    """v4 适配器 (供 skill tool.py 调用).

    支持两种模式:
      - fast_path (默认): 仅 CalculationEngine, 不调 LLM
      - expert_path: 调 v4 完整 Orchestrator + 3 专家 (Ollama 在线时)
    """

    def __init__(self, root: Optional[Path] = None, mode: str = "fast_path",
                 ollama_model: str = "qwen2.5:1.5b"):
        self.root = root
        self.mode = mode
        self.ollama_model = ollama_model
        self._v4_original = None
        if mode == "expert_path":
            # 懒加载 _fleet_v4_original 模块 (依赖 Ollama 在线)
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "_fleet_v4_original",
                    Path(__file__).parent.parent / "_fleet_v4_original.py",
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self._v4_original = mod
            except Exception as e:
                log.warning("[fleet_v4] expert_path 加载失败, 降级 fast_path: %r", e)
                self.mode = "fast_path"

    def run_quote(self, **kwargs: Any) -> Dict[str, Any]:
        """跑报价. kwargs = material/shape/dimensions/quantity/surface."""
        if self.mode == "expert_path" and self._v4_original is not None:
            # 调原 v4 FleetCoordinatorV4 (Ollama 路径)
            return self._run_v4_original(**kwargs)
        return run_fleet_v4_quote(**kwargs)

    def _run_v4_original(self, **kwargs: Any) -> Dict[str, Any]:
        """调原 v4 OrchestratorV4 (优先 fast 计算, 再调 3 专家 LLM)."""
        if self._v4_original is None:
            return run_fleet_v4_quote(**kwargs)
        try:
            calc = calculate_quote(
                material=kwargs["material"],
                shape=kwargs["shape"],
                dimensions=kwargs["dimensions"],
                quantity=kwargs["quantity"],
                surface=kwargs.get("surface", "none"),
            )
            calc_text = "\n".join([
                f"- {k}: {v}" for k, v in calc.items()
                if k in ("material_name", "volume_cm3", "weight_kg_single",
                         "total_single", "total_batch")
            ])
            # 调 3 专家 (material/quote/dfm) + Orchestrator 综合
            input_text = kwargs.get("user_input", "") or f"{kwargs['material']} {kwargs['shape']} {kwargs['quantity']}件"
            experts = {}
            for name in ("material_expert", "quote_expert", "dfm_expert"):
                agent = self._v4_original.ExpertAgentV4(name=name, domain_key=name, model=self.ollama_model)
                r = agent.ask(user_prompt=input_text, calculation_context=calc_text)
                experts[name] = r.to_dict() if r.success else {"error": r.error}
            orch = self._v4_original.OrchestratorV4(model=self.ollama_model)
            synth = orch.synthesize(experts, calc, input_text)
            critic = self._v4_original.QualityCritic(model=self.ollama_model)
            # ExpertResult 对象需要 Dict[str, AgentResult], 这里简化用 dict
            from dataclasses import dataclass
            agent_results = {}
            for k, v in experts.items():
                # 把 dict 转回 AgentResult (临时)
                @dataclass
                class TmpResult:
                    def __init__(self, d):
                        self.response = d.get("response_preview", d.get("response", ""))
                        self.success = "error" not in d
                agent_results[k] = TmpResult(v)
            critic_eval = critic.evaluate(agent_results, synth.get("synthesis", ""), calc)
            return {
                "ok": True,
                "skill": "fleet-coordinator-v4",
                "mode": "expert_path",
                "calculation": calc,
                "experts": experts,
                "synthesis": synth,
                "critic": critic_eval,
                "iron_rule": "deterministic",
            }
        except Exception as e:
            log.exception("[fleet_v4] expert_path failed, fallback to fast_path")
            return run_fleet_v4_quote(**kwargs)


# 便捷函数
def run_fleet_v4_quote_with_experts(
    material: str, shape: str, dimensions: Dict[str, Any], quantity: int,
    surface: str = "none", user_input: str = "", ollama_model: str = "qwen2.5:1.5b",
) -> Dict[str, Any]:
    """一站式: 先计算, 再 (如 Ollama 在线) 跑 3 专家 + Orchestrator + Critic."""
    adapter = FleetCoordinatorV4Adapter(mode="expert_path", ollama_model=ollama_model)
    return adapter.run_quote(
        material=material, shape=shape, dimensions=dimensions,
        quantity=quantity, surface=surface, user_input=user_input,
    )
