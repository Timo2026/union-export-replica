"""gmail_api.py — /v1/gmail/* 端点: IMAP 连接 + 拉信 + 设置.

铁律①对齐:
- 默认禁用 (gmail_settings.enabled=False). 显式 POST /settings {enabled:true} 才允许 connect.
- 凭据 Fernet 加密存 services/credentials.py, 不存 plaintext, 不外发.
- IMAP 不可达 → 返 error, 不冒充成功.
- 拉信只写 data/mailbox/*.eml (sandbox 内), 跟 v3.0 现有邮件台共享目录.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .credentials import delete_credentials, list_services, status as cred_status
from .gmail_imap import GmailMailbox

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/gmail", tags=["gmail"])

SETTINGS_FILE = Path("data/gmail_settings.json")
DEFAULT_SETTINGS: Dict[str, Any] = {"enabled": False, "host": "imap.gmail.com", "port": 993, "folder": "INBOX"}


def _load_settings() -> Dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        s = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return {**DEFAULT_SETTINGS, **s}
    except Exception:
        return dict(DEFAULT_SETTINGS)


def _save_settings(s: Dict[str, Any]) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


_MAILBOX: Optional[GmailMailbox] = None


def _get_mailbox() -> GmailMailbox:
    global _MAILBOX
    if _MAILBOX is None:
        _MAILBOX = GmailMailbox()
    return _MAILBOX


@router.get("/settings")
def get_settings():
    return JSONResponse({"settings": _load_settings(), "credentials": cred_status()})


@router.post("/settings")
async def post_settings(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid json body")
    s = _load_settings()
    if "enabled" in body:
        s["enabled"] = bool(body["enabled"])
    if "host" in body and isinstance(body["host"], str):
        s["host"] = body["host"]
    if "port" in body:
        s["port"] = int(body["port"])
    if "folder" in body and isinstance(body["folder"], str):
        s["folder"] = body["folder"]
    _save_settings(s)
    return JSONResponse({"saved": True, "settings": s})


@router.post("/connect")
async def connect(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid json body")
    s = _load_settings()
    if not s.get("enabled"):
        raise HTTPException(403, "gmail disabled. POST /v1/gmail/settings {\"enabled\": true} first")
    email = (body.get("email") or "").strip()
    app_password = (body.get("app_password") or "").strip()
    if not email or not app_password:
        raise HTTPException(400, "missing email or app_password")
    from .credentials import save_credentials
    save_credentials("gmail", email, app_password)
    mb = _get_mailbox()
    res = mb.connect()
    return JSONResponse(res)


@router.post("/disconnect")
def disconnect():
    delete_credentials("gmail")
    mb = _get_mailbox()
    mb.disconnect()
    return JSONResponse({"ok": True, "disconnected": True})


@router.post("/sync")
def sync(folder: Optional[str] = None, limit: int = 50):
    s = _load_settings()
    if not s.get("enabled"):
        raise HTTPException(403, "gmail disabled")
    mb = _get_mailbox()
    res = mb.sync(folder=folder or s.get("folder", "INBOX"), limit=limit)
    # LINK-3 (E1 #34): 手动 sync 也要入 pending 队列, 否则黄金链无人消费
    try:
        if isinstance(res, dict) and res.get("ok") and res.get("fetched"):
            from .mail_puller import get_puller
            res["enqueued"] = get_puller()._enqueue_pending_from_mailbox()
    except Exception as e:
        log.warning("[gmail/sync] enqueue pending 失败 (不冒充成功): %r", e)
        res = {**res, "enqueued": 0, "enqueue_error": repr(e)}
    return JSONResponse(res)


@router.get("/status")
def status():
    s = _load_settings()
    mb = _get_mailbox()
    return JSONResponse({
        "settings": s,
        "credentials": cred_status(),
        "mailbox": mb.status(),
    })