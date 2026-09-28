"""services.nim_health — v6.0.0 NIM (Inference Microservice) 探活 + AgentCache 缓存.

诚实边界:
  - 无 NVIDIA_API_KEY → 返 mock "NIM_NOT_CONFIGURED" (不假装实跑)
  - 有 key → 真探 build.nvidia.com /v1/models
  - 探活结果缓存到 AgentCache (nvidia:health 键, TTL 5min)
  - 失败显式标注 (nemo_available + last_error), 失败不静默

frontend (/v1/nim/health) 直接返当前状态供 UI 显示.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# v6.0.0 默认端点 (云端 build.nvidia.com 公开 API)
NIM_DEFAULT_BASE = "https://integrate.api.nvidia.com/v1"
NIM_HEALTH_TIMEOUT_S = 5.0

CACHE_KEY = "nvidia:health"
CACHE_TTL_S = 300  # 5min (复用 AgentCache TTL)


def _probe_nim(base_url: str, api_key: str, timeout_s: float) -> Dict[str, Any]:
    """真探 NIM 端点 (urllib, 无额外依赖)."""
    url = f"{base_url.rstrip('/')}/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read())
            return {
                "online": True,
                "latency_ms": round((time.time() - t0) * 1000, 1),
                "base_url": base_url,
                "models_count": len(data.get("data", [])) if isinstance(data, dict) else 0,
                "sample_models": [m.get("id") for m in data.get("data", [])[:5]] if isinstance(data, dict) else [],
                "source": "nim",
                "ts": time.time(),
            }
    except Exception as e:
        return {
            "online": False,
            "error": repr(e),
            "base_url": base_url,
            "latency_ms": round((time.time() - t0) * 1000, 1),
            "source": "nim",
            "ts": time.time(),
        }


def _probe_mock() -> Dict[str, Any]:
    """无 key 时的 mock 探活 — 显式标注 NIM_NOT_CONFIGURED, 不静默冒充."""
    return {
        "online": False,
        "configured": False,
        "reason": "NIM_NOT_CONFIGURED",
        "hint": "Set NVIDIA_API_KEY env var, 或 export UEA_NIM_BASE=https://your-nim.example.com/v1",
        "source": "mock",
        "ts": time.time(),
    }


def nim_health(force_refresh: bool = False) -> Dict[str, Any]:
    """返 NIM 探活结果, 缓存到 AgentCache (nvidia:health 键).

    流程:
      1. 查 cache, 命中且未过期 → 直接返
      2. 过期/无 → 探活 (有 key 真探, 无 key mock)
      3. 写入 cache
      4. 返结果
    """
    from services.agent_cache import get_cache
    cache = get_cache()

    if not force_refresh:
        hit = cache.get(CACHE_KEY, {})
        if hit is not None:
            hit["_cache"] = "hit"
            return hit

    # 真正探活
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    base_url = os.environ.get("UEA_NIM_BASE", NIM_DEFAULT_BASE)
    if api_key:
        result = _probe_nim(base_url, api_key, NIM_HEALTH_TIMEOUT_S)
        result["configured"] = True
    else:
        result = _probe_mock()

    cache.set(CACHE_KEY, {}, result)
    result["_cache"] = "miss"
    return result


def invalidate_nim_cache() -> bool:
    """失效 NIM 缓存 (下次查时重新探活)."""
    try:
        from services.agent_cache import get_cache
        get_cache().invalidate("nvidia")
        return True
    except Exception:
        return False
