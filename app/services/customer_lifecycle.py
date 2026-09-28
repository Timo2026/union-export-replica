"""customer_lifecycle.py — 客户生命周期状态机 + 流失预警 + 健康分 (T13).

状态流转:
  NEW → INQUIRING → QUOTED → NEGOTIATING → WON → REPEAT ↺
  任意 → DORMANT(30天无互动) → CHURNED(60天) → WINBACK → INQUIRING

铁律:
  - 纯规则状态机, 不调 LLM (铁律① 保持)
  - 阈值从环境变量读, 不硬编码
  - 健康分 0-1 范围 (与 customer_health.py 的 0-100 体系独立)
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from services.crm_memory import CRMMemory

# 阈值从环境变量读 (不硬编码)
DORMANT_DAYS = int(os.environ.get("LIFECYCLE_DORMANT_DAYS", "30"))
CHURNED_DAYS = int(os.environ.get("LIFECYCLE_CHURNED_DAYS", "60"))

# 状态转移图 (合法转移)
TRANSITIONS: Dict[str, List[str]] = {
    "NEW": ["INQUIRING"],
    "INQUIRING": ["QUOTED", "DORMANT"],
    "QUOTED": ["NEGOTIATING", "WON", "DORMANT"],
    "NEGOTIATING": ["WON", "DORMANT"],
    "WON": ["REPEAT", "DORMANT"],
    "REPEAT": ["WON", "DORMANT"],
    "DORMANT": ["CHURNED", "WINBACK", "INQUIRING"],
    "CHURNED": ["WINBACK"],
    "WINBACK": ["INQUIRING"],
}

# 健康分计算权重 (和为 1.0)
_HEALTH_WEIGHTS = {
    "interaction_freq": 0.30,   # 互动频率
    "win_rate": 0.30,            # 成交率
    "recency": 0.25,             # 最近互动天数
    "repeat_gap": 0.15,          # 复购间隔
}

_DAY = 86400.0  # 秒/天


class CustomerLifecycle:
    """客户生命周期状态机 + 流失预警 + 健康分."""

    def __init__(self, crm: "CRMMemory"):
        self.crm = crm

    # ---------- 状态转移 ----------

    def transition(self, customer_id: str, new_state: str) -> bool:
        """校验状态转移合法性, 合法则更新. 返回是否成功.

        非法转移 (不在 TRANSITIONS 中) 返回 False, 不抛异常.
        """
        current = self.crm.get_lifecycle_state(customer_id)
        allowed = TRANSITIONS.get(current, [])
        if new_state not in allowed:
            return False
        self.crm.update_lifecycle(customer_id, new_state)
        return True

    def force_transition(self, customer_id: str, new_state: str) -> None:
        """强制转移 (不校验合法性), 用于 DORMANT/CHURNED 自动巡检."""
        self.crm.update_lifecycle(customer_id, new_state)

    # ---------- 事件钩子 ----------

    def on_rfq_received(self, customer_id: str) -> None:
        """收到询盘: NEW→INQUIRING, DORMANT→INQUIRING, WINBACK→INQUIRING, CHURNED→WINBACK→INQUIRING."""
        current = self.crm.get_lifecycle_state(customer_id)
        if current in ("NEW", "DORMANT", "WINBACK"):
            self.transition(customer_id, "INQUIRING")
        elif current == "CHURNED":
            # CHURNED → WINBACK → INQUIRING (两步)
            self.force_transition(customer_id, "WINBACK")
            self.transition(customer_id, "INQUIRING")
        # INQUIRING/QUOTED/NEGOTIATING/WON/REPEAT 保持不变 (活跃中)

    def on_quote_sent(self, customer_id: str) -> None:
        """发出报价: INQUIRING→QUOTED."""
        self.transition(customer_id, "QUOTED")

    def on_order_won(self, customer_id: str, revenue: float) -> None:
        """成交: QUOTED→WON 或 NEGOTIATING→WON; 若已有 WON/REPEAT 则 REPEAT↺.
        同时记录订单 (total_orders+1, total_revenue+=revenue).
        """
        current = self.crm.get_lifecycle_state(customer_id)
        if current in ("QUOTED", "NEGOTIATING"):
            self.transition(customer_id, "WON")
        elif current in ("WON", "REPEAT"):
            # 复购
            if current == "WON":
                self.transition(customer_id, "REPEAT")
            else:
                self.transition(customer_id, "WON")
        # 记录订单
        self.crm.record_order(customer_id, revenue)
        # 记录互动
        self.crm.record_interaction(customer_id, "order",
                                     f"成交 ${revenue:.2f}")

    # ---------- 流失预警巡检 ----------

    def check_dormant(self) -> List[Dict[str, Any]]:
        """扫描所有客户, 将超过 DORMANT_DAYS 无互动的标为 DORMANT.

        跳过已是 DORMANT/CHURNED 的客户 (避免重复降级).
        返回变更列表 [{customer_id, from_state, to_state, days_inactive}, ...].
        """
        now = time.time()
        threshold = now - DORMANT_DAYS * _DAY
        changes = []
        for cid in self.crm.list_all_customer_ids():
            state = self.crm.get_lifecycle_state(cid)
            # 已是 DORMANT/CHURNED 的跳过
            if state in ("DORMANT", "CHURNED"):
                continue
            last = self.crm.get_customer_last_interaction_at(cid)
            if last is None:
                # 无互动记录, 用 updated_at 回退
                continue
            if last < threshold:
                days_inactive = (now - last) / _DAY
                changes.append({
                    "customer_id": cid,
                    "from_state": state,
                    "to_state": "DORMANT",
                    "days_inactive": round(days_inactive, 1),
                })
                self.force_transition(cid, "DORMANT")
        return changes

    def check_churned(self) -> List[Dict[str, Any]]:
        """将超过 CHURNED_DAYS 无互动的 DORMANT 客户标为 CHURNED, 生成 win_back 跟进任务.

        返回变更列表 [{customer_id, from_state, to_state, days_inactive, follow_up_id}, ...].
        """
        now = time.time()
        threshold = now - CHURNED_DAYS * _DAY
        changes = []
        for cid in self.crm.list_all_customer_ids():
            state = self.crm.get_lifecycle_state(cid)
            if state != "DORMANT":
                continue
            last = self.crm.get_customer_last_interaction_at(cid)
            if last is None:
                continue
            if last < threshold:
                days_inactive = (now - last) / _DAY
                # 标为 CHURNED
                self.force_transition(cid, "CHURNED")
                # 生成 win_back 跟进任务 (due_at = now + 1 天)
                fu_id = self.crm.create_follow_up(
                    customer_id=cid,
                    task_type="win_back",
                    reason=f"流失客户 {round(days_inactive)} 天无互动, 需赢回",
                    due_at=now + _DAY,
                )
                changes.append({
                    "customer_id": cid,
                    "from_state": "DORMANT",
                    "to_state": "CHURNED",
                    "days_inactive": round(days_inactive, 1),
                    "follow_up_id": fu_id,
                })
        return changes

    # ---------- 健康分 ----------

    def compute_health_score(self, customer_id: str) -> float:
        """健康分 = f(互动频率, 成交率, 复购间隔, 最近互动天数). 0-1 范围.

        维度:
          interaction_freq (30%): 最近 30 天互动次数 / 10 (上限 1.0)
          win_rate (30%): 成交率 = total_orders / total_quotes
          recency (25%): 最近互动天数, 7 天内=1.0, 30 天=0.5, 60 天=0.0
          repeat_gap (15%): 复购间隔, 越短越好; 无复购=0.3
        """
        profile = self.crm.get_customer_profile(customer_id)
        if not profile:
            return 0.5  # 未知客户中性分

        now = time.time()

        # 1. 互动频率: 最近 30 天互动次数
        recent_interactions = profile.get("recent_interactions", [])
        recent_30d = [i for i in recent_interactions
                      if i.get("created_at", 0) > now - 30 * _DAY]
        # recent_interactions 只查了最近 5 条, 用 interactions 表全量查更准
        interaction_count = self._count_recent_interactions(customer_id, 30)
        freq_score = min(1.0, interaction_count / 10.0)

        # 2. 成交率
        total_orders = profile.get("total_orders", 0) or 0
        hist = self.crm.list_customer_history(customer_id, limit=100)
        total_quotes = len(hist.get("quotes", []))
        if total_quotes > 0:
            win_score = min(1.0, total_orders / total_quotes)
        else:
            win_score = 0.3  # 无报价中性分

        # 3. 最近互动天数
        last_interaction = profile.get("last_interaction_at")
        if last_interaction and last_interaction > 0:
            days_since = (now - last_interaction) / _DAY
            if days_since <= 7:
                recency_score = 1.0
            elif days_since <= 30:
                recency_score = 0.5 + 0.5 * (30 - days_since) / 23
            elif days_since <= 60:
                recency_score = 0.5 * (60 - days_since) / 30
            else:
                recency_score = 0.0
        else:
            recency_score = 0.0

        # 4. 复购间隔
        if total_orders >= 2:
            # 有复购: 间隔越短越好
            # 简化: 用 last_order_at - first_order 估算平均间隔
            # 这里用 total_orders / tenure_days 近似
            repeat_score = min(1.0, total_orders / 12.0)  # 12 单/年 = 1.0
        elif total_orders == 1:
            repeat_score = 0.5
        else:
            repeat_score = 0.3

        # 加权综合
        score = (
            freq_score * _HEALTH_WEIGHTS["interaction_freq"] +
            win_score * _HEALTH_WEIGHTS["win_rate"] +
            recency_score * _HEALTH_WEIGHTS["recency"] +
            repeat_score * _HEALTH_WEIGHTS["repeat_gap"]
        )
        score = round(min(1.0, max(0.0, score)), 4)

        # 落库
        self.crm.update_customer_health(customer_id, score)
        return score

    def _count_recent_interactions(self, customer_id: str, days: int) -> int:
        """统计最近 N 天的互动次数."""
        threshold = time.time() - days * _DAY
        row = self.crm._conn.execute(
            "SELECT COUNT(*) FROM interactions WHERE customer_id=? AND created_at>=?",
            (customer_id, threshold)).fetchone()
        return row[0] if row else 0

    # ---------- 定时巡检 ----------

    def run_sweep(self) -> Dict[str, Any]:
        """定时巡检: check_dormant + check_churned + 重算健康分.

        返回摘要 {dormant_changes, churned_changes, health_recomputed, total_scanned}.
        """
        dormant_changes = self.check_dormant()
        churned_changes = self.check_churned()

        # 重算所有客户健康分
        health_recomputed = []
        for cid in self.crm.list_all_customer_ids():
            try:
                score = self.compute_health_score(cid)
                health_recomputed.append({"customer_id": cid, "health_score": score})
            except Exception:
                pass

        return {
            "dormant_changes": dormant_changes,
            "churned_changes": churned_changes,
            "health_recomputed": health_recomputed,
            "total_scanned": len(health_recomputed),
        }