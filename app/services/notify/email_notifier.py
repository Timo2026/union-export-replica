"""services.notify.email_notifier — Email SMTP 通知 (mock, draft_only)."""
from __future__ import annotations

import json
import logging
import os
import smtplib
import time
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from .base import NotifierBase, NotificationEvent, build_default_template

log = logging.getLogger(__name__)


class EmailNotifier(NotifierBase):
    """Email SMTP 通知器 (mock 默认实现: 写本地 .eml 文件, 不外发).

    铁律: draft_only — 默认 mock 模式仅写 data/notifications/*.eml, 不真正 SMTP 外发.
    启用真实 SMTP: env EMAIL_SMTP_HOST + EMAIL_SMTP_USER + EMAIL_SMTP_PASSWORD.
    """

    def __init__(self, smtp_host: Optional[str] = None, smtp_port: int = 587,
                 user: Optional[str] = None, password: Optional[str] = None,
                 from_addr: Optional[str] = None, to_addrs: Optional[list] = None,
                 real_send: bool = False):
        super().__init__("email")
        self.smtp_host = smtp_host or os.environ.get("EMAIL_SMTP_HOST", "")
        self.smtp_port = smtp_port
        self.user = user or os.environ.get("EMAIL_SMTP_USER", "")
        self.password = password or os.environ.get("EMAIL_SMTP_PASSWORD", "")
        self.from_addr = from_addr or os.environ.get("EMAIL_FROM_ADDR", "l3@union-mfg.com")
        self.to_addrs = to_addrs or os.environ.get("EMAIL_TO_ADDRS", "ops@union-mfg.com").split(",")
        self.real_send = real_send  # 默认 False (mock)

    def send(self, event: NotificationEvent) -> bool:
        body = build_default_template(event)
        subject = f"[UEA-L3] {event.kind.upper()} · {event.context_id}"
        if not self.real_send:
            return self._write_local(event, subject, body)
        # 铁律①: 真实外发必须过集中式 egress 主闸; 闸关 → 降级本地草稿
        from services.egress_gate import check
        decision = check("smtp")
        if not decision.allowed:
            log.warning("[email-real] egress gate closed (%s) → 降级本地草稿", decision.reason)
            return self._write_local(event, subject, body)
        return self._smtp_send(event, subject, body)

    def _write_local(self, event: NotificationEvent, subject: str, body: str) -> bool:
        try:
            notif_dir = Path("data") / "notifications"
            notif_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{event.kind}_{event.context_id}_{int(time.time())}.eml"
            (notif_dir / fname).write_text(
                f"Subject: {subject}\nTo: {','.join(self.to_addrs)}\nFrom: {self.from_addr}\n\n{body}",
                encoding="utf-8",
            )
            log.info("[email-mock] wrote %s", fname)
            return True
        except Exception as e:
            log.warning("[email-mock] write failed: %r", e)
            return False

    def _smtp_send(self, event: NotificationEvent, subject: str, body: str) -> bool:
        """真实 SMTP (默认禁用)."""
        if not self.smtp_host:
            log.warning("[email-real] smtp_host 缺失")
            return False
        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = self.from_addr
            msg["To"] = ",".join(self.to_addrs)
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as s:
                s.starttls()
                if self.user and self.password:
                    s.login(self.user, self.password)
                s.send_message(msg)
            log.info("[email-real] sent %s for %s", event.kind, event.context_id)
            return True
        except Exception as e:
            log.warning("[email-real] smtp failed: %r", e)
            return False
