"""test_model_router_layered.py — Nemotron 全家族分层调度验证.

验证 model_router 在 nvidia backend 下路由到正确的 Nemotron 端点 (v3 · 2026-09-20 实测栈):
  FAST   -> :8002  NVIDIA-Nemotron-3-Nano-4B-BF16              (边缘极速, 意图分类/路由)
  REASON -> :8000  NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4  (MoE 深度推理, 规划/草稿)
  VISION -> :8020  Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4 (多模态)
  ASR    -> :8021  nemotron-3.5-asr-streaming-0.6b              (专档流式; 不再蹭 Omni)
  EMBED  -> :8011  Nemotron-3-Embed-1B-BF16                     (RAG 向量化; nv-embedqa 已否决)
  DETERMINISTIC -> locked, timo-kernel                          (铁律1, 永不走 LLM)

核心断言:
  - FAST 与 REASON 路由到不同 endpoint+model (分层调度, 非同一模型)
  - ASR 用专档流式模型 (与 VISION 的 Omni 分离)
  - 所有 NIM model 在 Nemotron 家族 (全 NVIDIA 自研纯度)
  - DETERMINISTIC 永远 locked 到 Timo 引擎

对齐: config/models.nvidia-fullstack.yaml v3 + services/model_router.py _NIM_DEFAULTS v3
      (hf-mirror API 实测仓库 ID, 见 docs/PRD-MASTER-UEA-DELIVERY.md §1.2-F)
"""
from __future__ import annotations

import pytest

from services.model_router import ModelRouter


class _FakeTimo:
    base_url = "http://127.0.0.1:7862"
    online = True


def _settings(backend="nvidia"):
    return {"model_router": {"backend": backend, "roles": {}}}


# ---------- 单角色端点断言 ----------

def test_fast_routes_to_nano_4b_port_8002():
    mr = ModelRouter(_settings("nvidia"), timo=_FakeTimo())
    r = mr.resolve("FAST")
    assert "8002" in r["endpoint"], f"FAST 应路由到 :8002 (Nano-4B), 实际 {r['endpoint']}"
    assert "nemotron-3-nano-4b" in r["model"].lower()


def test_reason_routes_to_lightning_port_8000():
    mr = ModelRouter(_settings("nvidia"), timo=_FakeTimo())
    r = mr.resolve("REASON")
    assert "8000" in r["endpoint"], f"REASON 应路由到 :8000 (Lightning-30B), 实际 {r['endpoint']}"
    assert "lightning-30b-a3b" in r["model"].lower()


def test_vision_routes_to_omni_port_8020():
    mr = ModelRouter(_settings("nvidia"), timo=_FakeTimo())
    r = mr.resolve("VISION")
    assert "8020" in r["endpoint"], f"VISION 应路由到 :8020 (Omni), 实际 {r['endpoint']}"
    assert "omni" in r["model"].lower()


def test_asr_routes_to_streaming_port_8021():
    mr = ModelRouter(_settings("nvidia"), timo=_FakeTimo())
    r = mr.resolve("ASR")
    assert "8021" in r["endpoint"], f"ASR 应路由到 :8021 (streaming-0.6b), 实际 {r['endpoint']}"
    assert "asr-streaming" in r["model"].lower()


def test_embed_routes_to_nemotron_embed_port_8011():
    mr = ModelRouter(_settings("nvidia"), timo=_FakeTimo())
    r = mr.resolve("EMBED")
    assert "8011" in r["endpoint"], f"EMBED 应路由到 :8011 (Nemotron-3-Embed-1B), 实际 {r['endpoint']}"
    assert "nemotron-3-embed" in r["model"].lower()
    assert "embedqa" not in r["model"].lower(), "nv-embedqa 已否决 (NIM 容器路线关闭)"


# ---------- 分层调度核心断言 ----------

def test_fast_and_reason_layered_to_different_endpoints():
    """分层调度核心: FAST (4B 极速) 与 REASON (30B MoE) 必须走不同 endpoint+model.

    这是 Nemotron 全家族能效梯度的关键:
      FAST 用 4B 省延迟 (意图分类/路由)
      REASON 用 MoE 省显存 (规划/草稿, 30B 能力 3B 成本)
    若两者路由到同一 endpoint, 说明分层调度失效, 退化为单模型兜一切.
    """
    mr = ModelRouter(_settings("nvidia"), timo=_FakeTimo())
    fast = mr.resolve("FAST")
    reason = mr.resolve("REASON")
    assert fast["endpoint"] != reason["endpoint"], (
        "FAST 与 REASON 必须分层到不同 endpoint, 不能同 endpoint"
    )
    assert fast["model"] != reason["model"], (
        "FAST 与 REASON 必须用不同模型 (4B vs 30B-A3B MoE)"
    )


def test_vision_and_asr_use_dedicated_models():
    """VISION 走 Omni 多模态, ASR 走专档流式模型 — 实测栈分离 (不再共用 Omni)."""
    mr = ModelRouter(_settings("nvidia"), timo=_FakeTimo())
    vision = mr.resolve("VISION")
    asr = mr.resolve("ASR")
    assert vision["endpoint"] != asr["endpoint"], (
        "VISION 与 ASR 应使用各自端点 (Omni :8020 vs streaming :8021)"
    )
    assert vision["model"] != asr["model"], "VISION 与 ASR 应为不同模型"
    assert "omni" in vision["model"].lower()
    assert "asr-streaming" in asr["model"].lower()


# ---------- Nemotron 全家族纯度 ----------

def test_nim_models_all_nvidia_family():
    """Nemotron 全家族纯度: 所有 NIM model 名含 nemotron (NVIDIA 自研)."""
    mr = ModelRouter(_settings("nvidia"), timo=_FakeTimo())
    for role in ("FAST", "REASON", "VISION", "ASR", "EMBED"):
        r = mr.resolve(role)
        m = r["model"].lower()
        assert "nemotron" in m, (
            f"{role} model={r['model']} 不在 Nemotron 家族 (NVIDIA 自研纯度破坏)"
        )


# ---------- 铁律1: DETERMINISTIC 锁定 ----------

def test_deterministic_locked_to_timo_kernel():
    """铁律1: DETERMINISTIC 永远路由到 Timo 引擎, 不走任何 LLM (含 Nemotron)."""
    mr = ModelRouter(_settings("nvidia"), timo=_FakeTimo())
    r = mr.resolve("DETERMINISTIC")
    assert r["backend"] == "timo-kernel"
    assert r["online"] is True
    assert "LLM" in r["note"]
    # 不含任何 Nemotron/Nano/Lightning 字样 (DETERMINISTIC 不平替)
    assert "nemotron" not in r.get("model", "").lower()


def test_deterministic_locked_even_in_mock_backend():
    """铁律1 双保险: 即使 backend=mock, DETERMINISTIC 仍走 Timo 引擎."""
    mr = ModelRouter(_settings("mock"), timo=_FakeTimo())
    r = mr.resolve("DETERMINISTIC")
    assert r["backend"] == "timo-kernel"
    assert r["online"] is True