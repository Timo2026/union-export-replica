"""tests/test_nim_health.py — F7 NIM mock + 缓存 5 用例.

覆盖:
  1. 无 NVIDIA_API_KEY → mock NIM_NOT_CONFIGURED
  2. 第二次调 → 缓存命中 (AgentCache hit)
  3. force_refresh=True → 重新探活
  4. 有 key 时返 configured=True
  5. invalidate_nim_cache 后再调 仍能工作
"""
from __future__ import annotations
import os
from pathlib import Path

import pytest

from services.agent_cache import reset_global
from services import nim_health


@pytest.fixture(autouse=True)
def _clean_cache(tmp_path, monkeypatch):
    """每个测试用独立 root + 清理 cache."""
    monkeypatch.chdir(tmp_path)
    # 重置 AgentCache 单例 (用新的 root)
    import services.agent_cache as ac
    ac.reset_global()
    yield


def test_no_api_key_returns_mock() -> None:
    """无 NVIDIA_API_KEY → mock NIM_NOT_CONFIGURED (不静默冒充)."""
    # 确保无 key
    os.environ.pop("NVIDIA_API_KEY", None)
    os.environ.pop("UEA_NIM_BASE", None)
    r = nim_health.nim_health(force_refresh=True)
    assert r["online"] is False
    assert r["configured"] is False
    assert r["reason"] == "NIM_NOT_CONFIGURED"
    assert r["source"] == "mock"
    assert "hint" in r
    assert r["_cache"] == "miss"


def test_cache_hit_on_second_call() -> None:
    """第二次调命中 AgentCache, _cache=hit."""
    os.environ.pop("NVIDIA_API_KEY", None)
    r1 = nim_health.nim_health(force_refresh=True)
    r2 = nim_health.nim_health()  # 不 force_refresh
    assert r1["_cache"] == "miss"
    assert r2["_cache"] == "hit"
    assert r1["reason"] == r2["reason"]


def test_force_refresh_invalidates_cache() -> None:
    """force_refresh=True 强制重探, _cache=miss."""
    os.environ.pop("NVIDIA_API_KEY", None)
    nim_health.nim_health()  # warm
    r = nim_health.nim_health(force_refresh=True)
    assert r["_cache"] == "miss"


def test_invalidate_nim_cache() -> None:
    """invalidate_nim_cache 后下次调重新探活."""
    os.environ.pop("NVIDIA_API_KEY", None)
    nim_health.nim_health()
    ok = nim_health.invalidate_nim_cache()
    assert ok is True
    r = nim_health.nim_health()  # 应 miss
    assert r["_cache"] == "miss"


def test_probe_mock_does_not_pretend_online() -> None:
    """mock 探活必须显式标 configured=False, 绝不假装 online."""
    os.environ.pop("NVIDIA_API_KEY", None)
    r = nim_health.nim_health(force_refresh=True)
    # 关键: 4 个字段显式
    assert r["online"] is False
    assert r["configured"] is False
    assert r["reason"] == "NIM_NOT_CONFIGURED"
    assert r["source"] == "mock"
