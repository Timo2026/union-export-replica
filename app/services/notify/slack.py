"""services.notify.slack — Slack Webhook 通知 (stub)."""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Optional

from .base import NotifierBase, NotificationEvent, build_default_template

log = logging.getLogger(__name__)


class SlackNotifier(NotifierBase):
    """Slack Webhook 通知器 (stub).

    配置: env SLACK_WEBHOOK_URL.
    未配置时返 False (降级到本地 log).
    """

    def __init__(self, webhook_url: Optional[str] = None, timeout_s: float = 8):
        super().__init__("slack")
        self.webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
        self.timeout_s = timeout_s

    def send(self, event: NotificationEvent) -> bool:
        if not self.webhook_url:
            log.debug("[slack] webhook_url 缺失, 跳过")
            return False
        # 铁律①: webhook 出站必须过集中式 egress 主闸
        from services.egress_gate import check
        decision = check("webhook")
        if not decision.allowed:
            log.warning("[slack] egress gate closed (%s) → 跳过外发", decision.reason)
            return False
        text = build_default_template(event)
        payload = json.dumps({"text": text}).encode("utf-8")
        try:
            req = urllib.request.Request(self.webhook_url, data=payload,
                                        headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return resp.status == 200
        except Exception as e:
            log.warning("[slack] send failed: %r", e)
            return False
