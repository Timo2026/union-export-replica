"""test_resilience.py — 容错: 指数退避重试 + 熔断器 + 超时 + fallback (维度 6.2)."""
from __future__ import annotations

import time

import pytest

from services.resilience import CircuitOpenError, Resilient


def test_success_no_retry():
    rt = Resilient(max_retries=3, backoff=0.01, jitter=False)
    calls = {"n": 0}

    def ok():
        calls["n"] += 1
        return "good"

    assert rt.call(ok, name="op") == "good"
    assert calls["n"] == 1
    assert rt.stats["op"]["success"] == 1


def test_retries_then_succeeds():
    rt = Resilient(max_retries=3, backoff=0.01, jitter=False)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient")
        return "recovered"

    assert rt.call(flaky, name="flaky", retry_on=(ConnectionError,)) == "recovered"
    assert calls["n"] == 3
    assert rt.stats["flaky"]["retries"] == 2


def test_exhausts_retries_raises():
    rt = Resilient(max_retries=2, backoff=0.01, jitter=False)

    def always_fail():
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        rt.call(always_fail, name="down", retry_on=(ConnectionError,))
    assert rt.stats["down"]["failures"] == 1


def test_exhausts_retries_uses_fallback():
    rt = Resilient(max_retries=2, backoff=0.01, jitter=False)

    def always_fail():
        raise ConnectionError("down")

    out = rt.call(always_fail, name="fb", retry_on=(ConnectionError,), fallback=lambda: "offline-kernel")
    assert out == "offline-kernel"


def test_non_retryable_fails_fast():
    rt = Resilient(max_retries=5, backoff=0.01, jitter=False)
    calls = {"n": 0}

    def schema_err():
        calls["n"] += 1
        raise ValueError("schema mismatch")     # 不在 retry_on → fail fast

    with pytest.raises(ValueError):
        rt.call(schema_err, name="schema", retry_on=(ConnectionError,))
    assert calls["n"] == 1                       # 未重试


def test_circuit_opens_after_threshold():
    rt = Resilient(max_retries=0, backoff=0.01, jitter=False, fail_threshold=2, reset_after=30)

    def fail():
        raise ConnectionError("x")

    for _ in range(2):
        with pytest.raises(ConnectionError):
            rt.call(fail, name="cb", retry_on=(ConnectionError,))
    assert rt.state("cb") == "OPEN"
    # OPEN → 快速失败 (CircuitOpenError), 不再调用 fn
    with pytest.raises(CircuitOpenError):
        rt.call(lambda: "never", name="cb")


def test_circuit_open_uses_fallback():
    rt = Resilient(max_retries=0, backoff=0.01, fail_threshold=1, reset_after=30)
    with pytest.raises(ConnectionError):
        rt.call(lambda: (_ for _ in ()).throw(ConnectionError("x")), name="cb2",
                retry_on=(ConnectionError,))
    assert rt.state("cb2") == "OPEN"
    assert rt.call(lambda: "never", name="cb2", fallback=lambda: "degraded") == "degraded"


def test_circuit_half_open_recovers():
    rt = Resilient(max_retries=0, backoff=0.01, fail_threshold=1, reset_after=0.05)
    with pytest.raises(ConnectionError):
        rt.call(lambda: (_ for _ in ()).throw(ConnectionError("x")), name="ho",
                retry_on=(ConnectionError,))
    assert rt.state("ho") == "OPEN"
    time.sleep(0.08)                              # 冷却 → HALF_OPEN
    assert rt.call(lambda: "back", name="ho") == "back"
    assert rt.state("ho") == "CLOSED"


def test_exponential_backoff_increases_delay():
    rt = Resilient(max_retries=3, backoff=0.05, backoff_max=10, jitter=False)
    calls = {"n": 0, "t": []}

    def fail():
        calls["t"].append(time.time())
        calls["n"] += 1
        raise ConnectionError("x")

    with pytest.raises(ConnectionError):
        rt.call(fail, name="bo", retry_on=(ConnectionError,))
    # 4 次调用 (1 + 3 重试), 间隔应递增 (0.05, 0.1, 0.2)
    gaps = [round(calls["t"][i+1] - calls["t"][i], 3) for i in range(len(calls["t"]) - 1)]
    assert len(gaps) == 3
    assert gaps[1] >= gaps[0] * 1.5               # 指数增长


def test_snapshot_structure():
    rt = Resilient(max_retries=1, backoff=0.01)
    rt.call(lambda: 1, name="s")
    snap = rt.snapshot()
    assert "breakers" in snap and "stats" in snap
    assert snap["stats"]["s"]["calls"] == 1
