"""po_generator.py — v2.3.0 采购单（PO）生成。

契约：
  - PO 文本不含客户 PII；以 customer_fingerprint 关联内部单据。
  - 外协单价 = supplier_quote.unit_price_cny × (1 + markup_pct/100)
    与自产报价（final_price 已含引擎利润）分轨，**不双算**。
  - 输出 dataclass PO（含 text + 元数据），由 orchestrator 进一步 zip + send。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, Optional

from supplier_module.desensitize import fingerprint_customer


@dataclass
class PO:
    context_id: str
    supplier_id: int
    customer_fingerprint: str
    unit_price_cny: float           # supplier 给的 base
    total_cny: float                # unit × qty
    lead_time_days: int
    text: str
    markup_pct: float = 0.0
    sell_price_cny: float = 0.0
    created_at: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def generate_po(
    context_id: str,
    customer: Dict[str, Any],
    rfq: Dict[str, Any],
    supplier: Dict[str, Any],
    quote: Dict[str, Any],
    markup_pct: float = 0.0,
) -> PO:
    """生成一份 PO 文本。

    入参 quote 期望字段：{unit_price_cny, lead_time_days}。
    """
    fp = fingerprint_customer(customer)
    unit = float(quote.get("unit_price_cny", 0.0))
    qty = int(rfq.get("quantity", 1))
    lead = int(quote.get("lead_time_days", supplier.get("lead_time_days", 14)))
    total = round(unit * qty, 2)
    sell = round(unit * (1 + markup_pct / 100.0), 2) if markup_pct else unit

    mat = rfq.get("material", "n/a")
    tol = rfq.get("tolerance_grade", "n/a")
    dims = rfq.get("dimensions_mm") or []
    dims_str = "x".join(str(d) for d in dims) if dims else "n/a"
    procs = ",".join(rfq.get("processes") or []) or "n/a"

    lines = [
        "PURCHASE ORDER (PO)",
        "=" * 50,
        f"Context ID         : {context_id}",
        f"Customer Fingerprint : {fp}",
        f"Supplier ID        : {supplier.get('id')}",
        f"Supplier Name      : {supplier.get('name')}",
        f"Supplier Region    : {supplier.get('region')}",
        "",
        "[SPEC]",
        f"Material           : {mat}",
        f"Processes          : {procs}",
        f"Dimensions (mm)    : {dims_str}",
        f"Tolerance          : {tol}",
        f"Quantity           : {qty}",
        "",
        "[COMMERCIAL]",
        f"Supplier Unit (CNY): {unit:.2f}",
        f"Markup (%)         : {markup_pct:.2f}",
        f"Sell to Customer   : {sell:.2f} CNY/unit",
        f"Total (base)       : {total:.2f} CNY",
        f"Lead Time (days)   : {lead}",
        "",
        "[NOTE]",
        "Customer-identifying fields are anonymized; refer to internal order via fingerprint.",
        "DO NOT include this PO in any external publication without desensitize.py.",
        "=" * 50,
    ]
    return PO(
        context_id=context_id,
        supplier_id=int(supplier.get("id", 0)),
        customer_fingerprint=fp,
        unit_price_cny=unit,
        total_cny=total,
        lead_time_days=lead,
        markup_pct=markup_pct,
        sell_price_cny=sell,
        text="\n".join(lines),
    )