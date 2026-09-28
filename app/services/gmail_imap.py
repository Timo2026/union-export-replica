"""gmail_imap.py — Gmail IMAP 拉信封装 (imap_tools, Apache-2.0).

铁律①对齐:
- 凭据从 services.credentials 读 (Fernet 解密), 不存 plaintext, 不外发
- 默认禁用 (services/skill_config + settings 双重门禁)
- 拉的邮件只写本地 data/mailbox/*.eml, 不外发
- IMAP 不可达 → 返回 error, 不静默冒充
- 测试用 monkeypatch imap_tools.MailBox 注入 mock, 不真连
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .credentials import load_credentials

log = logging.getLogger(__name__)
SERVICE_NAME = "gmail"
DEFAULT_HOST = "imap.gmail.com"
QQ_HOST = "imap.qq.com"
DEFAULT_PORT = 993
DEFAULT_FOLDER = "INBOX"


class GmailMailbox:
    """IMAP 拉信封装. service 参数 = credentials 键 + 来源标签 (gmail/qq/...)."""

    def __init__(
        self,
        mailbox_dir: Optional[Path] = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        mailbox_factory: Optional[Callable[[str, int], Any]] = None,
        service: str = SERVICE_NAME,
    ):
        self.mailbox_dir = Path(mailbox_dir) if mailbox_dir else Path("data/mailbox")
        self.host = host
        self.port = port
        self.service = service
        self._factory = mailbox_factory
        self._client = None
        self.last_sync_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self.last_count: int = 0
        self.last_account: Optional[str] = None

    def _make_client(self):
        if self._factory:
            return self._factory(self.host, self.port)
        from imap_tools import MailBox
        return MailBox(self.host, port=self.port)

    def connect(self) -> Dict[str, Any]:
        cred = load_credentials(self.service)
        if not cred:
            self.last_error = "no credentials saved"
            return {"ok": False, "error": self.last_error}
        try:
            client = self._make_client()
            client.login(cred["account"], cred["password"])
            self._client = client
            self.last_account = cred["account"]
            self.last_error = None
            return {"ok": True, "account": cred["account"], "host": self.host, "port": self.port}
        except Exception as e:
            self.last_error = repr(e)
            self._client = None
            return {"ok": False, "error": repr(e), "host": self.host}

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.logout()
            except Exception:
                pass
            self._client = None

    def _mail_id_for(self, uid: str, msg_date: str, msg_from: str) -> str:
        raw = f"{uid}|{msg_date}|{msg_from}".encode("utf-8", errors="ignore")
        return self.service + "_" + hashlib.sha256(raw).hexdigest()[:16]

    @staticmethod
    def _addr_to_str(addr: Any) -> str:
        # imap_tools>=1.10 返回 EmailAddress(name, email) 对象而非 str
        name = getattr(addr, "name", None)
        email = getattr(addr, "email", None)
        if email is None:
            return str(addr)
        return f"{name} <{email}>" if name else str(email)

    @staticmethod
    def _clean_header(value: Any) -> str:
        # RFC2047 折叠头解码后可能含 \r\n, email 库拒绝 → 压平防头注入
        return " ".join(str(value or "").split())

    @classmethod
    def _msg_to_eml_bytes(cls, msg) -> bytes:
        em = EmailMessage()
        em["From"] = cls._clean_header(msg.from_)
        if msg.to_values:
            em["To"] = cls._clean_header(", ".join(cls._addr_to_str(a) for a in msg.to_values))
        if msg.cc_values:
            em["Cc"] = cls._clean_header(", ".join(cls._addr_to_str(a) for a in msg.cc_values))
        em["Subject"] = cls._clean_header(msg.subject)
        if msg.date_str:
            em["Date"] = cls._clean_header(msg.date_str)
        body = msg.text or msg.html or ""
        em.set_content(body)
        return em.as_bytes()

    def sync(self, folder: str = DEFAULT_FOLDER, limit: int = 50) -> Dict[str, Any]:
        if self._client is None:
            r = self.connect()
            if not r.get("ok"):
                return {"ok": False, "error": r.get("error"), "fetched": 0, "skipped": 0}
        self.mailbox_dir.mkdir(parents=True, exist_ok=True)
        fetched = 0
        skipped = 0
        try:
            self._client.folder.set(folder)
            for msg in self._client.fetch(limit=limit, reverse=True):
                uid = str(msg.uid)
                mid = self._mail_id_for(uid, msg.date_str or "", msg.from_ or "")
                eml_path = self.mailbox_dir / f"{mid}.eml"
                meta_path = self.mailbox_dir / f"{mid}.meta.json"
                if eml_path.exists():
                    skipped += 1
                    continue
                eml_bytes = self._msg_to_eml_bytes(msg)
                eml_path.write_bytes(eml_bytes)
                meta = {
                    "uid": uid,
                    "folder": folder,
                    "account": self.last_account,
                    "received_at": time.time(),
                    "context_id": None,
                    "customer_id": None,
                    "badges": ["NEW", self.service.upper() + "_PULLED"],
                    "source": self.service + "-imap",
                    "from": msg.from_ or "",
                    "subject": msg.subject or "",
                    "size_bytes": len(eml_bytes),
                    "attachments_count": len(msg.attachments or []),
                }
                meta_path.write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                fetched += 1
        except Exception as e:
            self.last_error = repr(e)
            return {
                "ok": False,
                "error": repr(e),
                "fetched": fetched,
                "skipped": skipped,
                "folder": folder,
            }
        self.last_sync_at = time.time()
        self.last_count = fetched
        self.last_error = None
        return {
            "ok": True,
            "fetched": fetched,
            "skipped": skipped,
            "folder": folder,
            "mailbox_dir": str(self.mailbox_dir),
        }

    def status(self) -> Dict[str, Any]:
        return {
            "service": self.service,
            "host": self.host,
            "port": self.port,
            "connected": self._client is not None,
            "last_account": self.last_account,
            "last_sync_at": self.last_sync_at,
            "last_count": self.last_count,
            "last_error": self.last_error,
            "mailbox_dir": str(self.mailbox_dir),
        }


_global: Optional[GmailMailbox] = None


def get_mailbox(mailbox_dir: Optional[Path] = None, **kwargs) -> GmailMailbox:
    global _global
    if _global is None:
        _global = GmailMailbox(mailbox_dir=mailbox_dir, **kwargs)
    return _global


def reset_global() -> None:
    global _global
    if _global is not None:
        _global.disconnect()
    _global = None