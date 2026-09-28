"""customer_flywheel.py — 客户飞轮总引擎.

整合定价飞轮 + 跟进飞轮 + 留存飞轮, 形成完整的客户跟进闭环。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class CustomerFlywheel:
    """客户飞轮总引擎 — 整合三重飞轮, 驱动越报越准。"""

    def __init__(self, crm, health_engine, calibration, funasr_adapter=None):
        self.crm = crm
        self.health = health_engine
        self.calibration = calibration
        self.funasr = funasr_adapter
        self._sandboxes: Dict[str, Any] = {}

    def before_run(self, customer: Dict[str, Any]) -> Dict[str, Any]:
        """CAT run 前钩子 — 加载客户飞轮状态注入 Context。

        返回: 包含客户健康分、定价修正、跟进建议的上下文。
        """
        cid = customer.get("customer_id", "")
        result: Dict[str, Any] = {"customer_id": cid}

        # 1. 健康分
        try:
            health = self.health.calculate_health(customer)
            result["health_score"] = health.get("health_score", 50)
            result["risk_level"] = health.get("risk_level", "medium")
            result["risk_signals"] = health.get("signals", [])
            if self.health.should_escalate(health):
                result["_escalate_to_HITL"] = True
                result["_escalate_reason"] = self.health.escalate_reason(health)
        except Exception:
            health = {"health_score": 50, "risk_level": "medium"}

        # 2. 定价修正建议
        try:
            model = self._get_pricing_model(cid)
            result["pricing_model"] = model
            result["price_adjustment_suggestion"] = self._price_advice(model)
        except Exception:
            result["pricing_model"] = {}
            result["price_adjustment_suggestion"] = []

        # 3. 跟进建议
        try:
            followups = self._get_recent_followups(cid)
            result["followup_suggestions"] = self._followup_advice(followups)
        except Exception:
            result["followup_suggestions"] = []

        # 4. 新客户标记
        result["is_new"] = health.get("is_new", True)
        result["quote_count"] = health.get("quote_count", 0)

        return result

    def after_run(self, context: Dict[str, Any], verification: Dict[str, Any],
                  reply: Dict[str, Any]) -> Dict[str, Any]:
        """CAT run 后钩子 — 落沙箱 + 更新飞轮。

        1. 记录报价到沙箱
        2. 如果有 outcome → 更新定价模型
        3. 更新客户知识库
        """
        result: Dict[str, Any] = {"_skipped": "no outcome"}
        customer = context.get("customer", {})
        cid = customer.get("customer_id", "")
        rfq = context.get("rfq", {})
        quote = context.get("commercial", {}).get("quote", {})

        if not cid:
            return {"_skipped": "no customer_id"}

        # 1. 记录 RFQ 到沙箱
        try:
            from services.sandbox import get_sandbox
            sandbox = get_sandbox(cid)
            sandbox.write_rfq(context.get("context_id", ""), rfq)
            sandbox.write_quote(context.get("context_id", ""), quote)
            sandbox.close()
            result["sandbox_recorded"] = True
        except Exception as e:
            result["sandbox_recorded"] = False
            result["sandbox_error"] = repr(e)

        # 2. 记录客户交互
        try:
            from services.sandbox import get_sandbox
            sandbox = get_sandbox(cid)
            sandbox.add_followup(
                action="quote_sent",
                trigger=f"context_{context.get('context_id', '')}",
                result=f"margin_{quote.get('margin_pct', 'N/A')}%"
            )
            sandbox.close()
        except Exception:
            pass

        # 3. 如果有成交/丢单结果 → 更新飞轮
        outcome = verification.get("outcome")  # won/lost
        if outcome in ("won", "lost"):
            result.update(self._on_outcome(cid, context, verification, quote, outcome))

        return result

    def _on_outcome(self, cid: str, context: Dict[str, Any],
                       verification: Dict[str, Any], quote: Dict[str, Any],
                       outcome: str) -> Dict[str, Any]:
        """处理成交/丢单结果 → 更新定价模型 + 知识回流。"""
        result: Dict[str, Any] = {"outcome": outcome, "knowledge_updates": []}
        actual_cost = verification.get("actual_cost")
        quoted_price = quote.get("final_price") or quote.get("unit_price")

        try:
            from services.sandbox import get_sandbox
            sandbox = get_sandbox(cid)

            # 记录复盘
            if outcome == "lost":
                reason = self._infer_loss_reason(quote, verification, context)
                note = f"丢单原因: {reason}"
                sandbox.record_postmortem(context.get("context_id", ""), "lost",
                                             actual_cost, note)
                sandbox.add_knowledge("loss", reason,
                                     f"{outcome} - {reason} - 下次调整报价策略")
                result["loss_reason"] = reason
                result["knowledge_updates"].append({
                    "type": "loss_review", "severity": "warning",
                    "signal": f"丢单: {reason}",
                    "action": "下次报价调整风险余量"})
            else:
                sandbox.record_postmortem(context.get("context_id", ""), "won",
                                             actual_cost, "")
                result["knowledge_updates"].append({
                    "type": "win_confirm", "severity": "info",
                    "signal": "成交", "action": "巩固当前策略"})

            # 2. 计算偏差并更新定价模型
            if actual_cost and quoted_price:
                deviation = (float(actual_cost) - float(quoted_price)) / float(quoted_price) * 100
                won = (outcome == "won")
                model = sandbox.update_pricing_model(
                    material_coeff=deviation * 0.3,
                    surface_coeff=deviation * 0.2,
                    tolerance_coeff=deviation * 0.2,
                    deviation=deviation,
                    won=won
                )
                result["pricing_model_updated"] = model
                result["deviation_pct"] = round(deviation, 2)
                result["knowledge_updates"].append({
                    "type": "pricing_calibrated", "severity": "info",
                    "signal": f"偏差 {deviation:.2f}% → 模型已更新",
                    "action": f"下次报价自动修正"})
            else:
                result["pricing_model_updated"] = None

            # 3. 重新加载定价模型
            result["new_pricing_model"] = sandbox.get_pricing_model()
            sandbox.close()

        except Exception as e:
            result["error"] = repr(e)

        return result

    def _get_pricing_model(self, cid: str) -> Dict[str, Any]:
        """获取客户定价模型。"""
        try:
            from services.sandbox import get_sandbox
            sandbox = get_sandbox(cid)
            model = sandbox.get_pricing_model()
            sandbox.close()
            return model
        except Exception:
            return {"material_coeff": 0, "surface_coeff": 0, "tolerance_coeff": 0}

    def _price_advice(self, model: Dict[str, Any]) -> List[str]:
        """基于定价模型给出报价建议。"""
        advice = []
        if model.get("avg_deviation", 0) > 3:
            advice.append(f"历史偏差 +{model['avg_deviation']}%, 建议上调风险余量")
        elif model.get("avg_deviation", 0) < -3:
            advice.append(f"历史偏差 {model['avg_deviation']}%, 可降低报价提升竞争力")
        if model.get("win_rate", 0.5) < 0.3:
            advice.append("赢单率偏低, 建议降低目标毛利至20%以下")
        if model.get("total_quotes", 0) < 3:
            advice.append("样本不足, 使用全局默认系数")
        return advice

    def _followup_advice(self, followups: List[Dict[str, Any]]) -> List[str]:
        """基于跟进记录给出建议。"""
        advice = []
        recent = [f for f in followups if f.get("action") == "quote_sent"][-3:]
        if not recent:
            advice.append("该客户尚未有报价记录, 使用默认策略")
        for f in recent:
            if f.get("result", "").startswith("margin_") and "low" in f.get("result", ""):
                advice.append("上次报价毛利偏低, 下次注意风险余量")
        return advice

    def _get_recent_followups(self, cid: str) -> List[Dict[str, Any]]:
        """获取近期跟进记录。"""
        try:
            from services.sandbox import get_sandbox
            sandbox = get_sandbox(cid)
            # 从 knowledge_base 获取
            kb = sandbox.get_knowledge_base(limit=10)
            sandbox.close()
            return [{"action": "knowledge_update", "result": k.get("insight", "")} for k in kb]
        except Exception:
            return []

    def _infer_loss_reason(self, quote: Dict[str, Any], verification: Dict[str, Any],
                              context: Dict[str, Any]) -> str:
        """推断丢单原因。"""
        reasons = []
        margin = quote.get("margin_pct", 25)
        if margin > 25:
            reasons.append("price_too_high")
        if verification.get("reasons"):
            for r in verification["reasons"]:
                if "margin" in r.lower():
                    reasons.append("margin_rejected")
                if "lead" in r.lower() or "交期" in r:
                    reasons.append("lead_time_too_long")
        if not reasons:
            reasons.append("competitor_better")
        return "; ".join(reasons)
