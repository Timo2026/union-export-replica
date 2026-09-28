"""flywheel_retention.py — 留存飞轮核心模块.

实现: 丢单 → 复盘原因 → 知识回流 → 下次避免同类问题 → 赢单率提升。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class FlywheelRetention:
    """留存飞轮 — 丢单知识回流, 提升赢单率。

    丢单原因分类 → 对应策略 → 知识更新 → 下次自动调整。
    """

    LOSS_PATTERNS = {
        "price_too_high": {
            "action": "降低风险余量2-3%",
            "knowledge_update": "该客户价格敏感, 下次报价target_margin下调至18-20%",
            "severity": "warning",
        },
        "margin_rejected": {
            "action": "降低目标毛利, 增加报价竞争力",
            "knowledge_update": "客户拒绝毛利, 下次报价主动降低3-5%",
            "severity": "warning",
        },
        "lead_time_too_long": {
            "action": "优先排产, 缩短交期",
            "knowledge_update": "该客户交期敏感, 下次自动排快速通道",
            "severity": "info",
        },
        "competitor_better": {
            "action": "提升附加值(免费样件/加速响应)",
            "knowledge_update": "竞品优势, 下次增加增值服务提案",
            "severity": "info",
        },
        "quality_concern": {
            "action": "提供质检报告+样品",
            "knowledge_update": "质量疑虑, 下次自动附带质检文档",
            "severity": "info",
        },
    }

    def __init__(self, sandbox):
        self.sandbox = sandbox

    def on_lost(self, context_id: str, verification: Dict[str, Any],
                   quote: Dict[str, Any], rfq: Dict[str, Any]) -> Dict[str, Any]:
        """丢单后自动触发知识回流。"""
        result: Dict[str, Any] = {"outcome": "lost", "knowledge_updates": []}

        # 1. 推断丢单原因
        reason = self._infer_loss_reason(quote, verification, rfq)
        pattern = self.LOSS_PATTERNS.get(reason, self.LOSS_PATTERNS["competitor_better"])

        result["loss_reason"] = reason
        result["strategy"] = pattern["action"]

        # 2. 记录复盘
        note = f"丢单原因: {reason} | 策略: {pattern['action']}"
        self.sandbox.record_postmortem(context_id, "lost",
                                        verification.get("actual_cost"), note)

        # 3. 知识回流到沙箱
        self.sandbox.add_knowledge(
            category="retention",
            keyword=reason,
            insight=f"LOST: {reason} → {pattern['knowledge_update']}",
            severity=pattern["severity"]
        )
        result["knowledge_updates"].append({
            "type": "loss_review",
            "severity": pattern["severity"],
            "signal": f"丢单: {reason}",
            "action": pattern["knowledge_update"],
        })

        # 4. 调整定价模型 (降低毛利争取下次赢单)
        if reason in ("price_too_high", "margin_rejected"):
            model = self.sandbox.get_pricing_model()
            self.sandbox.update_pricing_model(
                material_coeff=model.get("material_coeff", 0),
                surface_coeff=model.get("surface_coeff", 0),
                tolerance_coeff=model.get("tolerance_coeff", 0),
                deviation=-3,  # 下次报价降低3%
                won=False
            )
            result["pricing_adjusted"] = "margin_lowered_3pct"
            result["knowledge_updates"].append({
                "type": "margin_adjusted",
                "severity": "info",
                "signal": "因丢单降低毛利3%",
                "action": "下次报价目标毛利自动下调"
            })

        # 5. 设置下次RFQ提醒
        self.sandbox.add_followup(
            action="retention_alert",
            trigger=f"lost_{reason}",
            result=pattern["knowledge_update"]
        )

        return result

    def on_won(self, context_id: str, verification: Dict[str, Any],
                  quote: Dict[str, Any], rfq: Dict[str, Any]) -> Dict[str, Any]:
        """赢单后巩固策略。"""
        result: Dict[str, Any] = {"outcome": "won", "knowledge_updates": []}

        # 1. 记录赢单复盘
        winning_factors = self._identify_winning_factors(quote, rfq)
        self.sandbox.record_postmortem(context_id, "won",
                                        verification.get("actual_cost"), "")

        # 2. 强化成功策略
        self.sandbox.add_knowledge(
            category="win_confirm",
            keyword="winning_strategy",
            insight=f"WON with factors: {winning_factors}",
            severity="info"
        )
        result["winning_factors"] = winning_factors
        result["knowledge_updates"].append({
            "type": "win_confirm",
            "severity": "info",
            "signal": "成交, 巩固当前策略",
            "action": "保持当前定价和策略"
        })

        return result

    def _infer_loss_reason(self, quote: Dict[str, Any],
                              verification: Dict[str, Any],
                              rfq: Dict[str, Any]) -> str:
        """推断丢单原因。"""
        reasons = []
        margin = quote.get("margin_pct", 25)
        if margin > 25:
            reasons.append("price_too_high")
        if verification.get("reasons"):
            for r in verification["reasons"]:
                if "margin" in r.lower() or "毛利" in r:
                    if "price_too_high" not in reasons:
                        reasons.append("margin_rejected")
                if "lead" in r.lower() or "交期" in r:
                    reasons.append("lead_time_too_long")
        if not reasons:
            reasons.append("competitor_better")
        return reasons[0]  # 返回主要原因

    def _identify_winning_factors(self, quote: Dict[str, Any],
                                     rfq: Dict[str, Any]) -> List[str]:
        """识别赢单因素。"""
        factors = []
        margin = quote.get("margin_pct", 25)
        if margin <= 20:
            factors.append("competitive_price")
        if margin > 20 and margin <= 25:
            factors.append("balanced_offer")
        lead = quote.get("lead_time_days", 0)
        if lead <= 14:
            factors.append("fast_delivery")
        if rfq.get("material"):
            factors.append(f"material_{rfq['material']}")
        if not factors:
            factors.append("standard_offer")
        return factors

    def get_retention_score(self, customer_id: str) -> Dict[str, Any]:
        """计算客户留存分。"""
        history = self.sandbox.get_history()
        postmortems = history.get("postmortems", [])
        quotes = history.get("quotes", [])

        if not postmortems:
            return {"customer_id": customer_id, "retention_score": 50,
                    "status": "no_data"}

        won = sum(1 for p in postmortems if p.get("outcome") == "won")
        lost = sum(1 for p in postmortems if p.get("outcome") == "lost")
        total = won + lost
        win_rate = won / total if total > 0 else 0

        # 留存分 = 赢单率 × 80 + 平均毛利/50 × 20
        avg_margin = sum(q.get("margin_pct", 0) for q in quotes) / max(len(quotes), 1)
        retention_score = win_rate * 80 + min(avg_margin / 50 * 20, 20)

        return {
            "customer_id": customer_id,
            "retention_score": round(retention_score, 1),
            "win_rate": round(win_rate * 100, 1),
            "total_deals": total,
            "status": "healthy" if retention_score >= 60 else "at_risk",
        }
