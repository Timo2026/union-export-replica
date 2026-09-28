"""flywheel.similar_recall — 相似情境召回 (报价前的"课前预习").

在 calc_quote 之前调用, 注入历史相似案例:
  - similar_won:  该租户历史成交的相似件 → 价格带宽
  - similar_lost: 该租户历史失败的相似件 → 避免重蹈
  - price_band:   历史成交价 p25/p50/p75
  - confidence:   数据越多越自信

冷启动: 租户无历史 → 退到 kb_market (匿名聚合), 标 _cold_start=true.
"""
from __future__ import annotations

import logging
import statistics
from typing import Any, Dict, List, Optional

from .tenant import TenantScope
from .vector_store import VectorStore, get_vector_store

log = logging.getLogger(__name__)

PUBLIC_MARKET_COLLECTION = "kb_market"  # 全局匿名市场聚合 (冷启动)


class SimilarRecall:
    """相似情境召回器."""

    KIND = "quotes"

    def __init__(self, store: Optional[VectorStore] = None, limit: int = 5):
        self.store = store or get_vector_store()
        self.limit = limit

    def before_quote(self, scope: TenantScope, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """报价前召回历史相似案例.

        Returns:
            {
              "similar_won": [...],      # 成交命中 (top limit)
              "similar_lost": [...],     # 失败命中 (top limit)
              "price_band": {p25,p50,p75,count},  # 成交价带宽
              "sample_count": int,       # 该租户总样本
              "confidence": float,       # 0..1
              "query": str,              # 查询文本 (审计)
              "collection": str,         # 实际查询集合
              "_cold_start": bool,       # 是否冷启动退到匿名
            }
        """
        query = self._compose_query(ctx)
        collection = scope.collection_for(self.KIND)
        tenant_count = self.store.count(collection)

        # 冷启动: 租户无历史 → 退到匿名市场聚合
        cold_start = tenant_count == 0
        if cold_start:
            collection = PUBLIC_MARKET_COLLECTION
            tenant_filter = None  # 公共集合不过滤
            log.info("[similar_recall] 冷启动: %s → 退到 %s", scope.tenant_id, collection)
        else:
            tenant_filter = scope.tenant_id

        # 查成交 (won + reacting)
        won_hits = self.store.search(
            collection, query, limit=self.limit,
            tenant_filter=tenant_filter,
            extra_filter={"reaction": ["won", "reacting"]},
        )

        # 查失败 (lost + silent)
        lost_hits = self.store.search(
            collection, query, limit=self.limit,
            tenant_filter=tenant_filter,
            extra_filter={"reaction": ["lost", "silent"]},
        )

        # 价格带宽 (仅 won)
        price_band = self._compute_price_band(won_hits)

        # 样本数 (实际命中总数)
        total_hits = len(won_hits) + len(lost_hits)
        confidence = min(1.0, total_hits / float(self.limit * 2))

        return {
            "similar_won": won_hits,
            "similar_lost": lost_hits,
            "price_band": price_band,
            "sample_count": tenant_count if not cold_start else 0,
            "confidence": round(confidence, 3),
            "query": query,
            "collection": collection,
            "_cold_start": cold_start,
        }

    def _compose_query(self, ctx: Dict[str, Any]) -> str:
        """合成召回查询文本 (材料+表面+数量+公差+交期)."""
        rfq = ctx.get("rfq", {}) or {}
        parts = [
            f"材料 {rfq.get('material', '?')}",
            f"表面 {rfq.get('surface', '?')}",
            f"数量 {rfq.get('quantity', '?')}",
            f"公差 {rfq.get('tolerance_grade', '?')}",
            f"工艺 {rfq.get('process', 'CNC')}",
        ]
        cust = ctx.get("customer", {}) or {}
        if cust.get("country"):
            parts.append(f"国家 {cust['country']}")
        return " ".join(parts)

    def _compute_price_band(self, won_hits: List[Dict[str, Any]]) -> Dict[str, Any]:
        """从 won 命中算价格带宽 (p25/p50/p75)."""
        prices = []
        for h in won_hits:
            p = h.get("payload", {}).get("final_price")
            if isinstance(p, (int, float)) and p > 0:
                prices.append(float(p))
        if not prices:
            return {"count": 0}
        prices.sort()
        n = len(prices)
        def _pct(q: float) -> float:
            idx = max(0, min(n - 1, int(q * (n - 1))))
            return round(prices[idx], 2)
        return {
            "p25": _pct(0.25), "p50": _pct(0.50), "p75": _pct(0.75),
            "min": round(prices[0], 2), "max": round(prices[-1], 2),
            "count": n,
        }
