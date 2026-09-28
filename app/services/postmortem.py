"""postmortem.py — P3 闭环: 成交/丢单复盘 + 知识回流 + 客户记忆召回 (援).

对齐冻结 PRD P3 Closed loop:
  Quote → Won/Lost → Actual cost → deviation → Postmortem → knowledge_update → 下次报价。
  以及 Memory Fabric 的 Fact 召回: 客户历史 RFQ/报价/复盘注入 Context 作证据与风险信号。

原则: 复盘产出的是"证据/建议", 不自动改写已发报价; 回流以 knowledge_update 记录, 供人/检索采纳。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def record_outcome(crm, context_id: str, outcome: str,
                   actual_cost: Optional[float] = None,
                   actual_leadtime_days: Optional[int] = None,
                   note: str = "") -> Dict[str, Any]:
    """记录成交/丢单结果, 计算与报价的偏差, 落库并产出知识回流建议。"""
    outcome = (outcome or "").lower()
    if outcome not in ("won", "lost"):
        raise ValueError("outcome must be 'won' or 'lost'")

    quoted = crm.get_quote(context_id) if crm is not None else None
    analysis: Dict[str, Any] = {"context_id": context_id, "outcome": outcome,
                                "quoted": quoted, "deviation": {}, "knowledge_updates": []}

    if quoted:
        quoted_final = quoted.get("final_price")
        if actual_cost is not None and quoted_final:
            cost_dev_pct = round((float(actual_cost) - float(quoted_final)) / float(quoted_final) * 100, 2)
            analysis["deviation"]["cost_pct"] = cost_dev_pct
            # 成本高于报价 → 毛利被侵蚀, 回流"该材料/工艺报价偏低"信号
            if cost_dev_pct > 5:
                analysis["knowledge_updates"].append({
                    "type": "price_underestimate", "severity": "high",
                    "signal": f"实际成本高于报价 {cost_dev_pct}%",
                    "action": "上调该材料/工艺系数或增加风险余量"})
            elif cost_dev_pct < -5:
                analysis["knowledge_updates"].append({
                    "type": "price_overestimate", "severity": "medium",
                    "signal": f"实际成本低于报价 {abs(cost_dev_pct)}%",
                    "action": "该区间报价偏保守, 可提升竞争力"})
        quoted_lead = quoted.get("lead_time_days")
        if actual_leadtime_days is not None and quoted_lead:
            lead_dev = int(actual_leadtime_days) - int(quoted_lead)
            analysis["deviation"]["leadtime_days"] = lead_dev
            if lead_dev > 0:
                analysis["knowledge_updates"].append({
                    "type": "leadtime_overrun", "severity": "medium",
                    "signal": f"实际交期超承诺 {lead_dev} 天",
                    "action": "复核产能/运输时效假设"})

    if outcome == "lost":
        analysis["knowledge_updates"].append({
            "type": "loss_review", "severity": "info",
            "signal": "丢单", "action": "复盘价格/交期/竞品, 更新客户偏好记忆"})

    if crm is not None:
        crm.postmortem(context_id, outcome, actual_cost, note)

    return analysis


def recall_customer_memory(crm, customer: Dict[str, Any], limit: int = 10) -> Dict[str, Any]:
    """客户记忆召回: 过往报价/复盘 → 证据 + 风险信号 (注入 Context 作 '援')。"""
    if crm is None:
        return {"recall": False, "reason": "crm disabled", "signals": [], "history": {}}
    name = (customer or {}).get("name") or ""
    cid = (customer or {}).get("customer_id") or crm.customer_id_by_name(name)
    hist = crm.list_customer_history(cid, limit=limit) if cid else {"quotes": [], "postmortems": [], "n": 0}

    signals: List[Dict[str, Any]] = []
    quotes = hist.get("quotes", [])
    if quotes:
        signals.append({"type": "repeat_customer", "severity": "info",
                        "detail": f"历史 {len(quotes)} 条报价记录"})
        margins = [q.get("margin_pct") for q in quotes if q.get("margin_pct") is not None]
        if margins:
            avg_m = round(sum(margins) / len(margins), 1)
            signals.append({"type": "historical_margin", "severity": "info",
                            "detail": f"历史平均毛利 {avg_m}%"})
    lost = [p for p in hist.get("postmortems", []) if p.get("outcome") == "lost"]
    if lost:
        signals.append({"type": "past_loss", "severity": "warning",
                        "detail": f"有 {len(lost)} 次丢单记录, 关注价格竞争力"})
    over = [p for p in hist.get("postmortems", []) if (p.get("note") or "").find("超") >= 0]
    if over:
        signals.append({"type": "past_overrun", "severity": "warning",
                        "detail": f"{len(over)} 次成本/交期偏差记录"})

    return {"recall": True, "customer_id": cid, "is_new": len(quotes) == 0,
            "signals": signals, "history": hist}
