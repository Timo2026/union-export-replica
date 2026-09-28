"""supplier_module — v2.3.0 客户确认后履约流水线。

入口：desensitize → supplier_db → matcher → supplier_inbox(mock) → po_generator
契约："数据不出车间"——所有流向供应商的工件必须经 desensitize。
"""
from __future__ import annotations

__all__ = [
    "desensitize",
    "fingerprint_customer",
    "DesensitizeRequest",
    "DesensitizedPackage",
]