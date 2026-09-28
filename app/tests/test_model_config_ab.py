"""test_model_config_ab.py — v2.3.1 A/B 路由 + fallback 单元测试。

覆盖:
  - validate: ab_test/fallback 字段结构 + deterministic 不可 A/B
  - choose_route: primary_only / ab_hash / ab_round_robin / fallback 四种策略
  - choose_route: disabled / missing key / 不在线 (由调用方降级) 兜底
  - probe_all: 扩展 alternate / fallback 探活输出
  - hash 稳定: 同 request_id 同选; 不同 request_id 50% 分布
  - round_robin: counter 递增交替
"""
from __future__ import annotations

import pytest

from services.model_config import (
    choose_route,
    validate,
    probe_all,
    _hash_pick,
    _AB_STRATEGIES,
)


# ---------- 工具 ----------

def _entry(key="llm", **overrides):
    base = {
        "label": "LLM",
        "role": "REASON",
        "endpoint": "http://127.0.0.1:1234/v1",
        "model": "primary-model",
        "enabled": True,
        "probe_path": "/models",
    }
    base.update(overrides)
    return {"models": {key: base, "asr": {"endpoint": "http://127.0.0.1:9/v1", "model": "a"}}}


# ---------- validate ----------

def test_validate_accepts_ab_test_with_alternate_and_strategy():
    cfg = _entry(ab_test={
        "strategy": "ab_hash",
        "alternate": {"endpoint": "http://127.0.0.1:1235/v1", "model": "alt"},
    })
    assert validate(cfg) == []


def test_validate_rejects_ab_test_without_alternate_for_hash():
    cfg = _entry(ab_test={"strategy": "ab_hash"})
    errs = validate(cfg)
    assert any("alternate" in e for e in errs)


def test_validate_rejects_unknown_ab_strategy():
    cfg = _entry(ab_test={
        "strategy": "ab_random",
        "alternate": {"endpoint": "http://127.0.0.1:1235/v1", "model": "alt"},
    })
    errs = validate(cfg)
    assert any("ab_test.strategy" in e for e in errs)


def test_validate_requires_fallback_endpoint_and_model():
    cfg = _entry(fallback={"endpoint": "http://127.0.0.1:9/v1"})
    errs = validate(cfg)
    assert any("fallback 缺 model" in e for e in errs)


def test_validate_rejects_bad_scheme_in_alternate():
    cfg = _entry(ab_test={
        "strategy": "ab_hash",
        "alternate": {"endpoint": "tcp://nope", "model": "x"},
    })
    errs = validate(cfg)
    assert any("alternate.endpoint" in e for e in errs)


def test_validate_deterministic_cannot_have_ab_test():
    cfg = {
        "models": {
            "deterministic": {"endpoint": "http://x", "model": "y", "enabled": True},
        }
    }
    cfg["models"]["deterministic"]["ab_test"] = {
        "strategy": "ab_hash",
        "alternate": {"endpoint": "http://y", "model": "z"},
    }
    errs = validate(cfg)
    assert any("不可配置 ab_test/fallback" in e for e in errs)


def test_validate_deterministic_cannot_have_fallback():
    cfg = {
        "models": {
            "deterministic": {"endpoint": "http://x", "model": "y", "enabled": True,
                              "fallback": {"endpoint": "http://z", "model": "z"}},
        }
    }
    errs = validate(cfg)
    assert any("不可配置 ab_test/fallback" in e for e in errs)


def test_ab_strategies_constant_complete():
    assert set(_AB_STRATEGIES) == {"primary_only", "fallback", "ab_hash", "ab_round_robin"}


# ---------- choose_route: primary_only ----------

def test_choose_route_primary_only_returns_primary():
    cfg = _entry()
    d = choose_route("llm", cfg=cfg)
    assert d["source"] == "primary"
    assert d["strategy"] == "primary_only"
    assert d["endpoint"] == "http://127.0.0.1:1234/v1"
    assert d["model"] == "primary-model"
    assert d["selected"]["endpoint"] == d["endpoint"]


# ---------- choose_route: ab_hash ----------

def test_choose_route_ab_hash_stable_for_same_request_id():
    cfg = _entry(ab_test={
        "strategy": "ab_hash",
        "alternate": {"endpoint": "http://127.0.0.1:1235/v1", "model": "alt"},
    })
    d1 = choose_route("llm", cfg=cfg, request_id="req-42")
    d2 = choose_route("llm", cfg=cfg, request_id="req-42")
    assert d1["source"] == d2["source"]
    assert d1["endpoint"] == d2["endpoint"]


def test_choose_route_ab_hash_distributes_across_many_ids():
    """50 个不同 request_id 应该 primary/alternate 都有命中 (允许一边多但不能一边 0)。"""
    cfg = _entry(ab_test={
        "strategy": "ab_hash",
        "alternate": {"endpoint": "http://127.0.0.1:1235/v1", "model": "alt"},
    })
    hits = {"primary": 0, "alternate": 0}
    for i in range(50):
        d = choose_route("llm", cfg=cfg, request_id=f"req-{i}")
        hits[d["source"]] += 1
    assert hits["primary"] > 0
    assert hits["alternate"] > 0


# ---------- choose_route: ab_round_robin ----------

def test_choose_route_ab_round_robin_alternates():
    cfg = _entry(ab_test={
        "strategy": "ab_round_robin",
        "alternate": {"endpoint": "http://127.0.0.1:1235/v1", "model": "alt"},
    })
    rr = {}
    seq = [choose_route("llm", cfg=cfg, round_robin_counter=rr)["source"]
           for _ in range(6)]
    assert seq == ["primary", "alternate", "primary", "alternate", "primary", "alternate"]
    assert rr["llm"] == 6


# ---------- choose_route: fallback 策略 ----------

def test_choose_route_fallback_strategy_returns_primary_and_fallback():
    """strategy='fallback' 时 selected=primary, 同时暴露顶层 fallback 给调用方降级。"""
    cfg = _entry(
        ab_test={"strategy": "fallback"},
        fallback={"endpoint": "http://127.0.0.1:9999/v1", "model": "fb"},
    )
    d = choose_route("llm", cfg=cfg)
    assert d["strategy"] == "fallback"
    assert d["source"] == "primary"
    assert d["endpoint"] == "http://127.0.0.1:1234/v1"
    assert d["fallback"]["endpoint"] == "http://127.0.0.1:9999/v1"


# ---------- choose_route: 边界 ----------

def test_choose_route_missing_key_returns_source_missing():
    d = choose_route("nonexistent", cfg={"models": {}})
    assert d["source"] == "missing"
    assert d["endpoint"] is None


def test_choose_route_disabled_returns_source_disabled():
    cfg = _entry(enabled=False)
    d = choose_route("llm", cfg=cfg)
    assert d["source"] == "disabled"


def test_choose_route_no_ab_config_falls_back_to_primary_only():
    """未配置 ab_test/fallback, 应走 primary_only 默认。"""
    cfg = _entry()
    d = choose_route("llm", cfg=cfg)
    assert d["strategy"] == "primary_only"


# ---------- _hash_pick ----------

def test_hash_pick_returns_0_or_1():
    for i in range(20):
        assert _hash_pick("llm", f"req-{i}") in (0, 1)


def test_hash_pick_stable_for_same_input():
    a = _hash_pick("llm", "fixed-request")
    b = _hash_pick("llm", "fixed-request")
    assert a == b


# ---------- probe_all 扩展 ----------

def test_probe_all_includes_alternate_and_fallback(monkeypatch):
    """当 entry 配置了 ab_test.alternate + fallback, probe_all 输出应包含 alternate/fallback 子项。"""
    from services import model_config as mc
    cfg = {
        "models": {
            "llm": {
                "label": "LLM",
                "role": "REASON",
                "endpoint": "http://127.0.0.1:1/v1",  # 不通 → 离线
                "model": "p",
                "enabled": True,
                "probe_path": "/models",
                "ab_test": {
                    "strategy": "ab_hash",
                    "alternate": {"endpoint": "http://127.0.0.1:2/v1", "model": "a"},
                },
                "fallback": {"endpoint": "http://127.0.0.1:3/v1", "model": "f"},
            }
        }
    }
    # 桩 probe_one 避免真探活
    monkeypatch.setattr(mc, "probe_one",
                        lambda entry, timeout=4.0: {"online": False, "latency_ms": None,
                                                   "url": entry.get("endpoint")})
    out = probe_all(cfg=cfg, timeout=1.0)
    llm = out["llm"]
    assert llm["online"] is False
    assert "alternate" in llm
    assert llm["alternate"]["strategy"] == "ab_hash"
    assert llm["alternate"]["endpoint"] == "http://127.0.0.1:2/v1"
    assert llm["fallback"]["endpoint"] == "http://127.0.0.1:3/v1"


def test_probe_all_no_alternate_when_ab_test_absent(monkeypatch):
    from services import model_config as mc
    cfg = {"models": {"llm": {"endpoint": "http://127.0.0.1:1/v1", "model": "p",
                               "enabled": True, "probe_path": "/models"}}}
    monkeypatch.setattr(mc, "probe_one",
                        lambda entry, timeout=4.0: {"online": False, "latency_ms": None})
    out = probe_all(cfg=cfg, timeout=1.0)
    assert "alternate" not in out["llm"]
    assert "fallback" not in out["llm"]
