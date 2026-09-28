"""test_model_router.py — L3 Model Mesh 路由单元测试 (local/nvidia/mock + DETERMINISTIC)."""
from __future__ import annotations

import pytest

from services.model_router import ModelRouter, ROLES


class _FakeTimo:
    base_url = "http://127.0.0.1:7862"
    online = True


def _settings(backend="local"):
    return {"model_router": {"backend": backend, "roles": {
        "FAST": {"endpoint": "http://127.0.0.1:1/v1", "model": "m"},
        "EMBED": {"endpoint": "http://127.0.0.1:1/v1", "model": "e"}}}}


def test_deterministic_always_routes_to_timo():
    mr = ModelRouter(_settings("local"), timo=_FakeTimo())
    r = mr.resolve("DETERMINISTIC")
    assert r["backend"] == "timo-kernel"
    assert r["online"] is True
    assert "LLM" in r["note"]        # 明确不走 LLM


def test_all_roles_resolvable():
    mr = ModelRouter(_settings("local"), timo=_FakeTimo())
    st = mr.status()
    assert set(st["routes"].keys()) == set(ROLES)


def test_mock_backend_labels_all_non_deterministic_as_mock():
    mr = ModelRouter(_settings("mock"), timo=_FakeTimo())
    for role in ("FAST", "VISION", "REASON", "EMBED", "ASR"):
        r = mr.resolve(role)
        assert r["backend"] == "mock" and r["online"] is False
    # DETERMINISTIC 仍是内核
    assert mr.resolve("DETERMINISTIC")["backend"] == "timo-kernel"


def test_nvidia_backend_uses_nim_and_degrades_when_unreachable():
    mr = ModelRouter(_settings("nvidia"), timo=_FakeTimo())
    r = mr.resolve("REASON")
    assert r["backend"] == "nvidia-nim"
    assert r["model"]                      # NIM 模型名已配置
    assert r["online"] is False            # 本机无 NIM → 探测失败
    assert "降级" in r["note"]


def test_local_unreachable_endpoint_marked_offline(monkeypatch):
    """v2.3.1: local backend 走 models.yaml + choose_route(), 不再被 roles_cfg.endpoint 覆盖。
    注入一个不通的 llm endpoint, 验证 offline + MOCK note。
    """
    from services.model_config import load as _load
    cfg = _load()
    # 把 llm endpoint 临时改成一个肯定不通的端口
    cfg["models"]["llm"]["endpoint"] = "http://127.0.0.1:1/v1"
    cfg["models"]["llm"]["model"] = "offline-mock"
    mr = ModelRouter(_settings("local"), timo=_FakeTimo())
    mr._model_cfg = cfg  # 覆盖默认加载的 models.yaml
    mr._probe_cache.clear()
    r = mr.resolve("FAST")
    assert r["backend"] == "local" and r["online"] is False
    assert "MOCK" in r["note"]


def test_status_lists_online_roles():
    mr = ModelRouter(_settings("local"), timo=_FakeTimo())
    st = mr.status()
    # 至少 DETERMINISTIC 在线 (timo online=True)
    assert "DETERMINISTIC" in st["online_roles"]
