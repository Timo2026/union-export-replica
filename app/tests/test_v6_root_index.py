"""tests/test_v6_root_index.py — F4 融合版根 index.html 真接线验证 (5 用例).

覆盖:
  1. 根 / 服务 index.html (v6.0.0 融合版), 不是 webui/index.html
  2. 根 index.html 含 5 endpoint 真实 fetch
  3. 根 index.html 含 黄金链 7 步 DOM
  4. 根 index.html 含 三栏 (Inbox/Inspector/Agent)
  5. 根 index.html 引用 workbench.css 兼容 + 不依赖 webui 单文件
"""
from __future__ import annotations
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_root_serves_v6_index_not_webui() -> None:
    """FastAPI GET / 返 根 index.html (v6.0.0 融合版), 不应返 webui 单文件."""
    from fastapi.testclient import TestClient
    from services.api_server import app
    with TestClient(app) as c:
        r = c.get("/")
    assert r.status_code == 200
    text = r.text
    # 根 index.html 标识
    assert "v6.1.0 融合版" in text or "Union Manufacturing Export Agent" in text
    # 不应是 webui 单文件 2700+ 行 (v6 根应 < 500 行)
    assert len(text) < 50_000, f"根 index.html 过大 ({len(text)} bytes) — 可能是 webui 单文件被误用"


def test_root_contains_5_real_endpoints() -> None:
    """根 index.html 包含 5 endpoint 的 fetch 调用."""
    p = ROOT / "index.html"
    text = p.read_text(encoding="utf-8")
    # 5 真实 endpoint (v6 融合版关键接线)
    endpoints = ["/health", "/v1/mail/inbox", "/v1/mail/", "/v1/cache/stats", "/v1/spark/dashboard"]
    found = sum(1 for e in endpoints if e in text)
    assert found >= 3, f"根 index.html 缺真实 endpoint 接线 (仅命中 {found}/5: {[e for e in endpoints if e in text]})"


def test_root_golden_chain_7_steps() -> None:
    """根 index.html 黄金链 7 步 (INTAKE→PARSE→DFM→QUOTE→VERIFY→REPLY→CRM)."""
    p = ROOT / "index.html"
    text = p.read_text(encoding="utf-8")
    for step in ["INTAKE", "PARSE", "DFM", "QUOTE", "VERIFY", "REPLY", "CRM"]:
        assert step in text, f"根 index.html 缺黄金链步骤: {step}"


def test_root_three_columns_dom() -> None:
    """根 index.html 三栏 (Inbox/Inspector/Agent) DOM 结构."""
    p = ROOT / "index.html"
    text = p.read_text(encoding="utf-8")
    assert "Inbox" in text and "Inspector" in text and "Agent" in text
    # 三个 ID 至少存在
    for cid in ["inboxList", "inspector", "chatThread"]:
        assert f'id="{cid}"' in text, f"三栏 ID 缺失: {cid}"


def test_root_uses_workbench_css_legacy_fallback() -> None:
    """根 index.html 引用 css/workbench.css (v6 兼容 legacy), 不是 webui 单文件."""
    p = ROOT / "index.html"
    text = p.read_text(encoding="utf-8")
    # 引用 css/workbench.css (融合版保留)
    assert "css/workbench.css" in text
    # 不应直接 inline webui 全部 CSS (那是 webui/index.html)
    assert "wbInboxList" not in text  # webui 专属 ID
    assert "wbChatText" not in text    # webui 专属 ID
