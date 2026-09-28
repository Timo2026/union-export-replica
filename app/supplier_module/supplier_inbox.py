"""supplier_inbox.py — v2.3.0 供应商收件箱（mock 默认 + IMAP 占位）。

设计原则：数据不出车间。
  - MockInbox: 内置响应模板，**默认**所有 v2.3.0 流水线都走这个。
  - IMAPInbox: 必须显式 `enabled=True` 才会执行 fetch，否则 raise NotImplementedError。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Protocol, Union


@dataclass
class SupplierQuote:
    supplier_id: int
    unit_price_cny: float
    lead_time_days: int
    quality: str
    confidence: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "SupplierQuote":
        return cls(**d)


class SupplierInbox(Protocol):
    def fetch_quotes(
        self, pipeline_id: str, supplier_ids: List[int]
    ) -> List[SupplierQuote]: ...


class MockInbox:
    """内置响应：responses 字典 {supplier_id: SupplierQuote or None}。

    None 表示"未响应"，会被 fallback 替换。
    """

    def __init__(
        self,
        responses: Optional[Dict[int, Union[SupplierQuote, None]]] = None,
        fallback_unit_price: float = 0.0,
        fallback_lead_time_days: int = 30,
        fallback_quality: str = "ISO9001",
    ):
        self.responses = responses or {}
        self.fallback_unit_price = fallback_unit_price
        self.fallback_lead_time_days = fallback_lead_time_days
        self.fallback_quality = fallback_quality

    def fetch_quotes(
        self, pipeline_id: str, supplier_ids: List[int]
    ) -> List[SupplierQuote]:
        out: List[SupplierQuote] = []
        for sid in supplier_ids:
            resp = self.responses.get(sid)
            if resp is None:
                # 未响应 → fallback
                out.append(SupplierQuote(
                    supplier_id=sid,
                    unit_price_cny=self.fallback_unit_price,
                    lead_time_days=self.fallback_lead_time_days,
                    quality=self.fallback_quality,
                    confidence=0.0,
                ))
            else:
                out.append(resp)
        return out


class IMAPInbox:
    """IMAP 真实邮箱接入（v2.3.0 不实现，仅占位契约）。

    必须显式 enabled=True 才会执行（避免生产意外外发）。
    """

    def __init__(self, host: str = "", user: str = "", password: str = "",
                 enabled: bool = False):
        self.host = host
        self.user = user
        self.password = password
        self.enabled = enabled

    def fetch_quotes(
        self, pipeline_id: str, supplier_ids: List[int]
    ) -> List[SupplierQuote]:
        if not self.enabled:
            raise NotImplementedError(
                "IMAPInbox is egress-disabled by default; "
                "explicitly set enabled=True and provide IMAP creds. "
                "v2.3.0 ships with MockInbox only."
            )
        # 占位：返回一个模拟响应（不连真实 IMAP）
        return [
            SupplierQuote(
                supplier_id=sid,
                unit_price_cny=250.0,
                lead_time_days=15,
                quality="ISO9001",
                confidence=0.7,
            )
            for sid in supplier_ids
        ]