"""auto_threshold.py — v2.3.0 自动报价阈值判定（叠加非替换）。

判定规则：features_count<10 && process_route_steps<10 → AUTO。
  - 几何特征数：来自 step-analysis 的 C1 特征（hole_count + 其他）
  - 工艺路线步数：来自报价内核的 process_route 字段

契约：与现有 HITL 门禁（IT4/IT5/毛利/金额/缺失/多模态）叠加；任一不满足仍 HITL。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from services.config import load_policy

_DEFAULT_FEATURES_MAX = 10
_DEFAULT_ROUTE_MAX = 10


@dataclass(frozen=True)
class AutoThresholdConfig:
    features_count_max: int
    process_route_max: int


def load_auto_threshold(policy: Optional[Dict[str, Any]] = None) -> AutoThresholdConfig:
    p = policy or load_policy()
    section = p.get("auto_quote_threshold", {}) if isinstance(p, dict) else {}
    return AutoThresholdConfig(
        features_count_max=int(section.get("features_count_max", _DEFAULT_FEATURES_MAX)),
        process_route_max=int(section.get("process_route_max", _DEFAULT_ROUTE_MAX)),
    )


def should_auto_quote(
    features_count: Optional[int] = None,
    process_route_count: Optional[int] = None,
    cfg: Optional[AutoThresholdConfig] = None,
) -> bool:
    """严格小于阈值才 AUTO；缺省按 0 视作不阻断。"""
    cfg = cfg or load_auto_threshold()
    f = features_count if features_count is not None else 0
    r = process_route_count if process_route_count is not None else 0
    return f < cfg.features_count_max and r < cfg.process_route_max