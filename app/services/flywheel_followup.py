"""flywheel_followup.py — 客户跟进飞轮核心模块.

实现: 每次交互 → 更新客户画像 → 偏好记忆 → 下次自动适配。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class FlywheelFollowup:
    """客户跟进飞轮 — 画像越来越精准。

    核心逻辑:
      1. 每次RFQ/报价更新客户画像
      2. 偏好自动记忆 (材料/表面处理/精度/国家)
      3. 下次RFQ自动加载上下文并建议
    """

    PROFILE_FIELDS = ["preferred_material", "preferred_surface",
                      "preferred_tolerance", "country", "avg_quantity",
                      "price_sensitivity", "lead_time_priority"]

    def __init__(self, sandbox):
        self.sandbox = sandbox

    def update_profile(self, rfq: Dict[str, Any], outcome: str = "") -> Dict[str, Any]:
        """每次交互更新客户画像。"""
        profile = self._load_profile()

        # 更新偏好
        if rfq.get("material"):
            profile["preferred_material"] = rfq.get("material")
        if rfq.get("surface"):
            profile["preferred_surface"] = rfq.get("surface")
        if rfq.get("tolerance_grade"):
            profile["preferred_tolerance"] = rfq.get("tolerance_grade")

        # 更新统计
        profile["total_interactions"] = profile.get("total_interactions", 0) + 1
        profile["last_interaction"] = rfq.get("created_at")

        # 计算价格敏感度 (基于历史毛利)
        history = self.sandbox.get_history()
        margins = [q.get("margin_pct") for q in history.get("quotes", []) if q.get("margin_pct")]
        if margins:
            avg_margin = sum(margins) / len(margins)
            # 毛利低 → 客户要求低价 → 价格敏感
            profile["price_sensitivity"] = min(1.0, max(0, (25 - avg_margin) / 25))

        # 计算交期优先级 (基于丢单原因)
        postmortems = history.get("postmortems", [])
        lead_issues = sum(1 for p in postmortems if "lead" in str(p).lower() or "交期" in str(p))
        profile["lead_time_priority"] = min(1.0, lead_issues / max(len(postmortems), 1) + 0.2)

        self._save_profile(profile)
        return profile

    def get_context_for_new_rfq(self) -> Dict[str, Any]:
        """新RFQ时自动加载客户上下文。"""
        profile = self._load_profile()
        history = self.sandbox.get_history()
        suggestions = self._generate_suggestions(profile, history)
        auto_fill = self._get_auto_fill(profile)

        return {
            "customer_profile": profile,
            "historical_quote_count": history.get("n", 0),
            "historical_avg_margin": self._avg_margin(history),
            "auto_suggestions": suggestions,
            "auto_fill": auto_fill,
        }

    def _generate_suggestions(self, profile: Dict[str, Any],
                                 history: Dict[str, Any]) -> List[str]:
        """基于历史自动生成建议。"""
        suggestions = []

        if profile.get("price_sensitivity", 0) > 0.6:
            suggestions.append("该客户价格敏感, 建议降低风险余量至2%")
        if profile.get("lead_time_priority", 0) > 0.6:
            suggestions.append("该客户关注交期, 建议优先排产")
        if profile.get("preferred_material"):
            suggestions.append(f"历史偏好 {profile['preferred_material']}, 自动预填材料")
        if profile.get("preferred_surface"):
            suggestions.append(f"历史偏好 {profile['preferred_surface']}, 自动预填表面处理")
        if history.get("n", 0) >= 5:
            avg_dev = self.sandbox.get_pricing_model().get("avg_deviation", 0)
            if abs(avg_dev) > 2:
                suggestions.append(f"历史报价偏差 {avg_dev}%, 建议调整报价系数")
        if history.get("postmortems"):
            lost = sum(1 for p in history["postmortems"] if p.get("outcome") == "lost")
            if lost >= 2:
                suggestions.append(f"有 {lost} 次丢单记录, 下次报价重点关注价格竞争力")

        if not suggestions:
            suggestions.append("新客户, 使用默认策略报价")
        return suggestions

    def _get_auto_fill(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """获取自动填充值。"""
        return {
            "material": profile.get("preferred_material"),
            "surface": profile.get("preferred_surface"),
            "tolerance_grade": profile.get("preferred_tolerance"),
            "country": profile.get("country"),
        }

    def _avg_margin(self, history: Dict[str, Any]) -> float:
        """计算历史平均毛利。"""
        margins = [q.get("margin_pct") for q in history.get("quotes", []) if q.get("margin_pct")]
        return round(sum(margins) / len(margins), 1) if margins else 0.0

    def _load_profile(self) -> Dict[str, Any]:
        """加载客户画像 (从沙箱)。"""
        try:
            kb = self.sandbox.get_knowledge_base(limit=20)
            profile = {}
            for item in kb:
                if item.get("category") == "profile":
                    profile[item.get("keyword", "")] = item.get("insight", "")
            profile.setdefault("total_interactions", 0)
            return profile
        except Exception:
            return {}

    def _save_profile(self, profile: Dict[str, Any]) -> None:
        """保存客户画像到沙箱知识库。"""
        for key in ["preferred_material", "preferred_surface", "preferred_tolerance",
                    "country", "price_sensitivity", "lead_time_priority"]:
            value = profile.get(key)
            if value is not None:
                self.sandbox.add_knowledge(
                    category="profile",
                    keyword=key,
                    insight=str(value),
                    severity="info"
                )
        self.sandbox.add_followup(
            action="profile_updated",
            trigger="interaction",
            result=f"total={profile.get('total_interactions', 0)}"
        )
