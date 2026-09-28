"""tests/test_agent_cache.py — v5.1.0 AgentCache LRU+TTL 8 用例.

覆盖:
  1. set + get 命中
  2. miss 返 None
  3. 不同 args 生成不同 key
  4. TTL 过期
  5. LRU 淘汰 (超出 max_size)
  6. invalidate (skill_id 粒度)
  7. 持久化 + 重启恢复
  8. hit_rate 统计 + dispatcher 集成
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cache_root(tmp_root: Path):
    """清空缓存目录返回."""
    cache_dir = tmp_root / "data" / ".agent_cache"
    index_path = tmp_root / "spark-output" / "context" / "agent_cache.json"
    if cache_dir.exists():
        import shutil; shutil.rmtree(cache_dir)
    if index_path.exists():
        index_path.unlink()
    yield tmp_root


# ---- 1. set + get 命中 ----
def test_set_and_get_hit(cache_root: Path) -> None:
    from services.agent_cache import AgentCache
    c = AgentCache(root=cache_root)
    c.set("calc_quote", {"material": "6061", "qty": 50}, {"total": 3826.62})
    v = c.get("calc_quote", {"material": "6061", "qty": 50})
    assert v == {"total": 3826.62}
    stats = c.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 0


# ---- 2. miss ----
def test_miss_returns_none(cache_root: Path) -> None:
    from services.agent_cache import AgentCache
    c = AgentCache(root=cache_root)
    v = c.get("never_set", {})
    assert v is None
    assert c.stats()["misses"] == 1


# ---- 3. 不同 args 生成不同 key ----
def test_different_args_different_keys(cache_root: Path) -> None:
    from services.agent_cache import AgentCache
    c = AgentCache(root=cache_root)
    c.set("calc_quote", {"material": "6061", "qty": 50}, {"v": "A"})
    c.set("calc_quote", {"material": "6061", "qty": 100}, {"v": "B"})
    c.set("calc_quote", {"material": "304", "qty": 50}, {"v": "C"})
    assert c.get("calc_quote", {"material": "6061", "qty": 50}) == {"v": "A"}
    assert c.get("calc_quote", {"material": "6061", "qty": 100}) == {"v": "B"}
    assert c.get("calc_quote", {"material": "304", "qty": 50}) == {"v": "C"}
    assert c.stats()["hits"] == 3


# ---- 4. TTL 过期 ----
def test_ttl_expires(cache_root: Path) -> None:
    from services.agent_cache import AgentCache
    c = AgentCache(root=cache_root, ttl_s=0.2)
    c.set("x", {"k": 1}, "v")
    assert c.get("x", {"k": 1}) == "v"
    time.sleep(0.3)
    v = c.get("x", {"k": 1})
    assert v is None
    assert c.stats()["expires"] >= 1


# ---- 5. LRU 淘汰 ----
def test_lru_eviction(cache_root: Path) -> None:
    from services.agent_cache import AgentCache
    c = AgentCache(root=cache_root, max_size=3)
    for i in range(5):
        c.set(f"sk{i}", {"i": i}, f"v{i}")
    assert c.stats()["size"] == 3
    # 最早 2 个被淘汰
    assert c.get("sk0", {"i": 0}) is None
    assert c.get("sk1", {"i": 1}) is None
    assert c.get("sk2", {"i": 2}) == "v2"
    assert c.get("sk4", {"i": 4}) == "v4"
    assert c.stats()["evictions"] >= 2


# ---- 6. invalidate (skill_id 粒度) ----
def test_invalidate_by_skill_id(cache_root: Path) -> None:
    from services.agent_cache import AgentCache
    c = AgentCache(root=cache_root)
    c.set("a", {"i": 1}, 1)
    c.set("a", {"i": 2}, 2)
    c.set("b", {"i": 1}, 10)
    n = c.invalidate("a")
    assert n == 2
    assert c.get("a", {"i": 1}) is None
    assert c.get("b", {"i": 1}) == 10


def test_invalidate_all(cache_root: Path) -> None:
    from services.agent_cache import AgentCache
    c = AgentCache(root=cache_root)
    c.set("a", {}, 1)
    c.set("b", {}, 2)
    n = c.invalidate()
    assert n == 2
    assert c.get("a", {}) is None


# ---- 7. 持久化 + 重启恢复 ----
def test_persist_and_reload(cache_root: Path) -> None:
    from services.agent_cache import AgentCache
    c1 = AgentCache(root=cache_root, ttl_s=60)
    c1.set("p", {"x": 1}, "saved")
    c1.set("p", {"x": 2}, "saved2")
    assert c1.save() is True
    # 重启: 新 AgentCache 从同目录加载
    c2 = AgentCache(root=cache_root, ttl_s=60)
    assert c2.get("p", {"x": 1}) == "saved"
    assert c2.get("p", {"x": 2}) == "saved2"
    # 索引文件存在
    idx = cache_root / "spark-output" / "context" / "agent_cache.json"
    assert idx.exists()


# ---- 8. dispatcher 集成 + hit_rate ----
def test_dispatcher_integration_with_cache(cache_root: Path, monkeypatch) -> None:
    """验证 skills._runtime.execute() 调用 AgentCache."""
    monkeypatch.chdir(cache_root)
    import importlib
    from services import agent_cache
    importlib.reload(agent_cache)
    agent_cache.reset_global()

    import skills._runtime as rt
    rt.discover(force=True)

    # 写一个 mock skill fn
    class FakeFn:
        call_count = 0
        def __call__(self, ctx, **kw):
            FakeFn.call_count += 1
            return {"ok": True, "skill": "fake", "args": kw, "result": "computed"}

    # 注册 mock skill
    rt._REGISTRY["fake_skill"] = FakeFn()

    args = {"material": "6061", "qty": 50}
    # 1st call: miss → run → cache
    r1 = rt.execute("fake_skill", args, use_cache=True)
    assert r1["_source"] == "skill_runtime"  # miss, 跑 skill
    assert r1["_cache"] == "miss"
    assert FakeFn.call_count == 1
    # 2nd call: hit
    r2 = rt.execute("fake_skill", args, use_cache=True)
    assert r2["_source"] == "agent_cache"
    assert r2["_cache"] == "hit"
    assert FakeFn.call_count == 1  # 没再调
    # 3rd call: use_cache=False → 强制重跑
    r3 = rt.execute("fake_skill", args, use_cache=False)
    assert r3["_source"] == "skill_runtime"
    assert FakeFn.call_count == 2
    # hit_rate 统计
    cache = agent_cache.get_cache()
    stats = cache.stats()
    assert stats["hits"] >= 1
    assert stats["hit_rate"] > 0
