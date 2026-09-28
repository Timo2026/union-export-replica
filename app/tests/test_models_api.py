"""test_models_api.py — 模型设置工具 API 端点 + UI 测试 (不需引擎, 纯配置/探活)."""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from services import model_config as mc
from services.api_server import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_ui_served_at_root(client):
    """v6.0.0: 根路由服务融合版 UI, legacy 模型设置面板迁移至 /webui。"""
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "v6" in r.text  # v6 融合版标识
    r_legacy = client.get("/webui")
    assert r_legacy.status_code == 200
    assert "模型设置" in r_legacy.text


def test_static_assets_mounted(client):
    """v6.1.0 B1: v6 融合 UI 引用的 css/js 静态资源必须 200 (非 404)。"""
    r_css = client.get("/css/workbench.css")
    r_js = client.get("/js/workbench.js")
    assert r_css.status_code == 200, "css/workbench.css 未挂载"
    assert r_js.status_code == 200, "js/workbench.js 未挂载"


def test_ui_has_ab_routing_and_locked_deterministic(client):
    """v2.3.1: UI 应含 A/B 路由关键字 + 确定性角色锁定文案 + 4 个策略选项。(legacy /webui)"""
    r = client.get("/webui")
    assert r.status_code == 200
    html = r.text
    assert "v2.3.1" in html
    assert "A/B" in html
    assert "primary_only" in html
    assert "ab_hash" in html
    assert "ab_round_robin" in html
    assert "fallback" in html
    assert "确定性" in html or "确定性角色" in html
    # deterministic 不应有 ab-llm / ab-ep-deterministic 这类 input id
    assert "id=\"ab-deterministic\"" not in html
    assert "id=\"fb-ep-deterministic\"" not in html


def test_ui_v240_console_5tabs_and_svg_icons(client):
    """v2.4.0 baseline + v3.0.0 第 6 tab Skill 设置。(legacy /webui)"""
    r = client.get("/webui")
    assert r.status_code == 200
    html = r.text
    # 副标题: v6.1.0-fusion (兼容 v3.0.1-mailbox / v3.0.0-nemoclaw / v2.4.0-console 旧断言)
    assert any(m in html for m in ("v6.1.0-fusion", "v3.0.1-mailbox", "v3.0.0-nemoclaw", "v2.4.0-console"))
    # 6 个 nav tab (含 skills)
    for tab in ("models", "demo", "endpoints", "threeD", "feedback", "skills"):
        assert f'data-tab="{tab}"' in html, f"nav button missing for tab={tab}"
    # 6 个 section
    for sec in ("tab-models", "tab-demo", "tab-endpoints", "tab-threeD", "tab-feedback", "tab-skills"):
        assert f'id="{sec}"' in html, f"section missing for id={sec}"
    # SVG icons: nav 内至少 5 个 icon-18, header 至少 1 个
    assert html.count('class="icon-18"') >= 6
    # header 反馈按钮 + 未读 badge
    assert 'id="fbBtn"' in html
    assert 'id="unreadBadge"' in html
    # 3D tab: 拖拽区 + .step/.stp accept
    assert 'id="threeDDrop"' in html
    assert 'accept=".step,.stp"' in html
    # 反馈 tab: 类型选择 + 蜜罐字段
    assert 'name="type"' in html or 'id="fbType"' in html
    assert 'honeypot' in html.lower() or 'hp_field' in html or 'website' in html.lower()
    # 反馈邮箱按钮 mailto 跳转
    assert "agent-feedback@union-export.example" in html or "mailto:" in html
    # v3.0.0 Skill 设置面板关键控件
    assert 'id="dispStrategy"' in html
    assert 'id="skillsList"' in html
    assert 'id="openshellList"' in html
    assert "iron-rule-1" in html or "铁律" in html


def test_get_models_config(client):
    d = client.get("/v1/models/config").json()
    assert "config" in d and "probe" in d
    for k in ("llm", "vlm", "embedding", "ocr", "asr", "deterministic"):
        assert k in d["config"]["models"]
        assert k in d["probe"] and "online" in d["probe"][k]


def test_probe_all_endpoint(client):
    d = client.post("/v1/models/probe").json()
    assert "deterministic" in d and "online" in d["deterministic"]


def test_probe_single_endpoint(client):
    d = client.post("/v1/models/probe", data={"key": "deterministic"}).json()
    assert "deterministic" in d
    assert client.post("/v1/models/probe", data={"key": "nope"}).status_code == 404


def test_save_config_validates_and_rejects_bad(client):
    bad = copy.deepcopy(mc.load())
    bad["models"]["llm"]["endpoint"] = "not-a-url"
    r = client.post("/v1/models/config", json=bad)
    assert r.status_code == 400


def test_save_config_rejects_disabling_deterministic(client):
    bad = copy.deepcopy(mc.load())
    bad["models"]["deterministic"]["enabled"] = False
    # validate 会拦 (deterministic 不可禁用) → 400
    r = client.post("/v1/models/config", json=bad)
    assert r.status_code == 400


def test_save_config_roundtrip_preserves_lock(tmp_path, monkeypatch, client):
    tmp = tmp_path / "models.yaml"
    tmp.write_text(open(mc._MODELS_YAML, encoding="utf-8").read(), encoding="utf-8")
    monkeypatch.setattr(mc, "_MODELS_YAML", tmp)
    cfg = mc.load()
    cfg["models"]["ocr"]["endpoint"] = "http://127.0.0.1:9999"
    r = client.post("/v1/models/config", json=cfg)
    assert r.status_code == 200
    saved = r.json()["config"]
    assert saved["models"]["ocr"]["endpoint"] == "http://127.0.0.1:9999"
    assert saved["models"]["deterministic"]["locked"] is True


def test_skills_registry_endpoint(client):
    d = client.get("/v1/skills").json()
    assert d["registry"]["count"] >= 4
    assert d["cross_check"]["ok"] is True                       # 注册技能都在 allow-list
    tool_names = {t["function"]["name"] for t in d["registry"]["openai_tools"]}
    assert {"cnc_quote", "dfm_conflict", "rfq_extraction", "step_analysis"} <= tool_names


def test_nim_smoke_skips_when_unreachable():
    """无 NIM (本机无 GPU) → nim_smoke 显式 SKIP 且退出码 0, 不抛异常、不阻断。"""
    import subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, str(root / "services" / "nim_smoke.py"),
                        "--url", "http://127.0.0.1:59994/v1"],
                       capture_output=True, text=True, timeout=30,
                       encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0 and "SKIP" in out


def test_feedback_post_get_unread_roundtrip(client):
    """v2.4.0: 反馈邮箱端到端 — POST /v1/feedback 落库, GET /v1/feedback 列出, GET /v1/feedback/unread 计数。"""
    payload = {"type": "feature", "title": "API smoke 测试",
               "body": "v2.4.0 反馈邮箱 roundtrip 验证",
               "email": "qa@union-export.example"}
    r = client.post("/v1/feedback", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "id" in body and body["id"] > 0
    assert "created_at" in body

    # 列表能找到这条
    listed = client.get("/v1/feedback?limit=20").json()
    assert listed["count"] >= 1
    assert any(item["title"] == "API smoke 测试" for item in listed["items"])

    # 未读计数 ≥ 1 (新提交默认 open = 未读)
    unread = client.get("/v1/feedback/unread").json()
    assert unread["unread"] >= 1


def test_feedback_post_rejects_short_title(client):
    """v2.4.0: 标题/正文长度下限 — 阻断空标题和超长 body。"""
    r = client.post("/v1/feedback", json={"type": "bug", "title": "x", "body": "ok"})
    assert r.status_code == 400
    long = "x" * 5001
    r2 = client.post("/v1/feedback", json={"type": "bug", "title": "ok", "body": long})
    assert r2.status_code == 400


def test_feedback_post_rejects_bad_type_and_email(client):
    """v2.4.0: 非法 type + 非法 email → 400。"""
    r = client.post("/v1/feedback", json={"type": "spam", "title": "ok", "body": "ok"})
    assert r.status_code == 400
    r2 = client.post("/v1/feedback", json={"type": "bug", "title": "ok", "body": "ok",
                                            "email": "not-an-email"})
    assert r2.status_code == 400

