"""extract_specs — LLM 提议补全 RFQ 缺字段 (不覆盖确定性值)."""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, email_text: str = "", rfq: Dict[str, Any] | None = None, **kwargs) -> Dict[str, Any]:
    planner = ctx.planner
    if planner is None:
        try:
            planner = ctx.get_ctrl().planner
        except Exception:
            planner = None
    body = email_text or ctx.scratch.get("email_text") or ""
    base = dict(rfq or ctx.scratch.get("rfq") or {})
    if planner is None or not getattr(planner, "online", lambda: False)():
        return {
            "ok": True, "skill": "extract_specs", "iron_rule": "llm_proposal",
            "used_llm": False, "rfq": base, "filled": [],
            "_source": "MOCK:llm-offline", "note": "LLM 离线, 保留确定性抽取结果",
        }
    lr = planner.extract_rfq(body) if body else {"ok": False, "data": None}
    data = lr.get("data") if isinstance(lr, dict) else None
    filled = []
    if isinstance(data, dict):
        for k in ("material", "surface", "quantity", "tolerance_grade", "tolerance_mm", "dimensions_mm"):
            if base.get(k) in (None, "", []) and data.get(k) not in (None, "", []):
                base[k] = data[k]
                filled.append(k)
        miss = [m for m in (base.get("missing_information") or []) if m not in filled]
        for k in filled:
            if k in miss:
                miss.remove(k)
        base["missing_information"] = miss
    ctx.scratch["rfq"] = base
    return {
        "ok": True, "skill": "extract_specs", "iron_rule": "llm_proposal",
        "used_llm": True, "rfq": base, "filled": filled,
        "_source": lr.get("_source") if isinstance(lr, dict) else "live:llm",
    }
