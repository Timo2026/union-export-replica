"""verification.py — "辟·牟·援·推·止" 业务验收循环 + HITL 门禁 (Verification Agent).

对齐冻结 PRD 第 10/11 节。这是业务验收循环, 不让模型自由发挥:
  辟 (DFM 冲突)  : 材料/表面/公差/工艺硬冲突 → BLOCKED
  牟 (商业风险)  : 毛利红线 / 金额门禁 / 历史风险 → HITL/BLOCKED
  援 (证据支撑)  : RAG/图纸/沟通是否支持结论 → 证据不足 HITL
  推 (承诺一致性): 产能/交期/物流是否支持承诺 → 不一致 HITL
  止 (红线熔断)  : 毛利低于门槛 / 无法可靠报价 → BLOCKED

输出: {status: PASS|HITL|BLOCKED, checks[], reasons[], evidence[], next_action}
"""
from __future__ import annotations

from typing import Any, Dict, List


class Verification:
    def __init__(self, policy: Dict[str, Any]):
        self.p = policy

    def run(self, ctx_dict: Dict[str, Any]) -> Dict[str, Any]:
        rfq = ctx_dict.get("rfq", {})
        mfg = ctx_dict.get("manufacturing", {})
        com = ctx_dict.get("commercial", {})
        risk = ctx_dict.get("risk", {})
        evidence = ctx_dict.get("evidence", [])

        checks: List[Dict[str, Any]] = []
        reasons: List[str] = []
        status = "PASS"

        def escalate(level: str):
            nonlocal status
            order = {"PASS": 0, "HITL": 1, "BLOCKED": 2}
            if order[level] > order[status]:
                status = level

        # ---- 辟: DFM 硬冲突 ----
        dfm = mfg.get("dfm", {})
        hard = (dfm.get("valid") is False) or bool(dfm.get("conflicts"))
        checks.append({"step": "辟", "name": "dfm_conflict",
                       "pass": not hard,
                       "detail": [c.get("message", str(c)) for c in dfm.get("conflicts", [])]})
        if hard:
            escalate(self.p.get("dfm", {}).get("hard_conflict_action", "BLOCKED"))
            reasons.append("DFM 硬冲突: " + "; ".join(c.get("message", str(c)) for c in dfm.get("conflicts", [])))
        elif dfm.get("warnings"):
            escalate(self.p.get("dfm", {}).get("warning_action", "HITL"))
            reasons.append("DFM 警告需人工确认")

        # ---- 精度等级 (S5: TC4+IT5 → HITL) ----
        tol = rfq.get("tolerance_grade") or ""
        hitl_grades = self.p.get("tolerance", {}).get("hitl_grades", ["IT4", "IT5"])
        tol_hitl = tol.upper() in [g.upper() for g in hitl_grades]
        checks.append({"step": "辟", "name": "precision_tolerance",
                       "pass": not tol_hitl, "detail": tol or "n/a"})
        if tol_hitl:
            escalate("HITL")
            reasons.append(f"{tol} 属精密公差(超常规CNC经济公差), 强制人工复核")

        # ---- 牟 + 止: 毛利红线 / 金额门禁 ----
        margin = com.get("margin_pct")
        floor = self.p.get("margin", {}).get("floor_pct", 15.0)
        review_below = self.p.get("margin", {}).get("review_below_pct", 20.0)
        if margin is not None:
            ok = margin >= floor
            checks.append({"step": "止", "name": "margin_floor", "pass": ok,
                           "detail": f"{margin:.1f}% vs floor {floor}%"})
            if not ok:
                escalate("BLOCKED")
                reasons.append(f"毛利率 {margin:.1f}% 低于红线 {floor}% → 熔断")
            elif margin < review_below:
                escalate("HITL")
                reasons.append(f"毛利率 {margin:.1f}% 低于复核线 {review_below}%")

        unit_price = com.get("unit_price") or (com.get("quote", {}) or {}).get("unit_price")
        gate = self.p.get("amount_gate", {}).get("unit_price_review_cny", 12000.0)
        if unit_price is not None and float(unit_price) > gate:
            escalate("HITL")
            checks.append({"step": "牟", "name": "amount_gate", "pass": False,
                           "detail": f"unit_price {unit_price} > {gate}"})
            reasons.append(f"单件报价 {unit_price} 超门禁 {gate}, 需商务确认")
        else:
            checks.append({"step": "牟", "name": "amount_gate", "pass": True,
                           "detail": f"unit_price {unit_price} <= {gate}"})

        # ---- 援: 证据支撑 ----
        has_core_ev = any(e.get("source_type") in ("email", "step", "pdf") for e in evidence)
        mock_only = bool(evidence) and all(e.get("mock") for e in evidence)
        checks.append({"step": "援", "name": "evidence_support",
                       "pass": has_core_ev and not mock_only,
                       "detail": f"{len(evidence)} evidence, mock_only={mock_only}"})
        if not has_core_ev:
            escalate("HITL")
            reasons.append("缺乏邮件/图纸/STEP 等核心证据支撑")
        # 缺关键 RFQ 字段 → 证据不足
        if rfq.get("missing_information"):
            escalate("HITL")
            reasons.append("RFQ 关键信息缺失: " + ", ".join(rfq["missing_information"]))

        # ---- 推: 承诺一致性 (交期/产能) + 多模态冲突 ----
        mm_conflicts = ctx_dict.get("risk", {}).get("multimodal_conflicts") or risk.get("multimodal_conflicts") or []
        checks.append({"step": "推", "name": "multimodal_consistency",
                       "pass": len(mm_conflicts) == 0,
                       "detail": [c.get("type") for c in mm_conflicts]})
        if mm_conflicts:
            escalate(self.p.get("multimodal", {}).get("conflict_action", "HITL"))
            reasons.append("多模态冲突(语音↔邮件): " + "; ".join(c.get("type", "") for c in mm_conflicts))

        lead = com.get("lead_time_days") or (com.get("quote", {}) or {}).get("lead_time_days")
        promised = rfq.get("promised_lead_time_days")
        if promised and lead and int(lead) > int(promised):
            escalate("HITL")
            reasons.append(f"承诺交期 {promised}d 与产能估算 {lead}d 不一致")

        next_action = {
            "PASS": "AUTO_REPLY_DRAFT",
            "HITL": "HUMAN_REVIEW",
            "BLOCKED": "BLOCK_AND_SUGGEST_ALTERNATIVE",
        }[status]

        return {
            "status": status,
            "checks": checks,
            "reasons": reasons,
            "evidence": [{"evidence_id": e.get("evidence_id"), "source_type": e.get("source_type"),
                          "mock": e.get("mock", False)} for e in evidence],
            "next_action": next_action,
        }
