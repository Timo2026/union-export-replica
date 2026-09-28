"""test_timo_engine_env.py — CNC_BRAIN_SRC / CNC_BRAIN_PY 环境变量覆盖.

DGX Spark 节点部署时 settings.yaml 里的 Windows 引擎路径不存在, 用环境变量
把离线内核指向节点上的引擎 venv (或 OCC 环境) — 免改配置文件.
"""
from __future__ import annotations

from adapters.timo_adapter import TimoAdapter

_CFG = {"timo": {"engine_src": "/win/engine",
                 "engine_python": "/win/engine/.venv/python.exe"}}


def test_engine_paths_from_settings_by_default(monkeypatch):
    monkeypatch.delenv("CNC_BRAIN_SRC", raising=False)
    monkeypatch.delenv("CNC_BRAIN_PY", raising=False)
    t = TimoAdapter(_CFG)
    assert t.engine_src == "/win/engine"
    assert t.engine_python == "/win/engine/.venv/python.exe"


def test_engine_paths_env_override(monkeypatch):
    monkeypatch.setenv("CNC_BRAIN_SRC", "/opt/cnc-ai-brain")
    monkeypatch.setenv("CNC_BRAIN_PY", "/opt/cnc-ai-brain/.venv/bin/python")
    t = TimoAdapter(_CFG)
    assert t.engine_src == "/opt/cnc-ai-brain"
    assert t.engine_python == "/opt/cnc-ai-brain/.venv/bin/python"


def test_engine_paths_partial_env_override(monkeypatch):
    """只设 CNC_BRAIN_PY (OCC 场景: 引擎源码已在 PYTHONPATH) 时 src 仍走配置."""
    monkeypatch.delenv("CNC_BRAIN_SRC", raising=False)
    monkeypatch.setenv("CNC_BRAIN_PY", "/home/Developer/miniconda3/envs/occ/bin/python")
    t = TimoAdapter(_CFG)
    assert t.engine_src == "/win/engine"
    assert t.engine_python == "/home/Developer/miniconda3/envs/occ/bin/python"
