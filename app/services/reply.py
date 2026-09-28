"""reply.py — 英文回复草稿生成 (Sales Agent).

原则: 草稿只反映确定性引擎产出的事实 (报价/交期/冲突/替代方案);
LLM 不生成最终数字。默认 draft_only, 高风险不自动发送 (external_send policy)。
"""
from __future__ import annotations

from typing import Any, Dict


def build_reply(ctx_dict: Dict[str, Any], verification: Dict[str, Any]) -> Dict[str, Any]:
    rfq = ctx_dict.get("rfq", {})
    com = ctx_dict.get("commercial", {})
    quote = com.get("quote", com)
    cust = ctx_dict.get("customer", {})
    status = verification.get("status", "PASS")
    mat = rfq.get("material", "the requested material")
    qty = rfq.get("quantity", "the requested quantity")
    surf = rfq.get("surface") or "as-machined"
    tol = rfq.get("tolerance_grade") or "standard tolerance"
    name = cust.get("contact_name") or cust.get("name") or "there"

    unit = quote.get("unit_price")
    total = quote.get("final_price") or quote.get("total_price")
    lead = quote.get("lead_time_days")
    src = quote.get("_source", com.get("source", "deterministic engine"))

    if status == "BLOCKED":
        conflicts = ctx_dict.get("manufacturing", {}).get("dfm", {}).get("conflicts", [])
        ctext = "; ".join(c.get("message", str(c)) for c in conflicts) or "a manufacturing constraint"
        alt = _alternative(rfq, conflicts)
        subject = f"Re: RFQ {ctx_dict.get('context_id')} — process clarification needed"
        body = (
            f"Dear {name},\n\n"
            f"Thank you for your inquiry for {qty} pcs in {mat} with {surf}.\n\n"
            f"After DFM review we found a hard process conflict: {ctext}. "
            f"We therefore cannot quote this combination as specified.\n\n"
            f"{alt}\n\n"
            f"Could you confirm an alternative so we can proceed with a firm quotation?\n\n"
            f"Best regards,\nUnion Export Sales Engineering"
        )
        auto_send = False
    elif status == "HITL":
        reasons = "; ".join(verification.get("reasons", [])) or "requires internal review"
        subject = f"Re: RFQ {ctx_dict.get('context_id')} — under review"
        body = (
            f"Dear {name},\n\n"
            f"Thank you for your inquiry for {qty} pcs in {mat} ({surf}, {tol}).\n\n"
            f"Your request is currently under engineering/commercial review ({reasons}). "
            f"We will revert with a firm quotation shortly.\n\n"
            f"Best regards,\nUnion Export Sales Engineering"
        )
        auto_send = False
    else:
        subject = f"Quotation {ctx_dict.get('context_id')} — {mat} {qty} pcs"
        price_line = (f"Unit price: USD/CNY {unit} | Total: {total} | Lead time: {lead} days."
                      if unit is not None else "Pricing to follow.")
        body = (
            f"Dear {name},\n\n"
            f"Thank you for your inquiry. We are pleased to quote as follows:\n\n"
            f"- Material: {mat}\n"
            f"- Quantity: {qty} pcs\n"
            f"- Surface finish: {surf}\n"
            f"- Tolerance: {tol}\n"
            f"- {price_line}\n\n"
            f"(Estimate produced by our deterministic manufacturing engine [{src}]; "
            f"valid 14 days, subject to final drawing confirmation.)\n\n"
            f"Best regards,\nUnion Export Sales Engineering"
        )
        auto_send = False  # 默认 draft_only

    return {
        "subject": subject, "body": body, "status": status,
        "auto_send": auto_send, "mode": "draft_only",
        "quote_source": src,
    }


def _alternative(rfq: Dict[str, Any], conflicts) -> str:
    mat = (rfq.get("material") or "").lower()
    surf = rfq.get("surface") or ""
    if mat in ("304", "316l") and "阳极氧化" in surf:
        return ("Suggested alternative: for stainless steel, passivation (钝化) or electropolishing "
                "provides corrosion protection; anodizing is not applicable to 304/316L.")
    if rfq.get("tolerance_grade", "").upper() in ("IT4", "IT5"):
        return ("Suggested alternative: relax tolerance to IT6/IT7 for standard CNC, "
                "or confirm grinding/wire-EDM if IT4/IT5 is critical (added cost & lead time).")
    if mat in ("6061", "7075") and "镀锌" in surf:
        return "Suggested alternative: for aluminum, anodizing or nickel plating is preferred over zinc plating."
    return "Please advise an adjusted specification and we will re-quote."
