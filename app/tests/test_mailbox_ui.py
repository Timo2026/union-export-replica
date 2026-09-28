"""test_mailbox_ui.py — v3.0 #36 + v4.0.0 邮件台 + Workbench UI smoke 测试.

v4.0.0 设计变更:
  - 默认 active tab 从 mailbox 改为 workbench (三栏智能体协作台)
  - tab-mailbox section 改为 hidden 默认 (用户可手动切换)
  - webui 行数上限从 1700 提升到 2500 (v4 加 workbench section + CSS + IIFE)

断言 webui/index.html 含:
  - Workbench nav 按钮 (data-tab="workbench", class="active") — v4 默认
  - tab-mailbox nav 存在但 section 默认 hidden
  - 7 区 region 标签 (客户/图纸/RAG/未办/门禁/复盘/落地成本)
  - Mail IIFE 命名空间 + 关键函数 (向后兼容, 旧 tab 仍可达)
  - demo 装载 6 个场景按钮
  - draft_only 草稿占位 + 铁律①
  - tab-models 已被移到 hidden (默认页切换)
  - tab-workbench 含三栏 DOM (wb-shell / wb-inbox / wb-inspect / wb-chat)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api_server import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_root_serves_workbench_default(client):
    """v4.0.0 设计变更: 默认 tab = workbench (三栏智能体协作台), tab-mailbox 默认 hidden.

    v6.0.0 路由变更: legacy 三栏 UI 迁移至 /webui, 根路由为 v6 融合版。
    """
    r = client.get("/webui")
    assert r.status_code == 200
    html = r.text
    # workbench 是默认 active
    m = re.search(r'<button data-tab="workbench"([^>]*)>', html)
    assert m, "workbench nav button missing"
    assert 'class="active"' in m.group(1), f"workbench should be active by default: {m.group(1)}"
    # tab-workbench section 默认非 hidden
    m2 = re.search(r'<section id="tab-workbench"([^>]*)>', html)
    assert m2, "tab-workbench section missing"
    assert 'hidden' not in m2.group(1), f"tab-workbench should be visible by default: {m2.group(1)}"
    # tab-mailbox 仍可达 (用户可手动切), 但默认 hidden
    m3 = re.search(r'<section id="tab-mailbox"([^>]*)>', html)
    assert m3, "tab-mailbox section missing (v3 兼容)"
    assert 'hidden' in m3.group(1), f"tab-mailbox should be hidden by default in v4: {m3.group(1)}"
    # tab-models 仍是 hidden
    m4 = re.search(r'<section id="tab-models"([^>]*)>', html)
    assert 'hidden' in m4.group(1)


def test_mailbox_has_all_7_regions(client):
    """7 区 region 标签都在 (Trace 可选, 共 7-8 个)."""
    r = client.get("/webui")
    html = r.text
    for label in ["客户", "图纸", "RAG", "未办", "门禁", "复盘", "落地成本"]:
        assert label in html, f"region label missing: {label}"


def test_mailbox_has_6_demo_scenario_buttons(client):
    """S1-S5 + M1 共 6 个 demo 按钮."""
    r = client.get("/webui")
    html = r.text
    for s in ["S1", "S2", "S3", "S4", "S5", "M1"]:
        assert f"loadScenario('{s}')" in html, f"demo button missing: {s}"


def test_mailbox_has_mail_iife_namespace(client):
    """window.Mail IIFE 命名空间 + 关键函数."""
    r = client.get("/webui")
    html = r.text
    assert "window.Mail = (function()" in html
    for fn in ["refresh", "openMail", "loadScenario", "toggleUpload", "handleUpload"]:
        assert fn in html, f"Mail.{fn} missing"


def test_mailbox_has_draft_only_placeholder(client):
    """草稿面板占位 + draft_only 标识 + 铁律①."""
    r = client.get("/webui")
    html = r.text
    assert "draft-panel" in html
    assert "draft_only" in html
    assert "铁律" in html  # 铁律① 文案


def test_mailbox_calls_seven_region_apis(client):
    """JS 中 8 个 region 并行拉 (含 trace, 容错)."""
    r = client.get("/webui")
    html = r.text
    # Mail IIFE 内部的 regions 数组 (字符串字面量)
    assert "'customer'" in html and "'geometry'" in html and "'rag'" in html
    assert "'pending'" in html and "'verification'" in html and "'postmortem'" in html
    assert "'commercial'" in html and "'trace'" in html
    # fetch 模板里有 /context/
    assert "/context/${r}" in html, "context 路径模板缺失"


def test_file_size_under_budget():
    """v4.0.0 + T12 + T2-T4: PRD 预算 webui 1100-1300 行 (v3 1700 + v4 Workbench 800 + T12 黄金链/3D/Ctrl+K/10 邮件 ≈ 3000).

    T2-T4 UI 全端点接线 (+RFQ 管线/飞轮/运维 3 tab, ~250 行) → 上限 3200→3400.
    若 v5 拆 workbench.js 到外部文件, 上限可重新调低.
    """
    p = Path("webui/index.html")
    n = sum(1 for _ in p.open(encoding="utf-8"))
    assert n >= 700, f"webui shrunk unexpectedly: {n}"
    assert n <= 3400, f"webui over budget: {n} lines (v3 1700 + v4 1000 + v5.1 真 3D + 模型面板 + T2-T4 全端点接线)"


def test_workbench_three_columns_dom(client):
    """v4 Workbench 三栏 DOM 结构: wb-shell + 三栏关键子元素 ID."""
    r = client.get("/webui")
    html = r.text
    assert 'class="wb-shell"' in html, "wb-shell 三栏容器缺失"
    # 左 Inbox
    assert 'id="wbInboxList"' in html, "Inbox 列表 id=wbInboxList 缺失"
    # 中 Inspector
    assert 'id="wbInspectBody"' in html, "Inspector body id=wbInspectBody 缺失"
    assert 'data-itab="mail"' in html
    assert 'data-itab="draft"' in html
    assert 'data-itab="approval"' in html
    # 右 Chat
    assert 'id="wbChatThread"' in html, "Chat 线程 id=wbChatThread 缺失"
    assert 'id="wbChatText"' in html, "Chat 输入框 id=wbChatText 缺失"
    assert 'id="wbBindPill"' in html, "Bind Context pill id=wbBindPill 缺失"
    assert 'id="wbSkillConsole"' in html, "Skill Console 抽屉 id=wbSkillConsole 缺失"
    # 状态栏 iron-rule-1
    assert 'iron-rule-1 LOCKED' in html or 'iron-rule-1 🔒' in html, "铁律① LOCKED 状态栏缺失"
