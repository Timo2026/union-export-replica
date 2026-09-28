"""services.agent_cache — v5.1.0 Skill 结果 LRU 缓存 + spark-output 索引.

职责:
  - skill run 结果本地缓存 (LRU 100 项, TTL 5min)
  - 持久化到 data/.agent_cache/ + spark-output/context/agent_cache.json
  - 提供 hit/miss 统计 + 命中率 (给 UI 显示)
  - 命中时直接返, 不调 LLM (节省 token + 提速)

铁律:
  - iron-rule-1 不变 (LLM 改 quote 仍被拦)
  - 失效不静默: miss 返 None + 缓存键
  - TTL 过期自动失效
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

DEFAULT_MAX_SIZE = 100
DEFAULT_TTL_S = 300  # 5 min
DEFAULT_CACHE_DIR = "data/.agent_cache"
DEFAULT_INDEX_FILE = "spark-output/context/agent_cache.json"


def _make_key(skill_id: str, args: Dict[str, Any]) -> str:
    """稳定 hash: skill_id + args canonical JSON."""
    canonical = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    h = hashlib.sha256(f"{skill_id}|{canonical}".encode()).hexdigest()[:16]
    return f"{skill_id}:{h}"


class AgentCache:
    """LRU + TTL 缓存.

    用法:
        cache = AgentCache()
        v = cache.get("calc_quote", {"material": "6061", ...})
        if v is None:
            v = run_calc_quote(...)
            cache.set("calc_quote", {"material": "6061", ...}, v)
    """

    def __init__(self, max_size: int = DEFAULT_MAX_SIZE, ttl_s: float = DEFAULT_TTL_S,
                 root: Optional[Path] = None):
        self.max_size = int(max_size)
        self.ttl_s = float(ttl_s)
        self.root = Path(root) if root else Path(".")
        self.cache_dir = self.root / DEFAULT_CACHE_DIR
        self.index_path = self.root / DEFAULT_INDEX_FILE
        self._data: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0, "expires": 0, "sets": 0}
        self._load()

    # ---- 核心 get/set ----
    def get(self, skill_id: str, args: Dict[str, Any]) -> Optional[Any]:
        """命中返缓存值; 未命中/过期返 None."""
        key = _make_key(skill_id, args)
        if key not in self._data:
            self._stats["misses"] += 1
            return None
        entry = self._data[key]
        if self._is_expired(entry):
            del self._data[key]
            self._stats["expires"] += 1
            self._stats["misses"] += 1
            log.debug("[agent_cache] expired key=%s", key)
            return None
        # LRU 提升
        self._data.move_to_end(key)
        self._stats["hits"] += 1
        log.debug("[agent_cache] hit key=%s", key)
        # 命中即等价: deepcopy 防调用方 mutate 污染缓存
        return copy.deepcopy(entry["value"])

    def set(self, skill_id: str, args: Dict[str, Any], value: Any) -> str:
        """写入缓存 (含 TTL). 返 key."""
        key = _make_key(skill_id, args)
        self._data[key] = {
            "skill_id": skill_id, "args": copy.deepcopy(args),
            "value": copy.deepcopy(value),
            "created_at": time.time(), "ttl_s": self.ttl_s,
        }
        self._data.move_to_end(key)
        self._stats["sets"] += 1
        # 触发 LRU 淘汰
        while len(self._data) > self.max_size:
            oldest_key, _ = self._data.popitem(last=False)
            self._stats["evictions"] += 1
            log.debug("[agent_cache] evicted key=%s", oldest_key)
        return key

    def invalidate(self, skill_id: Optional[str] = None) -> int:
        """失效缓存. skill_id=None 失效全部. 返失效数量."""
        if skill_id is None:
            n = len(self._data)
            self._data.clear()
            return n
        prefix = f"{skill_id}:"
        keys = [k for k in list(self._data.keys()) if k.startswith(prefix)]
        for k in keys:
            del self._data[k]
        return len(keys)

    def stats(self) -> Dict[str, Any]:
        """返统计 + 命中率."""
        total = self._stats["hits"] + self._stats["misses"]
        rate = self._stats["hits"] / total if total > 0 else 0.0
        return {
            **self._stats,
            "size": len(self._data),
            "max_size": self.max_size,
            "ttl_s": self.ttl_s,
            "hit_rate": round(rate, 3),
            "total_requests": total,
        }

    def list_keys(self, skill_id: Optional[str] = None) -> list:
        """列缓存键 (调试用)."""
        if skill_id is None:
            return list(self._data.keys())
        return [k for k in self._data.keys() if k.startswith(f"{skill_id}:")]

    # ---- 持久化 ----
    def save(self) -> bool:
        """保存到 spark-output/context/agent_cache.json."""
        try:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": time.time(),
                "stats": self._stats,
                "size": len(self._data),
                "max_size": self.max_size,
                "ttl_s": self.ttl_s,
                "entries": [
                    {**e, "key": k} for k, e in self._data.items()
                ],
            }
            tmp = self.index_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.index_path)
            return True
        except Exception as e:
            log.warning("[agent_cache] save failed: %r", e)
            return False

    def _load(self) -> None:
        """从 spark-output/context/agent_cache.json 加载 (best-effort)."""
        if not self.index_path.exists():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            now = time.time()
            for entry in data.get("entries", []):
                if now - entry.get("created_at", 0) > entry.get("ttl_s", self.ttl_s):
                    continue  # 跳过过期
                key = entry["key"]
                self._data[key] = entry
                self._data.move_to_end(key)
            self._stats.update(data.get("stats", {}))
            log.info("[agent_cache] loaded %d entries", len(self._data))
        except Exception as e:
            log.warning("[agent_cache] load failed: %r", e)

    def _is_expired(self, entry: Dict[str, Any]) -> bool:
        return time.time() - entry.get("created_at", 0) > entry.get("ttl_s", self.ttl_s)


# ---- 单例 ----
_global: Optional[AgentCache] = None


def get_cache(root: Optional[Path] = None, **kw: Any) -> AgentCache:
    global _global
    if _global is None:
        _global = AgentCache(root=root, **kw)
    return _global


def reset_global() -> None:
    global _global
    _global = None


# ---- 与 dispatcher 集成 ----
def cached_skill_run(skill_id: str, args: Dict[str, Any], runner: Any) -> Any:
    """用缓存包装 skill runner.

    用法:
        result = cached_skill_run("calc_quote", args, lambda: calc_quote(**args))
    """
    cache = get_cache()
    hit = cache.get(skill_id, args)
    if hit is not None:
        return hit
    try:
        value = runner()
        if value is not None:
            cache.set(skill_id, args, value)
        return value
    except Exception:
        raise
