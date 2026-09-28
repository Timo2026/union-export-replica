"""quote_calibration.py — 报价偏差学习 (飞轮层).

对齐铁律:
  - 校准产出 bias_pct (提案/参数), 不改 Timo calc_quote 内部逻辑
  - bias 上限 ±10%, 置信度不足不生效
  - 纯规则, 无 LLM; 禁止作为 final_price 权威来源
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from services.config import target_margin_pct

if TYPE_CHECKING:
    from services.crm_memory import CRMMemory

MAX_BIAS_PCT = 10.0
MIN_SAMPLES = 3
DECISION_THRESHOLD_PCT = 5.0
DOWN_THRESHOLD_PCT = -2.0

ACTION_TO_BIAS_PCT = {
    "price_up_pct_3": 3.0,
    "price_down_pct_2": -2.0,
    "price_down_pct_3": -3.0,
    "price_down_pct_5": -5.0,
    "no_change_check_intent": 0.0,
    "no_change": 0.0,
}


class QuoteCalibration:
    """报价偏差学习器."""

    def __init__(self, crm: "CRMMemory"):
        self.crm = crm

    def record_outcome(self, context_id: str, customer_id: str,
                       material: str, surface: str, quantity: int,
                       quoted_unit_price: float,
                       actual_unit_cost: Optional[float],
                       outcome: str) -> Dict[str, Any]:
        """记录单次报价结果, 产出 calibration 事件 + 落库."""
        deviation = None
        if actual_unit_cost is not None and quoted_unit_price and quoted_unit_price > 0:
            deviation = round(
                (float(actual_unit_cost) - float(quoted_unit_price))
                / float(quoted_unit_price) * 100.0, 2)
        action = self._decide_action(outcome, deviation)
        confidence = self._estimate_confidence(customer_id, material)

        event_id = self.crm.record_calibration(
            context_id=context_id, customer_id=customer_id,
            material=material, surface=surface or "", quantity=int(quantity or 0),
            quoted_unit_price=float(quoted_unit_price or 0),
            actual_unit_cost=actual_unit_cost,
            deviation_pct=deviation, outcome=outcome,
            calibration_action=action, confidence=confidence,
        )
        return {
            "id": event_id,
            "context_id": context_id,
            "customer_id": customer_id,
            "material": material,
            "surface": surface,
            "quoted_unit_price": quoted_unit_price,
            "actual_unit_cost": actual_unit_cost,
            "deviation_pct": deviation,
            "outcome": outcome,
            "calibration_action": action,
            "confidence": confidence,
        }

    def get_adjustments(self, customer_id: str,
                        material: Optional[str] = None) -> Dict[str, Any]:
        """读取该客户(可选材料)的累计价格偏移建议."""
        rows = self.crm.get_quote_calibrations(customer_id, material=material, limit=50)
        return self._aggregate(rows)

    def get_global_bias(self, material: Optional[str] = None) -> Dict[str, Any]:
        """跨客户聚合 (样本稀少材料冷启动)."""
        try:
            if material:
                rows = self.crm._conn.execute(
                    "SELECT customer_id,material,surface,quoted_unit_price,"
                    "actual_unit_cost,deviation_pct,outcome,calibration_action,"
                    "confidence FROM quote_calibration WHERE material=? "
                    "ORDER BY created_at DESC LIMIT 200",
                    (material,)).fetchall()
            else:
                rows = self.crm._conn.execute(
                    "SELECT customer_id,material,surface,quoted_unit_price,"
                    "actual_unit_cost,deviation_pct,outcome,calibration_action,"
                    "confidence FROM quote_calibration "
                    "ORDER BY created_at DESC LIMIT 200").fetchall()
            cols = ["customer_id", "material", "surface", "quoted_unit_price",
                    "actual_unit_cost", "deviation_pct", "outcome",
                    "calibration_action", "confidence"]
            dicts = [dict(zip(cols, r)) for r in rows]
            return self._aggregate(dicts)
        except Exception:
            return self._aggregate([])

    def _get_model(self, customer_id: str) -> Dict[str, Any]:
        """获取客户定价模型。"""
        try:
            from services.sandbox import get_sandbox
            sandbox = get_sandbox(customer_id)
            model = sandbox.get_pricing_model()
            sandbox.close()
            return model
        except Exception:
            return {"material_coeff": 0, "surface_coeff": 0, "tolerance_coeff": 0}

    def predict_accuracy(self, customer_id: str, n_history: int) -> Dict[str, Any]:
        """预测报价精度 (基于历史样本量)。"""
        try:
            from services.sandbox import get_sandbox
            sandbox = get_sandbox(customer_id)
            model = sandbox.get_pricing_model()
            sandbox.close()
            n = model.get("total_quotes", 0)
            deviation = model.get("avg_deviation", 0)
        except Exception:
            n, deviation = 0, 0.0
        if n >= 20:
            confidence, error_mult = "high", 0.5
        elif n >= 10:
            confidence, error_mult = "medium", 0.7
        elif n >= 3:
            confidence, error_mult = "low", 1.0
        else:
            confidence, error_mult = "very_low", 1.5
        return {"sample_size": n, "confidence": confidence,
                "expected_error_pct": round(abs(deviation) * error_mult, 2),
                "avg_deviation": deviation}

    def _calc_margin(self, quote: Dict[str, Any]) -> float:
        """计算预估毛利。"""
        unit_price = quote.get("unit_price", 0)
        final_price = quote.get("final_price", unit_price)
        if not final_price or not unit_price:
            return 0.0
        return round((final_price - unit_price) / final_price * 100, 1)

    def _get_target_margin(self, customer: Dict[str, Any],
                               model: Dict[str, Any]) -> float:
        """根据客户历史和风险计算目标毛利。"""
        base_margin = target_margin_pct()  # 单源: settings.yaml pricing.target_margin_pct
        health_score = 0
        try:
            from services.customer_health import CustomerHealthEngine
            health = CustomerHealthEngine(self.crm).calculate_health(customer)
            health_score = health.get("health_score", 50)
        except Exception:
            pass
        if health_score > 75:
            base_margin -= 3
        elif health_score < 30:
            base_margin += 5
        if model.get("win_rate", 0.5) < 0.3:
            base_margin -= 2
        return max(12, min(40, base_margin))

    def _aggregate(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(rows)
        if n == 0:
            return {
                "bias_pct": 0.0,
                "confidence": 0.0,
                "sample_count": 0,
                "recommendation": "no_change",
                "low_confidence": True,
            }
        devs = [r.get("deviation_pct") for r in rows
                if r.get("deviation_pct") is not None]
        avg_dev = sum(devs) / len(devs) if devs else 0.0
        # bias 提案 = 平均偏差, 截断到 ±MAX_BIAS_PCT
        bias = max(-MAX_BIAS_PCT, min(MAX_BIAS_PCT, avg_dev))
        sample_count = n
        confidence = min(1.0, sample_count / float(MIN_SAMPLES)) * (0.85 if devs else 0.3)
        if sample_count < MIN_SAMPLES:
            confidence = min(confidence, 0.4)
            bias = bias  # 仍给出提案, 但标记 low_confidence
        if bias > 1.0:
            rec = "price_up"
        elif bias < -1.0:
            rec = "price_down"
        else:
            rec = "no_change"
        return {
            "bias_pct": round(bias, 2),
            "confidence": round(confidence, 3),
            "sample_count": sample_count,
            "avg_deviation_pct": round(avg_dev, 2),
            "recommendation": rec,
            "low_confidence": sample_count < MIN_SAMPLES,
            "cannot_override_price": True,
        }

    @staticmethod
    def _decide_action(outcome: str, deviation: Optional[float]) -> str:
        outcome = (outcome or "").lower()
        if deviation is None:
            if outcome == "lost":
                return "no_change_check_intent"
            return "no_change"
        if outcome == "won" and deviation > DECISION_THRESHOLD_PCT:
            return "price_up_pct_3"
        if outcome == "won" and deviation < -DECISION_THRESHOLD_PCT:
            return "price_down_pct_2"
        if outcome == "lost" and deviation > DOWN_THRESHOLD_PCT:
            return "price_down_pct_5"
        if outcome == "lost" and deviation < -DECISION_THRESHOLD_PCT:
            return "price_down_pct_3"
        return "no_change"

    @staticmethod
    def _estimate_confidence(customer_id: str, material: str) -> float:
        # 样本量驱动; 实际由 _aggregate 再基于行数收紧
        return 0.5

    # -------- T6.4 calibrate API (与 record_outcome 并存) --------

    def calibrate(self, customer: Dict[str, Any], rfq: Dict[str, Any],
                  base_quote: Dict[str, Any]) -> tuple:
        """返回 (calibrated_copy, adjustments)。calibrated 仅为提案副本。

        铁律①: 调用方不得把 calibrated.unit_price 当作 Timo 权威终价写回
        final_price 而不带 _source; overlay 默认只作证据/提案。
        """
        calibrated = dict(base_quote or {})
        adjustments: Dict[str, Any] = {"applied": [], "notes": [], "proposal_only": True}
        cid = (customer or {}).get("customer_id") or ""
        model = self._get_model(cid) if cid else {
            "material_coeff": 0, "surface_coeff": 0, "tolerance_coeff": 0,
            "quantity_discount": 0, "avg_deviation": 0}

        base_unit = float(calibrated.get("unit_price") or 0)
        if base_unit <= 0:
            calibrated.setdefault("unit_price", 0.0)
            adjustments["notes"].append("no base unit_price")
            return calibrated, adjustments

        # 材料系数
        mc = float(model.get("material_coeff") or 0)
        if mc:
            calibrated["unit_price"] = float(calibrated["unit_price"]) * (1 + mc / 100)
            adjustments["applied"].append(f"material_coeff:{mc}%")
            adjustments["notes"].append(f"材料系数修正 {mc}%")

        # 表面系数
        sc = float(model.get("surface_coeff") or 0)
        if sc:
            calibrated["unit_price"] = float(calibrated["unit_price"]) * (1 + sc / 100)
            adjustments["applied"].append(f"surface_coeff:{sc}%")
            adjustments["notes"].append(f"表面处理系数修正 {sc}%")

        # 公差系数
        tc = float(model.get("tolerance_coeff") or 0)
        if tc:
            calibrated["unit_price"] = float(calibrated["unit_price"]) * (1 + tc / 100)
            adjustments["applied"].append(f"tolerance_coeff:{tc}%")
            adjustments["notes"].append(f"精度系数修正 {tc}%")

        # 数量折扣 (线性简化)
        qd = float(model.get("quantity_discount") or 0)
        if qd:
            qty = int((rfq or {}).get("quantity") or 1)
            discount = qd * (qty / 100)
            calibrated["unit_price"] = float(calibrated["unit_price"]) * (1 - discount / 100)
            adjustments["applied"].append(f"quantity_discount:{discount:.2f}%")
            adjustments["notes"].append(f"数量折扣 {discount:.2f}%")

        # 历史偏差
        avg_dev = float(model.get("avg_deviation") or 0)
        if abs(avg_dev) > 2:
            calibrated["unit_price"] = float(calibrated["unit_price"]) * (1 + avg_dev / 100)
            adjustments["applied"].append(f"avg_deviation:{avg_dev}")
            adjustments["notes"].append(f"历史偏差修正 {avg_dev}%")

        # 目标毛利 (提案)
        target_margin = self._get_target_margin(customer or {}, model)
        calibrated["margin_pct"] = target_margin
        adjustments["applied"].append(f"target_margin:{target_margin}")

        final_price = calibrated.get("final_price") or calibrated.get("unit_price") or 0
        if final_price:
            calibrated["estimated_margin"] = self._calc_margin(calibrated)

        adjustments["calibrated_price"] = calibrated.get("unit_price")
        adjustments["original_price"] = base_quote.get("unit_price")
        if base_quote.get("unit_price"):
            adjustments["price_change_pct"] = (
                (float(calibrated.get("unit_price") or 0) - float(base_quote.get("unit_price") or 0))
                / float(base_quote.get("unit_price")) * 100
            )
        adjustments["cannot_override_price"] = True
        return calibrated, adjustments

    def predict_accuracy(self, customer_id: str, n_history: int = 0) -> Dict[str, Any]:
        """样本量 → 置信度/预期误差带 (提案)."""
        n = int(n_history or 0)
        if n <= 0:
            try:
                rows = self.crm.get_quote_calibrations(customer_id, limit=50) \
                    if hasattr(self.crm, "get_quote_calibrations") else []
                n = len(rows or [])
            except Exception:
                n = 0
        confidence = min(1.0, n / float(MIN_SAMPLES)) if n else 0.2
        expected_err = max(3.0, 18.0 - n * 2.0)
        return {
            "customer_id": customer_id,
            "n_history": n,
            "confidence": round(confidence, 3),
            "expected_error_pct": round(expected_err, 2),
            "low_confidence": n < MIN_SAMPLES,
        }

    @staticmethod
    def _calc_margin(quote: Dict[str, Any]) -> float:
        """margin% = (final - unit_related_cost_proxy) / final。

        测试约定: unit_price=75, final_price=100 → 25.0
        """
        try:
            unit = float(quote.get("unit_price") or 0)
            final = float(quote.get("final_price") or 0)
        except (TypeError, ValueError):
            return 0.0
        if final <= 0:
            return 0.0
        # 将 unit_price 视为成本代理时的毛利
        return round((final - unit) / final * 100.0, 2)

    @staticmethod
    def _get_target_margin(customer: Dict[str, Any], model: Dict[str, Any]) -> float:
        """目标毛利, 夹在 12–40。健康分/赢单率微调。"""
        base_margin = target_margin_pct()  # 单源: settings.yaml pricing.target_margin_pct
        health_score = 50.0
        try:
            # 健康分可选注入
            health_score = float((customer or {}).get("health_score") or 50)
        except Exception:
            health_score = 50.0
        if health_score > 75:
            base_margin -= 3
        elif health_score < 30:
            base_margin += 5
        lost = int((model or {}).get("total_lost") or 0)
        win_rate = float((model or {}).get("win_rate") or 0.5)
        if win_rate < 0.3 or lost >= 3:
            base_margin -= 2
        return max(12.0, min(40.0, base_margin))

    def _get_model(self, customer_id: str) -> Dict[str, Any]:
        """客户定价模型: 优先 sandbox, 否则从 quote_calibration 聚合。"""
        try:
            from services.sandbox import get_sandbox
            sb = get_sandbox(customer_id)
            model = sb.get_pricing_model()
            try:
                sb.close()
            except Exception:
                pass
            if isinstance(model, dict) and model:
                return model
        except Exception:
            pass
        adj = self.get_adjustments(customer_id)
        return {
            "material_coeff": 0,
            "surface_coeff": 0,
            "tolerance_coeff": 0,
            "quantity_discount": 0,
            "avg_deviation": float(adj.get("avg_deviation_pct") or 0),
            "win_rate": 0.5,
            "total_lost": 0,
        }

