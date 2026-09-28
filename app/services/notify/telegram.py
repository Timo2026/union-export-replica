"""services.notify.telegram — Telegram Bot API 通知."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Optional

from .base import NotifierBase, NotificationEvent, build_default_template

log = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
DEFAULT_TIMEOUT_S = 8


class TelegramNotifier(NotifierBase):
    """Telegram Bot API 通知器.

    配置: env TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (或 settings.yaml).
    若 token 缺失 → 写 data/notifications/telegram.failed.jsonl + 返 False.
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        super().__init__("telegram")
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.timeout_s = timeout_s

    def send(self, event: NotificationEvent) -> bool:
        if not self.bot_token or not self.chat_id:
            log.warning("[telegram] bot_token/chat_id 缺失, 跳过 (返 False)")
            self._record_failure(event, "config_missing")
            return False
        # 铁律①: webhook 出站必须过集中式 egress 主闸
        from services.egress_gate import check
        decision = check("webhook")
        if not decision.allowed:
            log.warning("[telegram] egress gate closed (%s) → 跳过外发", decision.reason)
            self._record_failure(event, "egress_blocked")
            return False
        text = build_default_template(event)
        url = TELEGRAM_API_BASE.format(token=self.bot_token, method="sendMessage")
        payload = json.dumps({"chat_id": self.chat_id, "text": text,
                             "parse_mode": "Markdown"}).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=payload,
                                        headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                if resp.status == 200:
                    log.info("[telegram] sent %s for %s", event.kind, event.context_id)
                    return True
                log.warning("[telegram] non-200: %s", resp.status)
                self._record_failure(event, f"http_{resp.status}")
                return False
        except Exception as e:
            log.warning("[telegram] send failed: %r", e)
            self._record_failure(event, repr(e))
            return False

    def _record_failure(self, event: NotificationEvent, reason: str) -> None:
        try:
            from pathlib import Path
            failed_path = Path("data") / "notifications" / "telegram.failed.jsonl"
            failed_path.parent.mkdir(parents=True, exist_ok=True)
            with failed_path.open("a", encoding="utf-8") as f:
                rec = {"ts": time.time(), "event": event.to_dict(), "reason": reason}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 不阻塞
