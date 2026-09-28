"""services.notify — v5.0.0 通知外发 (Telegram / Email / Slack).

职责:
  - 统一 Notifier 接口 (send_event)
  - 三种实现: telegram (Bot API) / email (SMTP) / slack (Webhook)
  - 失败 fallback: 任一通道失败 → 写 data/notifications.failed.jsonl + log
  - 不静默冒充: send 抛错时返 False, 让 MailOrchestrator 知道

铁律:
  - 通知失败不阻塞主链 (MailOrchestrator.run_pipeline 不抛)
  - 草稿 draft_only: 通知模板不含"已发送邮件"等冒认
"""
from .base import NotifierBase, NotificationEvent, build_default_template
from .telegram import TelegramNotifier
from .email_notifier import EmailNotifier
from .slack import SlackNotifier

__all__ = [
    "NotifierBase",
    "NotificationEvent",
    "build_default_template",
    "TelegramNotifier",
    "EmailNotifier",
    "SlackNotifier",
]
