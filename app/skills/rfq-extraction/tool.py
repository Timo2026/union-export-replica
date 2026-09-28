"""rfq-extraction skill — 委托 services/intake.extract_rfq (v6.0.0 最小补全)."""
from __future__ import annotations
from typing import Any, Dict


def run(ctx, email_text: str = "", **kwargs) -> Dict[str, Any]:
    """委托 services/intake.extract_rfq. LLM 不可用时 mock fallback."""
    if not email_text:
        return {"ok": False, "skill": "rfq-extraction", "iron_rule": "deterministic",
                "error": "email_text required"}
    try:
        from services.intake import extract_rfq
        from services.llm_planner import _try_llm_extract
        customer = kwargs.get("customer") or {}
        # 先 LLM 提议 (opt-in), 失败回退到正则
        llm_result = _try_llm_extract(email_text)
        rfq = extract_rfq(email_text, customer)
        if llm_result and isinstance(llm_result, dict):
            for k, v in llm_result.items():
                if v and not rfq.get(k):
                    rfq[k] = v
        ctx.scratch["rfq"] = rfq
        ctx.scratch["email_text"] = email_text
        return {"ok": True, "skill": "rfq-extraction", "iron_rule": "deterministic",
                "rfq": rfq, "missing_information": rfq.get("missing_information", []),
                "_source": "services.intake.extract_rfq"}
    except Exception as e:
        return {"ok": False, "skill": "rfq-extraction", "iron_rule": "deterministic",
                "error": repr(e)}
