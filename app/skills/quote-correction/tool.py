"""quote_correction — L2 锚点矫正提案 Skill (复用 scripts.quote_correction + v6.2 PriceCorrector)."""
from __future__ import annotations

from typing import Any, Dict

SKILL_META = {"skill": "quote_correction", "iron_rule": "deterministic",
              "proposal_only": True}


def run(ctx, action: str = "correct",
        engine_quote: Dict[str, Any] = None,
        query: str = "",
        customer_id: str = "",
        **kwargs) -> Dict[str, Any]:
    if action != "correct":
        return {**SKILL_META, "ok": False, "error": f"未知 action: {action}"}
    if not engine_quote or not query or not customer_id:
        return {**SKILL_META, "ok": False,
                "error": "engine_quote/query/customer_id 必填"}

    import scripts.quote_correction as qc
    from services.flywheel.price_corrector import PriceCorrector
    from services.rag_layers import get_gateway

    gw = get_gateway()
    out = qc.correct_quote_with_l2(gw, PriceCorrector(), dict(engine_quote),
                                   query, customer_id)
    if out is None:                                  # 脚本契约: 无召回锚点
        return {**SKILL_META, "ok": False, "reason": "no_anchor",
                "note": "L2 无该客户历史锚点, 不假造矫正 (诚实空转)"}
    return {**SKILL_META, "ok": True, "correction": out}
