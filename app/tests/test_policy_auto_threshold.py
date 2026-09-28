"""test_policy_auto_threshold.py — v2.3.0 自动报价阈值。

契约：features_count<10 && process_route<10 → AUTO；其余 HITL（叠加非替换）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from supplier_module.auto_threshold import (
    should_auto_quote,
    load_auto_threshold,
    AutoThresholdConfig,
)


def test_should_auto_quote_below_threshold():
    cfg = AutoThresholdConfig(features_count_max=10, process_route_max=10)
    assert should_auto_quote(features_count=5, process_route_count=3, cfg=cfg) is True


def test_should_auto_quote_at_threshold_returns_false_strict():
    """严格小于（<），等于阈值不进 AUTO。"""
    cfg = AutoThresholdConfig(features_count_max=10, process_route_max=10)
    assert should_auto_quote(features_count=10, process_route_count=5, cfg=cfg) is False
    assert should_auto_quote(features_count=5, process_route_count=10, cfg=cfg) is False


def test_should_auto_quote_above_threshold_returns_false():
    cfg = AutoThresholdConfig(features_count_max=10, process_route_max=10)
    assert should_auto_quote(features_count=15, process_route_count=3, cfg=cfg) is False
    assert should_auto_quote(features_count=3, process_route_count=15, cfg=cfg) is False


def test_should_auto_quote_none_treated_as_zero():
    """features_count 缺省（None）按 0 处理（不阻断）。"""
    cfg = AutoThresholdConfig(features_count_max=10, process_route_max=10)
    assert should_auto_quote(features_count=None, process_route_count=3, cfg=cfg) is True


def test_should_auto_quote_uses_default_config_when_none():
    """不传 cfg → 用默认 10/10。"""
    assert should_auto_quote(features_count=5, process_route_count=3) is True
    assert should_auto_quote(features_count=20, process_route_count=3) is False


def test_should_auto_quote_default_loads_from_policy():
    cfg = load_auto_threshold()
    assert cfg.features_count_max >= 1
    assert cfg.process_route_max >= 1


def test_config_immutable():
    cfg = AutoThresholdConfig(features_count_max=10, process_route_max=10)
    with pytest.raises((AttributeError, Exception)):
        cfg.features_count_max = 20  # frozen dataclass