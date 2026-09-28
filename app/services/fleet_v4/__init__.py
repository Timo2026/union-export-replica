"""services/fleet_v4/__init__.py — v5.0.0 复用 DGX_Spark 工业经验 v4 (FleetCoordinator).

从 UnionSkill-DFM-Quote-Agent-v1.0/fleet_coordinator_v4.py 抽取纯计算层与数据库,
包装为可被 dispatcher 调用的 skill.

原始 v4 是独立 CLI 程序 (unionskill_dfm_quote_agent.py), 本包只复用:
  - CalculationEngine (pure Python 几何/重量/费用计算, 零误差)
  - MATERIAL_DB / SURFACE_PRICE / MACHINING_RATE / GROSS_MARGIN (确定性数据库)
  - calculate_quote() (端到端报价)

专家 Agent (material/quote/dfm) 与 Orchestrator + Critic 的 Ollama 调用
保留在 _fleet_v4_original.py 完整实现, 可通过 services.fleet_v4.adapter.run_expert()
独立调用.
"""
from .calculation import (
    CalculationEngine,
    MATERIAL_DB,
    SURFACE_PRICE,
    MACHINING_RATE,
    GROSS_MARGIN,
    calculate_quote,
)
from .adapter import FleetCoordinatorV4Adapter, run_fleet_v4_quote

__all__ = [
    "CalculationEngine",
    "MATERIAL_DB",
    "SURFACE_PRICE",
    "MACHINING_RATE",
    "GROSS_MARGIN",
    "calculate_quote",
    "FleetCoordinatorV4Adapter",
    "run_fleet_v4_quote",
]
