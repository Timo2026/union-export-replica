"""freight_customs — P1 商业落地成本 (运费/关税/Incoterms), 确定性费率表.

铁律①: landed_cost 数字由 services.commercial.compute_commercial 权威产出,
LLM/Dispatcher 不得改写。
"""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, quote: Dict[str, Any] | None = None, rfq: Dict[str, Any] | None = None,
        cfg: Dict[str, Any] | None = None,
        destination_country: str | None = None,
        shipping_mode: str | None = None,
        incoterm: str | None = None,
        hs_code: str | None = None, **kwargs) -> Dict[str, Any]:
    # 从 dispatch scratch 补缺 (黄金链上一步产物)
    quote = dict(quote or ctx.scratch.get("quote") or {})
    rfq = dict(rfq or ctx.scratch.get("rfq") or {})
    # 商业费率表: 优先显式 cfg, 否则从 ctx.settings 加载 config/commercial.yaml
    if cfg is None:
        commercial_cfg = (ctx.settings or {}).get("commercial")
        if commercial_cfg:
            cfg = commercial_cfg
        else:
            ctrl = ctx.get_ctrl()
            cfg = getattr(ctrl, "commercial_cfg", None) or {}
    if not cfg:
        return {"ok": False, "skill": "freight_customs",
                "error": "商业费率表缺失 (config/commercial.yaml 未加载)",
                "iron_rule": "deterministic"}
    if not quote or not rfq:
        return {"ok": False, "skill": "freight_customs",
                "error": "quote 与 rfq 均为空 (黄金链未产出或参数缺失)",
                "iron_rule": "deterministic"}
    try:
        from services.commercial import compute_commercial
        out = compute_commercial(
            quote=quote, rfq=rfq, cfg=cfg,
            destination_country=destination_country,
            shipping_mode=shipping_mode, incoterm=incoterm, hs_code=hs_code,
        )
    except Exception as e:  # noqa
        return {"ok": False, "skill": "freight_customs", "error": repr(e),
                "iron_rule": "deterministic"}
    result = {
        "ok": True,
        "skill": "freight_customs",
        "iron_rule": "deterministic",
        "landed_cost": out.get("landed_cost"),
        "seller_quote_price": out.get("seller_quote_price"),
        "incoterm": out.get("incoterm"),
        "total_lead_time_days": out.get("total_lead_time_days"),
        "breakdown": out.get("breakdown") or {},
        "region": out.get("region"),
        "_source": "services.commercial.compute_commercial",
        "raw": out,
    }
    ctx.scratch["commercial"] = result
    return result
