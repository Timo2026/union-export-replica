"""test_model_config.py — 模型注册表 (UI 后端) load/save/validate/probe 测试 (维度: 模型设置工具)."""
from __future__ import annotations

import copy

import pytest

from services import model_config as mc


def test_load_registry_has_six_models():
    cfg = mc.load()
    models = cfg["models"]
    for k in ("llm", "vlm", "embedding", "ocr", "asr", "deterministic"):
        assert k in models, f"缺模型 {k}"
        assert models[k].get("endpoint") and models[k].get("model")


def test_deterministic_is_locked():
    cfg = mc.load()
    assert cfg["models"]["deterministic"].get("locked") is True


def test_validate_ok():
    assert mc.validate(mc.load()) == []


def test_validate_catches_missing_endpoint():
    bad = copy.deepcopy(mc.load())
    bad["models"]["llm"]["endpoint"] = ""
    errs = mc.validate(bad)
    assert any("endpoint" in e for e in errs)


def test_validate_catches_bad_scheme():
    bad = copy.deepcopy(mc.load())
    bad["models"]["asr"]["endpoint"] = "127.0.0.1:8089"
    assert any("http" in e for e in mc.validate(bad))


def test_validate_forbids_disabling_deterministic():
    bad = copy.deepcopy(mc.load())
    bad["models"]["deterministic"]["enabled"] = False
    assert any("deterministic" in e for e in mc.validate(bad))


def test_save_forces_deterministic_locked(tmp_path, monkeypatch):
    # 重定向到临时文件, 不污染真实 models.yaml
    tmp = tmp_path / "models.yaml"
    tmp.write_text(open(mc._MODELS_YAML, encoding="utf-8").read(), encoding="utf-8")
    monkeypatch.setattr(mc, "_MODELS_YAML", tmp)
    cfg = mc.load()
    cfg["models"]["deterministic"]["locked"] = False      # 试图解锁 (enabled 保持 True)
    saved = mc.save(cfg)
    assert saved["models"]["deterministic"]["locked"] is True   # 被强制恢复锁定
    assert saved["models"]["deterministic"]["enabled"] is True
    assert "updated_at" in saved


def test_save_rejects_disabling_deterministic(tmp_path, monkeypatch):
    tmp = tmp_path / "models.yaml"
    tmp.write_text(open(mc._MODELS_YAML, encoding="utf-8").read(), encoding="utf-8")
    monkeypatch.setattr(mc, "_MODELS_YAML", tmp)
    cfg = mc.load()
    cfg["models"]["deterministic"]["enabled"] = False     # 铁律①: 不可禁用
    with pytest.raises(ValueError):
        mc.save(cfg)


def test_probe_url_construction():
    ep = mc._probe_url({"endpoint": "http://127.0.0.1:1234/v1", "probe_path": "/models"})
    assert ep == "http://127.0.0.1:1234/v1/models"
    ep2 = mc._probe_url({"endpoint": "http://127.0.0.1:7862/", "probe_path": "api/health"})
    assert ep2 == "http://127.0.0.1:7862/api/health"


def test_probe_one_disabled_skips():
    r = mc.probe_one({"endpoint": "http://x", "enabled": False})
    assert r["online"] is False and r.get("skipped") == "disabled"


def test_probe_one_unreachable_offline():
    r = mc.probe_one({"endpoint": "http://127.0.0.1:59996", "probe_path": "/health", "enabled": True}, timeout=1.0)
    assert r["online"] is False and "error" in r


def test_probe_all_returns_all_keys():
    out = mc.probe_all(timeout=1.0)
    for k in ("llm", "vlm", "embedding", "ocr", "asr", "deterministic"):
        assert k in out and "online" in out[k]
    assert "funasr_gateway" in out


def test_endpoint_for_respects_enabled():
    cfg = copy.deepcopy(mc.load())
    assert mc.endpoint_for("llm", cfg) is not None
    cfg["models"]["llm"]["enabled"] = False
    assert mc.endpoint_for("llm", cfg) is None
