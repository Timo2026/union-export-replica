"""test_b4_rag_config.py — B4 settings.yaml rag_layers 配置段 + 去硬编码 (任务 #26).

铁律: 端点从配置读取 — rag_layers.embed_url 显式配置优先,
缺省派生自 funasr.embed_url (单一来源, 不再第二处硬编码 :1278)。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bootstrap import build_controller
from services.config import load_settings

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def base_settings(tmp_path):
    s = load_settings(_ROOT)
    s.setdefault("storage", {})["crm_db"] = str(tmp_path / "crm-b4.sqlite3")
    return s


def test_settings_yaml_has_rag_layers_section():
    s = load_settings(_ROOT)
    rl = s.get("rag_layers")
    assert isinstance(rl, dict), "settings.yaml 缺 rag_layers 段"
    assert rl.get("enabled") is True
    assert rl["embed_url"] == "http://127.0.0.1:1278/v1"
    assert rl["vector_backend"] in ("memory", "qdrant", "auto", "file")


def test_gateway_embed_url_derives_from_funasr_config(base_settings):
    """rag_layers 不写 embed_url → 派生 funasr.embed_url + /v1 (单一配置来源)."""
    base_settings["funasr"]["embed_url"] = "http://127.0.0.1:1999"
    base_settings["rag_layers"] = {"enabled": True, "vector_backend": "memory"}
    ctrl = build_controller(settings_override=base_settings)
    assert ctrl.rag_gateway is not None
    assert ctrl.rag_gateway.embedder.url == "http://127.0.0.1:1999/v1"
    assert ctrl.rag_gateway.store.mode == "memory"


def test_gateway_explicit_embed_url_wins(base_settings):
    base_settings["rag_layers"] = {"enabled": True, "vector_backend": "memory",
                                   "embed_url": "http://127.0.0.1:59999/v1",
                                   "timeout_s": 7}
    ctrl = build_controller(settings_override=base_settings)
    assert ctrl.rag_gateway.embedder.url == "http://127.0.0.1:59999/v1"
    assert ctrl.rag_gateway.embedder.timeout == 7.0


def test_gateway_disabled_yields_legacy_path(base_settings):
    base_settings["rag_layers"] = {"enabled": False}
    ctrl = build_controller(settings_override=base_settings)
    assert ctrl.rag_gateway is None
