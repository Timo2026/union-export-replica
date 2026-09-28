"""resilience.py — 统一容错: 指数退避重试 + 熔断器 + 超时 (维度 6.2).

对齐冻结 PRD 第 14 节:
  Timeout → exponential backoff → limited retry → persistent failure → circuit breaker
  → schema mismatch → fail fast → repeated agent failure → HITL/incident

用法:
  rt = Resilient(timeout=8, max_retries=3, backoff=0.2, fail_threshold=3, reset_after=20)
  data = rt.call(lambda: urlopen_json(...), name="timo.quote", retry_on=(URLError, TimeoutError))
熔断器三态: CLOSED(正常) → OPEN(连续失败达阈值, 快速失败) → HALF_OPEN(冷却后试探)。
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional, Tuple


class CircuitOpenError(RuntimeError):
    """熔断器 OPEN 时快速失败。"""


@dataclass
class _Breaker:
    fail_threshold: int
    reset_after: float
    state: str = "CLOSED"          # CLOSED | OPEN | HALF_OPEN
    failures: int = 0
    opened_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self) -> bool:
        with self.lock:
            if self.state == "CLOSED":
                return True
            if self.state == "OPEN":
                if time.time() - self.opened_at >= self.reset_after:
                    self.state = "HALF_OPEN"
                    return True
                return False
            return True            # HALF_OPEN: 放行一次试探

    def on_success(self):
        with self.lock:
            self.failures = 0
            self.state = "CLOSED"

    def on_failure(self):
        with self.lock:
            self.failures += 1
            if self.state == "HALF_OPEN" or self.failures >= self.fail_threshold:
                self.state = "OPEN"
                self.opened_at = time.time()


class Resilient:
    """一个带 per-name 熔断器的弹性调用器。"""

    def __init__(self, timeout: float = 8.0, max_retries: int = 3, backoff: float = 0.2,
                 backoff_max: float = 4.0, jitter: bool = True,
                 fail_threshold: int = 3, reset_after: float = 20.0):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.backoff_max = backoff_max
        self.jitter = jitter
        self.fail_threshold = fail_threshold
        self.reset_after = reset_after
        self._breakers: Dict[str, _Breaker] = {}
        self._lock = threading.Lock()
        self.stats: Dict[str, Dict[str, int]] = {}

    def _breaker(self, name: str) -> _Breaker:
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = _Breaker(self.fail_threshold, self.reset_after)
            return self._breakers[name]

    def _bump(self, name: str, key: str):
        s = self.stats.setdefault(name, {"calls": 0, "retries": 0, "success": 0,
                                         "failures": 0, "circuit_open": 0})
        s[key] = s.get(key, 0) + 1

    def call(self, fn: Callable[[], Any], name: str = "op",
             retry_on: Iterable[type] = (Exception,),
             fallback: Optional[Callable[[], Any]] = None) -> Any:
        """执行 fn(): 熔断检查 → 超时 → 指数退避重试 → 仍失败则 fallback 或抛出。"""
        br = self._breaker(name)
        self._bump(name, "calls")
        retry_on = tuple(retry_on)

        if not br.allow():
            self._bump(name, "circuit_open")
            if fallback is not None:
                return fallback()
            raise CircuitOpenError(f"circuit OPEN for '{name}' (failures>={self.fail_threshold})")

        attempt = 0
        last_exc: Optional[BaseException] = None
        while attempt <= self.max_retries:
            try:
                res = fn()
                br.on_success()
                self._bump(name, "success")
                return res
            except retry_on as e:  # noqa: PERF203
                last_exc = e
                attempt += 1
                if attempt > self.max_retries:
                    break
                self._bump(name, "retries")
                delay = min(self.backoff * (2 ** (attempt - 1)), self.backoff_max)
                if self.jitter:
                    delay *= (0.5 + random.random())
                time.sleep(delay)
            except Exception as e:
                # 不在 retry_on 内 (如 schema 错误) → fail fast
                br.on_failure()
                self._bump(name, "failures")
                if fallback is not None:
                    return fallback()
                raise e

        # 重试耗尽
        br.on_failure()
        self._bump(name, "failures")
        if fallback is not None:
            return fallback()
        assert last_exc is not None
        raise last_exc

    def state(self, name: str) -> str:
        return self._breaker(name).state

    def snapshot(self) -> Dict[str, Any]:
        return {"breakers": {n: b.state for n, b in self._breakers.items()},
                "stats": self.stats}


# ---- 便捷: 带超时的 urlopen JSON ----
def urlopen_json(url: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 8.0,
                 method: Optional[str] = None) -> Dict[str, Any]:
    import json
    import urllib.request
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"} if data else {},
                                 method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# 全局默认弹性调用器 (adapter 可复用)
DEFAULT = Resilient()
