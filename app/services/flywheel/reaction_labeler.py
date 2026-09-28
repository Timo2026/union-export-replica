"""flywheel.reaction_labeler — 全自动规则客户反应打标.

决策锁定 (2026-09-19): 全自动规则
  - 30d 无回 = silent
  - 客户回邮 = reacting
  - 付款确认 = won
  - 明确拒绝 = lost
  - 未发报价 = pending (等待发)

豁免: vacation_override (客户标记休假 → silent 判定延后)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# 可配置阈值 (秒)
DAY = 86400.0
DEFAULT_SILENT_DAYS = 30
DEFAULT_FOLLOWUP_DAYS = 7
DEFAULT_LOST_DAYS = 90


class Reaction(str, Enum):
    PENDING = "pending"        # 报价已发, 等待反应
    REACTING = "reacting"      # 客户有回复 (未付款也未拒绝)
    WON = "won"                # 成交
    LOST = "lost"              # 明确拒绝 / 超时未成交
    SILENT = "silent"          # 沉默 (超阈值无回复)


@dataclass
class LabelResult:
    reaction: str
    days_since: float
    reason: str
    confidence: float       # 0..1
    vacation_exempt: bool = False


class ReactionLabeler:
    """纯规则打标器. 不调 LLM, 不联网, 可降级."""

    def __init__(self, silent_days: int = DEFAULT_SILENT_DAYS,
                 lost_days: int = DEFAULT_LOST_DAYS):
        self.silent_s = silent_days * DAY
        self.lost_s = lost_days * DAY

    def label(self, ctx: Dict[str, Any],
              quote_sent_at: Optional[float] = None,
              customer_reply_at: Optional[float] = None,
              payment_at: Optional[float] = None,
              explicit_reject: bool = False,
              vacation_until: Optional[float] = None,
              now: Optional[float] = None) -> LabelResult:
        """根据已知事实打标.

        优先级 (高 → 低):
          1. explicit_reject=True → LOST
          2. payment_at 存在 → WON
          3. customer_reply_at 存在 → REACTING
          4. 超过 silent 阈值且无豁免 → SILENT
          5. 超过 lost 阈值 → LOST
          6. 否则 → PENDING
        """
        now = now or time.time()
        sent = quote_sent_at or ctx.get("_quote_sent_at") or ctx.get("created_at") or now
        days = (now - sent) / DAY

        # vacation 豁免窗口
        vacation_exempt = False
        if vacation_until and now < vacation_until:
            vacation_exempt = True

        # 1. 明确拒绝
        if explicit_reject:
            return LabelResult(Reaction.LOST.value, days, "explicit_reject", 1.0)

        # 2. 付款
        if payment_at:
            return LabelResult(Reaction.WON.value, days, "payment_confirmed", 1.0)

        # 3. 客户回复
        if customer_reply_at:
            return LabelResult(Reaction.REACTING.value, days, "customer_replied", 0.85)

        # 4. 沉默判定 (含 vacation 豁免)
        elapsed = now - sent
        if elapsed > self.lost_s:
            return LabelResult(Reaction.LOST.value, days,
                               f"timeout_{self.lost_s/DAY:.0f}d_no_response", 0.7)

        if elapsed > self.silent_s:
            if vacation_exempt:
                return LabelResult(Reaction.PENDING.value, days,
                                   "vacation_exempt", 0.6, vacation_exempt=True)
            return LabelResult(Reaction.SILENT.value, days,
                               f"silent_{self.silent_s/DAY:.0f}d", 0.75)

        # 5. 等待中
        return LabelResult(Reaction.PENDING.value, days, "awaiting_response", 0.5)

    def label_quote_row(self, row: Dict[str, Any], now: Optional[float] = None) -> LabelResult:
        """从 crm.quotes 行打标 (适配现有 schema)."""
        return self.label(
            ctx={},
            quote_sent_at=row.get("created_at"),
            customer_reply_at=row.get("_replied_at"),
            payment_at=row.get("_paid_at"),
            explicit_reject=row.get("_rejected") is True,
            vacation_until=row.get("_vacation_until"),
            now=now,
        )
