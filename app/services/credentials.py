"""credentials.py — 本地凭据加密存储 (Gmail IMAP App Password 等).

铁律①对齐: 凭据永远在 data/credentials.json (sandbox 内), 不出本机.
加密: cryptography.fernet.Fernet (AES-128-CBC + HMAC-SHA256, 已验证).
密钥派生: 固定 app_secret + machine-stable seed (MAC + hostname), 用户无感.
降级: 若 cryptography 缺失, 退到 base64 + 显式标记 insecure; 仍受 0600 文件权限保护.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

CRED_FILE = Path(__file__).resolve().parent.parent / "data" / "credentials.json"
_APP_SECRET = b"union-export-agent-v3-credentials"


def _machine_seed() -> bytes:
    try:
        mac = uuid.getnode().to_bytes(6, "big")
    except Exception:
        mac = b"\x00" * 6
    try:
        host = socket.gethostname().encode("utf-8")
    except Exception:
        host = b"unknown"
    return hashlib.sha256(mac + host).digest()[:16]


def _derive_key() -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(_APP_SECRET + _machine_seed()).digest())


def _fernet_or_none():
    try:
        from cryptography.fernet import Fernet
        return Fernet(_derive_key())
    except Exception:
        return None


def mask_secret(s: str, head: int = 2, tail: int = 2) -> str:
    if not s:
        return ""
    if len(s) <= head + tail:
        return "*" * len(s)
    return s[:head] + "*" * (len(s) - head - tail) + s[-tail:]


def _load_all() -> Dict[str, Any]:
    if not CRED_FILE.exists():
        return {"version": 1, "services": {}}
    try:
        return json.loads(CRED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "services": {}}


def _save_all(data: Dict[str, Any]) -> None:
    CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    # os.O_BINARY 仅 Windows 有; POSIX 回退 0 (跨平台)
    o_binary = getattr(os, "O_BINARY", 0)
    fd = os.open(CRED_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | o_binary, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        raise
    try:
        os.chmod(CRED_FILE, 0o600)
    except (NotImplementedError, PermissionError):
        pass


def save_credentials(service: str, account: str, password: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not service or not account or not password:
        return {"ok": False, "error": "missing service/account/password"}
    fernet = _fernet_or_none()
    if fernet is None:
        encrypted = base64.b64encode(password.encode("utf-8")).decode("ascii")
        cipher = "base64-insecure"
    else:
        encrypted = fernet.encrypt(password.encode("utf-8")).decode("ascii")
        cipher = "fernet-aes128-cbc-hmac-sha256"
    data = _load_all()
    data["services"][service] = {
        "account": account,
        "encrypted": encrypted,
        "cipher": cipher,
        "extra": extra or {},
        "created_at": time.time(),
        "masked": mask_secret(password),
    }
    _save_all(data)
    return {
        "ok": True,
        "service": service,
        "account": account,
        "masked": mask_secret(password),
        "cipher": cipher,
    }


def load_credentials(service: str) -> Optional[Dict[str, Any]]:
    data = _load_all()
    entry = data.get("services", {}).get(service)
    if not entry:
        return None
    encrypted = entry["encrypted"]
    cipher = entry.get("cipher", "fernet")
    try:
        if cipher.startswith("fernet"):
            from cryptography.fernet import Fernet
            plain = Fernet(_derive_key()).decrypt(encrypted.encode("ascii")).decode("utf-8")
        else:
            plain = base64.b64decode(encrypted.encode("ascii")).decode("utf-8")
    except Exception:
        return None
    return {
        "service": service,
        "account": entry["account"],
        "password": plain,
        "extra": entry.get("extra", {}),
        "created_at": entry.get("created_at"),
        "cipher": cipher,
    }


def delete_credentials(service: str) -> bool:
    data = _load_all()
    if service not in data.get("services", {}):
        return False
    del data["services"][service]
    _save_all(data)
    return True


def list_services() -> List[Dict[str, Any]]:
    data = _load_all()
    items = []
    for svc, entry in data.get("services", {}).items():
        items.append({
            "service": svc,
            "account": entry.get("account"),
            "masked": entry.get("masked"),
            "cipher": entry.get("cipher"),
            "created_at": entry.get("created_at"),
        })
    return items


def status() -> Dict[str, Any]:
    fernet = _fernet_or_none()
    return {
        "cred_file": str(CRED_FILE),
        "cred_exists": CRED_FILE.exists(),
        "fernet_available": fernet is not None,
        "services": list_services(),
    }