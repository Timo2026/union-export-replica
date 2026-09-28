"""customer_profile.py — 客户偏好画像 (T6.5, v6.1 飞轮层).

从历史报价 + outcome 自动学习客户偏好:
  tolerance_bias / material_preference / surface_preference / quantity_pattern
  decision_speed_days / price_sensitivity / preferred_incoterms
  communication_style / risk_signals

每个客户一份画像, 沙箱隔离存储 (preference_profile 表).

规则 (纯确定性, 无 LLM):
  tolerance_bias: 看 customer 高频 tolerance_grade 决定 premium/standard/budget
  material_preference: TOP-3 高频材料
  surface_preference: TOP-3 高频表面
  quantity_pattern: 历史 quantity 的 mean/std
  decision_speed_days: won quotes 的 created_at 平均间隔
  price_sensitivity: 赢单率 < 30% = high, 30-70% = med, > 70% = low
  preferred_incoterms: 从 rfq.payload 里抽 incoterm
  communication_style: 邮件文本风格 (formal/casual)
  risk_signals: 丢单 + 议价 + 投诉
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from services.crm_memory import CRMMemory


class CustomerProfile:
    """客户偏好画像 - 每客户一份, 沙箱隔离存储."""

    def __init__(self, customer_id: str, crm: "CRMMemory"):
        self.cid = customer_id
        self.crm = crm

    def build(self) -> Dict[str, Any]:
        """从历史数据学习偏好, 落库, 返回画像."""
        hist = self.crm.list_customer_history(self.cid, limit=50)
        quotes = hist.get("quotes", [])
        postmortems = hist.get("postmortems", [])

        materials = self._extract_materials(quotes)
        surfaces = self._extract_surfaces(quotes)
        qtys = self._extract_quantities(quotes)

        tolerance_bias = self._infer_tolerance_bias(quotes)
        decision_speed = self._infer_decision_speed(postmortems)
        price_sens = self._infer_price_sensitivity(postmortems)
        incoterms = self._infer_incoterms(quotes)
        style = self._infer_communication_style(quotes)
        risks = self._extract_risk_signals(postmortems)

        qty_avg = round(sum(qtys) / len(qtys), 1) if qtys else None
        qty_std = round(self._std(qtys), 1) if qtys and len(qtys) > 1 else None

        self.crm.upsert_profile(
            customer_id=self.cid,
            tolerance_bias=tolerance_bias,
            material_preference=materials[:5],
            surface_preference=surfaces[:5],
            quantity_avg=qty_avg,
            quantity_std=qty_std,
            decision_speed_days=decision_speed or 7.0,
            price_sensitivity=price_sens,
            preferred_incoterms=incoterms,
            communication_style=style,
            risk_signals=risks,
        )
        return self.crm.get_profile(self.cid) or {}

    def update_from_outcome(self, outcome: str, context_id: str = "") -> None:
        """单次 outcome 后增量更新画像."""
        cur = self.crm.get_profile(self.cid) or {}
        risks = cur.get("risk_signals") or []
        if outcome == "lost":
            risks.append({"type": "lost", "context_id": context_id, "at": time.time()})
        elif outcome == "won":
            risks.append({"type": "won", "context_id": context_id, "at": time.time()})
        # 仅保留最近 20 条
        risks = risks[-20:]
        self.crm.upsert_profile(
            customer_id=self.cid,
            tolerance_bias=cur.get("tolerance_bias", "standard"),
            material_preference=cur.get("material_preference") or [],
            surface_preference=cur.get("surface_preference") or [],
            quantity_avg=cur.get("quantity_avg"),
            quantity_std=cur.get("quantity_std"),
            decision_speed_days=cur.get("decision_speed_days", 7.0),
            price_sensitivity=cur.get("price_sensitivity", "med"),
            preferred_incoterms=cur.get("preferred_incoterms") or [],
            communication_style=cur.get("communication_style", "formal"),
            risk_signals=risks,
        )

    # ---------- 推断 ----------
    def _extract_materials(self, quotes: List[Dict[str, Any]]) -> List[str]:
        """从 quotes 表的 context_id 反查 rfqs.material."""
        mats = []
        for q in quotes:
            cid = q.get("context_id")
            if not cid:
                continue
            row = self.crm._conn.execute(
                "SELECT material FROM rfqs WHERE context_id=?", (cid,)).fetchone()
            if row and row[0]:
                mats.append(row[0])
        return [m for m, _ in Counter(mats).most_common()]

    def _extract_surfaces(self, quotes: List[Dict[str, Any]]) -> List[str]:
        surfs = []
        for q in quotes:
            cid = q.get("context_id")
            if not cid:
                continue
            row = self.crm._conn.execute(
                "SELECT surface FROM rfqs WHERE context_id=?", (cid,)).fetchone()
            if row and row[0]:
                surfs.append(row[0])
        return [s for s, _ in Counter(surfs).most_common()]

    def _extract_quantities(self, quotes: List[Dict[str, Any]]) -> List[int]:
        qtys = []
        for q in quotes:
            cid = q.get("context_id")
            if not cid:
                continue
            row = self.crm._conn.execute(
                "SELECT quantity FROM rfqs WHERE context_id=?", (cid,)).fetchone()
            if row and row[0]:
                qtys.append(int(row[0]))
        return qtys

    def _infer_tolerance_bias(self, quotes: List[Dict[str, Any]]) -> str:
        grades = []
        for q in quotes:
            cid = q.get("context_id")
            if not cid:
                continue
            row = self.crm._conn.execute(
                "SELECT tolerance FROM rfqs WHERE context_id=?", (cid,)).fetchone()
            if row and row[0]:
                grades.append(str(row[0]).upper())
        if not grades:
            return "standard"
        # IT4/IT5 = premium, IT7/IT8 = standard, IT9+ = budget
        premium = sum(1 for g in grades if any(k in g for k in ("IT4", "IT5")))
        budget = sum(1 for g in grades if any(k in g for k in ("IT9", "IT10", "IT11")))
        if premium > budget and premium > len(grades) * 0.3:
            return "premium"
        if budget > premium and budget > len(grades) * 0.3:
            return "budget"
        return "standard"

    def _infer_decision_speed(self, postmortems: List[Dict[str, Any]]) -> Optional[float]:
        if len(postmortems) < 2:
            return None
        ts = sorted([p.get("created_at", 0) for p in postmortems])
        diffs = [(ts[i+1] - ts[i]) / 86400.0 for i in range(len(ts)-1)]
        return round(sum(diffs) / len(diffs), 1) if diffs else None

    def _infer_price_sensitivity(self, postmortems: List[Dict[str, Any]]) -> str:
        n = len(postmortems)
        if n == 0:
            return "med"
        won = sum(1 for p in postmortems if p.get("outcome") == "won")
        rate = won / n
        if rate < 0.30:
            return "high"
        if rate > 0.70:
            return "low"
        return "med"

    def _infer_incoterms(self, quotes: List[Dict[str, Any]]) -> List[str]:
        terms = []
        for q in quotes:
            cid = q.get("context_id")
            if not cid:
                continue
            row = self.crm._conn.execute(
                "SELECT payload FROM rfqs WHERE context_id=?", (cid,)).fetchone()
            if row and row[0]:
                try:
                    payload = json.loads(row[0])
                    if isinstance(payload, dict) and payload.get("incoterm"):
                        terms.append(payload["incoterm"])
                except Exception:
                    pass
        return [t for t, _ in Counter(terms).most_common(3)]

    def _infer_communication_style(self, quotes: List[Dict[str, Any]]) -> str:
        # 简化: 没文本直接返回 formal
        return "formal"

    def _extract_risk_signals(self, postmortems: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        signals = []
        for p in postmortems[-10:]:
            if p.get("outcome") == "lost":
                signals.append({
                    "type": "loss_history",
                    "context_id": p.get("context_id"),
                    "at": p.get("created_at"),
                })
            note = (p.get("note") or "").lower()
            if "dispute" in note or "complaint" in note:
                signals.append({
                    "type": "dispute",
                    "context_id": p.get("context_id"),
                    "note": p.get("note"),
                    "at": p.get("created_at"),
                })
        return signals

    def _std(self, values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return math.sqrt(variance)