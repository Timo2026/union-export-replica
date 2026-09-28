"""customer_health.py — 客户健康度引擎.

计算客户综合健康分, 识别风险信号, 支持飞轮决策。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class CustomerHealthEngine:
    """客户健康度引擎 — 识别风险/机会, 驱动飞轮决策。"""

    def __init__(self, crm):
        self.crm = crm

    def compute_health(self, customer_id: str) -> Dict[str, Any]:
        """flywheel 钩子入口: 按 customer_id 计算健康分."""
        return self.calculate_health({"customer_id": customer_id})

    def should_escalate(self, health: Dict[str, Any]) -> bool:
        score = float(health.get("health_score", 50) or 50)
        risk = str(health.get("risk_level") or health.get("churn_risk") or "")
        return score < 40 or risk in ("high", "critical")

    def escalate_reason(self, health: Dict[str, Any]) -> str:
        score = float(health.get("health_score", 50) or 50)
        risk = str(health.get("risk_level") or health.get("churn_risk") or "")
        return f"health_score={score}, risk={risk or 'unknown'} — 需人工关怀"

    def calculate_health(self, customer: Dict[str, Any]) -> Dict[str, Any]:
        """计算客户健康分 (0-100)。

        权重:
          - 历史赢单率: 30%
          - 平均毛利: 20%
          - 丢单频率: 20%
          - 最近交互活跃度: 15%
          - 风险信号: 15%
        """
        cid = customer.get("customer_id", "")
        history = self.crm.list_customer_history(cid, limit=50) if cid else {"quotes": [], "postmortems": [], "n": 0}
        quotes = history.get("quotes", [])
        postmortems = history.get("postmortems", [])
        n = len(quotes)

        if n == 0:
            return {"customer_id": cid, "health_score": 50.0, "is_new": True,
                    "risk_level": "medium", "signals": ["new_customer"],
                    "breakdown": {"win_rate": 50, "margin": 0, "loss_freq": 0, "activity": 0, "risk": 0}}

        # 1. 赢单率 (30%)
        won = sum(1 for p in postmortems if p.get("outcome") == "won")
        total_outcomes = len(postmortems) if postmortems else n
        win_rate = won / total_outcomes if total_outcomes > 0 else 0.5
        win_score = win_rate * 100

        # 2. 平均毛利 (20%)
        margins = [q.get("margin_pct") for q in quotes if q.get("margin_pct") is not None]
        avg_margin = sum(margins) / len(margins) if margins else 0
        margin_score = max(0, min(100, avg_margin / 50 * 100))  # 归一化到0-100

        # 3. 丢单频率 (20%) — 丢单越多, 分数越低
        lost_count = sum(1 for p in postmortems if p.get("outcome") == "lost")
        loss_freq = lost_count / total_outcomes if total_outcomes > 0 else 0
        loss_score = (1 - loss_freq) * 100

        # 4. 活跃度 (15%) — 最近30天有交互为活跃
        recent = [q for q in quotes if (q.get("created_at", 0) > 0)]
        activity_score = 70 if recent else 30  # 简化: 有历史即活跃

        # 5. 风险信号 (15%)
        risk_signals = self._detect_risk_signals(history)
        risk_score = max(0, 100 - len(risk_signals) * 20)

        # 综合健康分
        health_score = (win_score * 0.3 + margin_score * 0.2 +
                        loss_score * 0.2 + activity_score * 0.15 + risk_score * 0.15)

        # 风险等级
        if health_score >= 75:
            risk_level = "low"
        elif health_score >= 50:
            risk_level = "medium"
        elif health_score >= 25:
            risk_level = "high"
        else:
            risk_level = "critical"

        return {
            "customer_id": cid,
            "health_score": round(health_score, 1),
            "is_new": n == 0,
            "risk_level": risk_level,
            "signals": risk_signals,
            "breakdown": {
                "win_rate": round(win_score, 1),
                "margin": round(margin_score, 1),
                "loss_freq": round(loss_score, 1),
                "activity": round(activity_score, 1),
                "risk": round(risk_score, 1),
            },
            "quote_count": n,
            "total_outcomes": total_outcomes,
        }

    def _detect_risk_signals(self, history: Dict[str, Any]) -> List[str]:
        """检测风险信号。"""
        signals: List[str] = []
        postmortems = history.get("postmortems", [])
        quotes = history.get("quotes", [])

        lost = [p for p in postmortems if p.get("outcome") == "lost"]
        if len(lost) >= 3:
            signals.append("frequent_loss")
        if lost and len(lost) / len(postmortems) > 0.6 if postmortems else False:
            signals.append("high_loss_ratio")
        margins = [q.get("margin_pct") for q in quotes if q.get("margin_pct") is not None]
        if margins and min(margins) < 10:
            signals.append("low_margin_history")
        return signals

    def should_escalate(self, health: Dict[str, Any]) -> bool:
        """健康分过低 → 升级 HITL。"""
        if health.get("risk_level") in ("high", "critical"):
            return True
        if health.get("health_score", 100) < 30:
            return True
        return False

    def escalate_reason(self, health: Dict[str, Any]) -> str:
        """获取升级原因。"""
        reasons = []
        if health.get("risk_level") == "critical":
            reasons.append("customer_health_critical")
        if health.get("risk_level") == "high":
            reasons.append("customer_health_high_risk")
        if health.get("health_score", 100) < 30:
            reasons.append(f"health_score_too_low ({health.get('health_score')})")
        for s in health.get("signals", []):
            reasons.append(f"risk_signal:{s}")
        return "; ".join(reasons) if reasons else "healthy"
