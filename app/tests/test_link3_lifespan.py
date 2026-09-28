"""test_link3_lifespan.py — LINK-3 邮件无人值守接线 (任务 #34 E1).

审计原话: puller/orchestrator 只有测试调用, uvicorn 入口无 lifespan 钩子;
/v1/gmail/sync 写 .eml 但不入 pending 队列.
铁律门禁: puller.is_enabled() 需 gmail_settings.enabled + 凭据, 默认 noop;
测试进程由 conftest 设 UEA_MAIL_AUTOSTART=0 双保险, 真实 IMAP 永不自动连.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import services.mail_orchestrator as mo
import services.mail_puller as mp
from services import api_server as apiserver


class FakePuller:
    instances: list = []

    def __init__(self, root=None, **kwargs):
        self.root = root
        self.kwargs = kwargs
        self.started = self.stopped = False
        FakePuller.instances.append(self)

    def is_enabled(self):
        return True

    def start(self):
        self.started = True
        return {"ok": True, "running": True}

    def stop(self, timeout=5.0):
        self.stopped = True
        return {"ok": True}

    def status(self):
        return {"state": {}, "pending": {"total": 0}, "enabled": True}


class FakeOrchestrator:
    instances: list = []

    def __init__(self, root=None, puller=None, cat=None, **kwargs):
        self.root = root
        self.puller = puller
        self.cat = cat
        self.loop_started = self.stopped = False
        FakeOrchestrator.instances.append(self)

    def start_loop(self, poll_interval_s=5.0):
        self.loop_started = True
        return {"ok": True}

    def stop(self, timeout=5.0):
        self.stopped = True
        return {"ok": True}


def _patch_fakes(monkeypatch, puller_enabled=True):
    FakePuller.instances.clear()
    FakeOrchestrator.instances.clear()
    monkeypatch.setattr(FakePuller, "is_enabled", lambda self: puller_enabled)
    monkeypatch.setattr(mp, "MailPuller", FakePuller)
    monkeypatch.setattr(mo, "MailOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(apiserver, "build_controller",
                        lambda root=None, **kw: object())
    monkeypatch.setenv("UEA_MAIL_AUTOSTART", "1")


def test_lifespan_starts_and_stops_puller_and_orchestrator(monkeypatch):
    _patch_fakes(monkeypatch, puller_enabled=True)
    with TestClient(apiserver.app):
        pass
    assert len(FakePuller.instances) == 1
    assert len(FakeOrchestrator.instances) == 1
    p, o = FakePuller.instances[0], FakeOrchestrator.instances[0]
    assert p.started and p.stopped
    assert o.loop_started and o.stopped
    assert o.puller is p


def test_lifespan_noop_when_puller_disabled(monkeypatch):
    _patch_fakes(monkeypatch, puller_enabled=False)
    with TestClient(apiserver.app):
        pass
    assert len(FakePuller.instances) == 1
    assert not FakePuller.instances[0].started
    assert FakeOrchestrator.instances == []


def test_kill_switch_env_zero_never_constructs_puller(monkeypatch):
    _patch_fakes(monkeypatch, puller_enabled=True)
    monkeypatch.setenv("UEA_MAIL_AUTOSTART", "0")
    with TestClient(apiserver.app):
        pass
    assert FakePuller.instances == []


def test_conftest_kill_switch_active_under_pytest():
    """pytest 进程默认必须带 UEA_MAIL_AUTOSTART=0 (conftest 双保险)."""
    import os
    assert os.environ.get("UEA_MAIL_AUTOSTART") == "0"


def test_gmail_sync_enqueues_pending(tmp_path, monkeypatch):
    """/v1/gmail/sync 拉到信后必须扫 mailbox 入 pending 队列 (LINK-3 后半)."""
    import services.gmail_api as ga

    pulled_dir = tmp_path / "data" / "mailbox"
    pulled_dir.mkdir(parents=True)
    (pulled_dir / "M-77.eml").write_bytes(b"Subject: x\n\nbody")
    (pulled_dir / "M-77.meta.json").write_text(
        json.dumps({"badges": ["NEW", "GMAIL_PULLED"]}), encoding="utf-8")

    puller = mp.MailPuller(root=tmp_path)

    monkeypatch.setattr(mp, "get_puller", lambda root=None, **kw: puller)
    monkeypatch.setattr(ga, "_load_settings",
                        lambda: {"enabled": True, "folder": "INBOX"})
    fake_mb = type("MB", (), {"sync": lambda self, **kw:
                              {"ok": True, "fetched": 1, "skipped": 0}})()
    monkeypatch.setattr(ga, "_get_mailbox", lambda: fake_mb)

    res = json.loads(ga.sync().body.decode())
    assert res["ok"] is True
    assert res["enqueued"] == 1
    assert "enqueue_error" not in res
    pending = (tmp_path / "data" / "mail_puller" / "pending.jsonl").read_text(encoding="utf-8")
    assert '"M-77"' in pending and '"new"' in pending.lower()
    # 已入队的 mail_id 不重复 enqueue
    res2 = json.loads(ga.sync().body.decode())
    assert res2["enqueued"] == 0
