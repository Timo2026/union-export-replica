"""test_config_reload_wiring.py — E-03 config_reload 生产接线 (任务 #34 E1).

hot_settings/hot_skills 此前只有测试导入 (AUDIT-v7 F5). 接线 = api_server 暴露
POST /v1/config/reload (强制重读 + 校验回滚结果) 与 GET /v1/config/status.
"""
from __future__ import annotations

import services.config_reload as cr
from fastapi.testclient import TestClient

from services import api_server as apiserver


def test_reload_endpoint_returns_per_key_status():
    cr.reset_singletons()
    try:
        with TestClient(apiserver.app) as c:
            r = c.post("/v1/config/reload")
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True
            assert {"settings", "skills"} <= set(body["configs"])
            assert body["configs"]["settings"]["reload_count"] >= 1
    finally:
        cr.reset_singletons()


def test_reload_rollback_on_invalid_skills():
    """坏配置 → 校验失败 → 保留上一份有效 (safe rollback); 修好后 /reload 恢复 ok."""
    cr.reset_singletons()
    try:
        hc = cr.hot_skills()
        good = hc.get()
        assert good is not None and hc.last_error == []
        hc._validator = lambda d: ["injected-invalid"]   # 模拟热载到坏配置
        hc._mtime = 0.0                                  # 强制视为文件变更
        val = hc.get()
        assert val is good                               # rollback: 仍是上一份有效
        assert hc.last_error == ["injected-invalid"]
        hc._validator = __import__("services.skill_config", fromlist=["validate"]).validate
        hc._mtime = 0.0                          # 再模拟一次"文件已修复变更"
        with TestClient(apiserver.app) as c:
            r = c.post("/v1/config/reload")
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True                    # 恢复有效配置如实上报
            assert body["configs"]["skills"]["reload_count"] >= 3
    finally:
        cr.reset_singletons()


def test_status_endpoint():
    with TestClient(apiserver.app) as c:
        r = c.get("/v1/config/status")
        assert r.status_code == 200
        body = r.json()
        assert "settings" in body and "skills" in body
