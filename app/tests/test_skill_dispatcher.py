"""test_skill_dispatcher.py — 路由 / 编排 / OpenShell 拦截 / 设置 API."""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from services import skill_config as sc
from services.skill_dispatcher import SkillDispatcher, rule_route
from services.openshell import OpenShell
from skills import _runtime as rt


@pytest.fixture(scope="module")
def client():
    from services.api_server import app
    with TestClient(app) as c:
        yield c


def test_rule_route_quote_intent():
    r = rule_route("客户要 CNC 报价，50 件 6061", [])
    assert "calc_quote" in r["skills"]
    assert "parse_rfq" in r["skills"]
    assert r["source"] == "rules"


def test_rule_route_feedback_intent():
    r = rule_route("我要提交一个 bug 反馈", [])
    assert r["skills"] == ["submit_feedback"]


def test_rule_route_golden_chain():
    r = rule_route("跑一遍黄金链端到端", [])
    assert r["skills"] == ["golden_chain"]


def test_rule_route_adds_thumbnail_for_step():
    r = rule_route("帮我处理这个零件", ["data/samples/a.step"])
    assert "render_thumbnail" in r["skills"]


def test_runtime_discovers_skill_tools():
    reg = rt.discover(force=True)
    for sid in ("parse_rfq", "check_dfm", "calc_quote", "submit_feedback",
                "render_thumbnail", "golden_chain"):
        assert sid in reg, f"missing skill tool: {sid}"


def test_dispatch_feedback_skill_offline_friendly():
    cfg = sc.default_config()
    cfg["dispatcher"]["strategy"] = "rules_only"
    disp = SkillDispatcher(cfg=cfg)
    resp = disp.dispatch(intent="提交反馈：界面按钮错位", args={
        "type": "bug", "title": "按钮错位", "body": "保存按钮在 1080p 下被裁切",
    })
    assert resp["dispatch_id"]
    assert "submit_feedback" in resp["executed_skills"] or \
           any(t.get("skill") == "submit_feedback" for t in resp["trace"])
    # 不应因 LLM 离线而整体失败
    assert resp["route"]["source"] in ("rules", "explicit") or resp["route"].get("strategy", "").startswith("auto")


# ---- P0 driver 标记: dispatch 默认 console + 显式透传 + audit 落盘 ----
def test_dispatch_driver_marker_default_console():
    cfg = sc.default_config()
    cfg["dispatcher"]["strategy"] = "rules_only"
    disp = SkillDispatcher(cfg=cfg)
    resp = disp.dispatch(intent="提交反馈：driver 默认值测试", args={
        "type": "bug", "title": "t", "body": "xxxxx",
    })
    assert resp["driver"] == "console"  # 控制台发起默认 console


def test_dispatch_driver_marker_explicit_and_audit():
    import json
    from services.skill_dispatcher import _AUDIT_PATH
    cfg = sc.default_config()
    cfg["dispatcher"]["strategy"] = "rules_only"
    disp = SkillDispatcher(cfg=cfg)
    resp = disp.dispatch(intent="提交反馈：driver 显式测试", driver="email", args={
        "type": "bug", "title": "t", "body": "xxxxx",
    })
    assert resp["driver"] == "email"
    if _AUDIT_PATH.exists():
        lines = [l for l in _AUDIT_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
        last = json.loads(lines[-1])
        assert last.get("driver") == "email"
        assert last.get("dispatch_id") == resp["dispatch_id"]


def test_dispatch_blocks_disabled_skill():
    cfg = sc.default_config()
    cfg["dispatcher"]["strategy"] = "rules_only"
    cfg["skills"] = {"submit_feedback": {"enabled": False, "label": "反馈"}}
    disp = SkillDispatcher(cfg=cfg)
    resp = disp.dispatch(intent="提交反馈", args={"type": "bug", "title": "t", "body": "xxxxx"})
    assert "submit_feedback" not in resp["executed_skills"]
    assert any(s.get("skill") == "submit_feedback" for s in resp["skipped"])


# ---- MEDIA 富输出协议 (workshop 复刻): skill 输出 media → resp["media"] ----
def test_dispatch_aggregates_media(monkeypatch):
    """skill output 带 media 列表 → dispatch resp 聚合出 media + MEDIA: 行."""
    from skills import _runtime as rt
    monkeypatch.setattr(rt, "execute", lambda sid, args, ctx: {
        "ok": True, "skill": sid,
        "media": [{"kind": "svg", "path": "data/cache/thumb/abc.svg"}],
    })
    cfg = sc.default_config()
    cfg["dispatcher"]["strategy"] = "rules_only"
    disp = SkillDispatcher(cfg=cfg)
    resp = disp.dispatch(intent="生成缩略图", files=["data/samples/a.step"],
                         args={"path": "data/samples/a.step"})
    assert resp["media"] == [{"kind": "svg", "path": "data/cache/thumb/abc.svg"}]
    # MEDIA: 行供 agent 平面原样粘进回复 (workshop 协议)
    assert "MEDIA:data/cache/thumb/abc.svg" in resp["media_lines"]
    assert "MEDIA:" in resp["media_lines"][0]


def test_dispatch_media_empty_when_no_skill_outputs_media():
    cfg = sc.default_config()
    cfg["dispatcher"]["strategy"] = "rules_only"
    disp = SkillDispatcher(cfg=cfg)
    resp = disp.dispatch(intent="提交反馈：无 media 场景", args={
        "type": "bug", "title": "media 测试", "body": "xxxxx",
    })
    assert resp["media"] == []
    assert resp["media_lines"] == []


def test_dispatch_blocks_path_outside_sandbox():
    cfg = sc.default_config()
    cfg["dispatcher"]["strategy"] = "rules_only"
    disp = SkillDispatcher(cfg=cfg)
    resp = disp.dispatch(
        intent="生成缩略图",
        files=["C:/Windows/evil.step"],
        args={"path": "C:/Windows/evil.step"},
    )
    # render_thumbnail 应被 local-only 拦下
    assert any(
        (t.get("skill") == "render_thumbnail" and (t.get("skipped") or t.get("violations")))
        or (s.get("skill") == "render_thumbnail")
        for t in resp["trace"] for s in [t]
    ) or any(s.get("skill") == "render_thumbnail" for s in resp["skipped"]) or \
        any("local-only" in str(v) for v in resp["openshell_violations"])
    assert "render_thumbnail" not in resp["executed_skills"] or resp["openshell_violations"]


def test_iron_rule_override_blocked_in_dispatch():
    """确定性 skill 输出锁定后, 篡改应被 OpenShell 拒绝."""
    cfg = sc.default_config()
    cfg["dispatcher"]["strategy"] = "rules_only"
    disp = SkillDispatcher(cfg=cfg)
    # 直接注入确定性输出锁
    shell = disp.shell
    original = {"unit_price": 222.8, "final_price": 9413.3, "ok": True, "skill": "calc_quote"}
    shell.postcheck("calc_quote", original, iron_rule="deterministic")
    tampered = dict(original)
    tampered["final_price"] = 1.0
    attempt = shell.attempt_override("calc_quote", tampered)
    assert attempt["allowed"] is False


def test_skills_config_api_get(client):
    d = client.get("/v1/skills/config").json()
    assert "summary" in d and "config" in d
    assert d.get("iron_rule_1_locked") is True
    ids = {s["id"] for s in d["summary"]["skills"]}
    assert "calc_quote" in ids and "parse_rfq" in ids
    pol = {p["id"]: p for p in d["summary"]["openshell"]}
    assert pol["iron-rule-1"]["locked"] is True
    assert pol["iron-rule-1"]["enabled"] is True


def test_skills_config_api_reject_disabling_iron_rule(client):
    payload = {
        "version": 3,
        "dispatcher": {"strategy": "rules_only", "llm_role": "llm",
                       "fallback_rules": True, "max_skills_per_task": 8, "audit_max": 50},
        "skills": {},
        "openshell": {"iron-rule-1": {"enabled": False, "locked": True}},
        "model_router": {"source": "rules_only"},
    }
    r = client.post("/v1/skills/config", json=payload)
    assert r.status_code == 400
    assert "iron-rule-1" in r.text


def test_skills_config_api_save_roundtrip(client):
    # 先读再改 strategy 保存
    cur = client.get("/v1/skills/config").json()["config"]
    cfg = copy.deepcopy(cur)
    cfg.setdefault("dispatcher", {})["strategy"] = "rules_only"
    cfg.setdefault("openshell", {})["iron-rule-1"] = {"enabled": True, "locked": True}
    r = client.post("/v1/skills/config", json=cfg)
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert body["config"]["dispatcher"]["strategy"] == "rules_only"
    # 恢复 auto
    cfg["dispatcher"]["strategy"] = "auto"
    client.post("/v1/skills/config", json=cfg)


def test_agent_task_api_feedback(client):
    r = client.post("/v1/agent/task", json={
        "intent": "提交反馈：测试 NemoClaw 调度",
        "args": {"type": "feature", "title": "skill panel", "body": "希望 Skill 面板可搜索过滤"},
    })
    assert r.status_code == 200
    d = r.json()
    assert d["dispatch_id"]
    assert "trace" in d
    assert "openshell_violations" in d


# ---- P0 driver 标记: /v1/agent/task 默认 agent + 显式透传 + 非法值 400 ----
def test_agent_task_api_driver_default_agent(client):
    r = client.post("/v1/agent/task", json={
        "intent": "提交反馈：driver 默认值",
        "args": {"type": "bug", "title": "t", "body": "xxxxx"},
    })
    assert r.status_code == 200
    assert r.json()["driver"] == "agent"


def test_agent_task_api_driver_explicit_console(client):
    r = client.post("/v1/agent/task", json={
        "intent": "提交反馈：driver 显式 console",
        "driver": "console",
        "args": {"type": "bug", "title": "t", "body": "xxxxx"},
    })
    assert r.status_code == 200
    assert r.json()["driver"] == "console"


def test_agent_task_api_invalid_driver_rejected(client):
    r = client.post("/v1/agent/task", json={
        "intent": "提交反馈：driver 非法值",
        "driver": "carrier-pigeon",
        "args": {"type": "bug", "title": "t", "body": "xxxxx"},
    })
    assert r.status_code == 400


def test_agent_task_api_requires_intent(client):
    r = client.post("/v1/agent/task", json={})
    assert r.status_code == 400


def test_agent_route_api(client):
    r = client.post("/v1/agent/route", json={"intent": "我要报价 50 件 6061"})
    assert r.status_code == 200
    d = r.json()
    assert "skills" in d
    assert "calc_quote" in d["skills"] or "golden_chain" in d["skills"]


def test_agent_openshell_api(client):
    r = client.get("/v1/agent/openshell")
    assert r.status_code == 200
    d = r.json()
    assert "openshell" in d and "policies" in d["openshell"]
    iron = next(p for p in d["openshell"]["policies"] if p["id"] == "iron-rule-1")
    assert iron["locked"] is True
