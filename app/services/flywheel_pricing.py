"""flywheel_pricing.py — 报价精度飞轮核心模块.

实现: 历史报价 → 偏差分析 → 定价模型修正 → 下次报价更准。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.config import target_margin_pct


class FlywheelPricing:
    """报价精度飞轮 — 越报越准。

    核心逻辑:
      1. 每次报价记录偏差 (quoted vs actual)
      2. 偏差反馈到定价模型系数
      3. 下次报价自动应用修正后的系数
    """

    DEFAULT_MODEL = {
        "material_coeff": 0.0,
        "surface_coeff": 0.0,
        "tolerance_coeff": 0.0,
        "quantity_discount": 0.0,
        "avg_deviation": 0.0,
        "win_rate": 0.5,
        "total_quotes": 0,
        "total_won": 0,
        "total_lost": 0,
    }

    def __init__(self, sandbox):
        self.sandbox = sandbox
        self._learning_rate = 0.3  # 前期学习快

    def predict_margin(self, rfq: Dict[str, Any]) -> float:
        """预测本次报价的预期毛利。"""
        model = self.sandbox.get_pricing_model()
        base_margin = target_margin_pct()  # 单源: settings.yaml pricing.target_margin_pct
        # 根据历史调整
        avg_dev = model.get("avg_deviation", 0)
        base_margin += avg_dev  # 历史偏差直接影响预期毛利
        win_rate = model.get("win_rate", 0.5)
        # 赢单率高 → 毛利可以稍高
        if win_rate > 0.6:
            base_margin += 2
        # 丢单多 → 降低毛利
        if model.get("total_lost", 0) > 3:
            base_margin -= 3
        return max(10, min(40, base_margin))

    def get_adjusted_quote(self, base_quote: Dict[str, Any]) -> Dict[str, Any]:
        """应用客户专属系数后的最终报价。"""
        model = self.sandbox.get_pricing_model()
        adjusted = dict(base_quote)
        coeff = 1.0
        coeff *= (1 + model.get("material_coeff", 0) / 100)
        coeff *= (1 + model.get("surface_coeff", 0) / 100)
        coeff *= (1 + model.get("tolerance_coeff", 0) / 100)
        adjusted["unit_price"] = round(adjusted.get("unit_price", 0) * coeff, 2)
        adjusted["margin_pct"] = self.predict_margin(base_quote)
        adjusted["_flywheel_adjusted"] = True
        adjusted["_adjustment_coeff"] = round(coeff, 4)
        return adjusted

    def update_after_outcome(self, context_id: str, outcome: str,
                                actual_cost: Optional[float] = None,
                                quoted_price: Optional[float] = None) -> Dict[str, Any]:
        """成交/丢单后更新定价模型 — 飞轮核心。"""
        if actual_cost is None or quoted_price is None:
            return {"updated": False, "reason": "missing_data"}

        deviation = (float(actual_cost) - float(quoted_price)) / float(quoted_price) * 100
        won = (outcome == "won")
        model = self.sandbox.get_pricing_model()
        n = model.get("total_quotes", 0) + 1

        # 指数移动平均更新系数 (前期学习快, 后期稳定)
        alpha = 0.3 if n < 5 else 0.1
        new_material = model.get("material_coeff", 0) * (1 - alpha) + deviation * 0.3 * alpha
        new_surface = model.get("surface_coeff", 0) * (1 - alpha) + deviation * 0.2 * alpha
        new_tolerance = model.get("tolerance_coeff", 0) * (1 - alpha) + deviation * 0.2 * alpha

        # 更新平均偏差
        old_avg = model.get("avg_deviation", 0) * model.get("total_quotes", 0)
        avg_deviation = (old_avg + deviation) / n

        # 更新赢单率
        total_won = model.get("total_won", 0) + (1 if won else 0)
        win_rate = total_won / n

        result = self.sandbox.update_pricing_model(
            material_coeff=round(new_material, 4),
            surface_coeff=round(new_surface, 4),
            tolerance_coeff=round(new_tolerance, 4),
            deviation=round(deviation, 2),
            won=won
        )

        return {
            "updated": True,
            "deviation_pct": round(deviation, 2),
            "won": won,
            "new_model": result,
            "sample_size": n,
        }

    def get_accuracy_prediction(self, customer_id: str) -> Dict[str, Any]:
        """预测报价精度 (基于历史样本量)。"""
        model = self.sandbox.get_pricing_model()
        n = model.get("total_quotes", 0)
        deviation = model.get("avg_deviation", 0)

        if n >= 20:
            confidence, error_mult = "high", 0.5
        elif n >= 10:
            confidence, error_mult = "medium", 0.7
        elif n >= 3:
            confidence, error_mult = "low", 1.0
        else:
            confidence, error_mult = "very_low", 1.5

        return {
            "sample_size": n,
            "confidence": confidence,
            "expected_error_pct": round(abs(deviation) * error_mult, 2),
            "avg_deviation": deviation,
        }
