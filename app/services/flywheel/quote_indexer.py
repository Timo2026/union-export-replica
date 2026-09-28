"""flywheel.quote_indexer — 报价 → 向量索引 (飞轮数据入口).

每完成一笔报价 → 向量化 → 写入租户私有向量集合.
下次该租户来询盘 → SimilarRecall 召回 → PriceCorrector 修正.

契约:
  - 索引失败绝不阻塞黄金链 (best-effort, 失败只警告)
  - 文本 = 客户画像 + 工艺摘要 + 报价 + 反应 + 复盘
  - metadata = tenant_id + material/surface/qty/tolerance + price + margin + reaction
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from .tenant import TenantScope
from .vector_store import VectorStore, get_vector_store

log = logging.getLogger(__name__)


class QuoteIndexer:
    """报价索引器 — 把成交/失败/复盘写入向量库."""

    KIND = "quotes"  # 集合后缀: tenant_<id>_quotes

    def __init__(self, store: Optional[VectorStore] = None):
        self.store = store or get_vector_store()

    def index_quote(self, scope: TenantScope, ctx: Dict[str, Any],
                    verification: Optional[Dict[str, Any]] = None,
                    quote: Optional[Dict[str, Any]] = None,
                    reaction: str = "pending",
                    postmortem: Optional[Dict[str, Any]] = None) -> bool:
        """索引一笔报价到租户私有集合.

        Args:
            scope: 租户作用域
            ctx: Context dict (含 rfq/customer/commercial)
            verification: 验证结果 (含 status/reasons)
            quote: 报价 dict (覆盖 ctx.commercial.quote)
            reaction: won/lost/silent/reacting/pending
            postmortem: 复盘 dict (含 outcome/note)
        """
        try:
            collection = scope.collection_for(self.KIND)
            ctx_id = ctx.get("context_id", "unknown")
            text = self._compose_text(ctx, verification, quote, reaction, postmortem)
            payload = self._compose_payload(scope, ctx, verification, quote,
                                            reaction, postmortem)
            ok = self.store.upsert(collection, ctx_id, text, payload)
            log.info("[quote_indexer] indexed %s → %s reaction=%s ok=%s",
                     ctx_id, collection, reaction, ok)
            return ok
        except Exception as e:
            log.warning("[quote_indexer] 索引失败 (不阻塞): %r", e)
            return False

    def _compose_text(self, ctx: Dict[str, Any],
                      verification: Optional[Dict[str, Any]],
                      quote: Optional[Dict[str, Any]],
                      reaction: str,
                      postmortem: Optional[Dict[str, Any]]) -> str:
        """合成可被语义检索的文本 (包含所有召回信号)."""
        rfq = ctx.get("rfq", {}) or {}
        cust = ctx.get("customer", {}) or {}
        cm = ctx.get("commercial", {}) or {}
        q = quote or cm.get("quote", {}) or {}
        ver = verification or {}

        parts = [
            f"客户 {cust.get('name', cust.get('customer_id', '?'))}",
            f"国家 {cust.get('country', '?')}",
            f"材料 {rfq.get('material', '?')}",
            f"表面 {rfq.get('surface', rfq.get('surface_treatment', '?'))}",
            f"数量 {rfq.get('quantity', '?')}",
            f"公差 {rfq.get('tolerance_grade', rfq.get('tolerance', '?'))}",
            f"工艺 {rfq.get('process', 'CNC')}",
        ]
        if q:
            parts.append(f"单价 {q.get('unit_price', '?')}")
            parts.append(f"总价 {q.get('final_price', '?')} {q.get('currency', 'CNY')}")
            parts.append(f"毛利 {cm.get('margin_pct', q.get('margin_pct', '?'))}%")
            parts.append(f"交期 {q.get('lead_time_days', '?')}天")
        parts.append(f"反应 {reaction}")
        parts.append(f"状态 {ver.get('status', '?')}")
        if ver.get("reasons"):
            parts.append(f"原因 {'; '.join(ver['reasons'])}")
        if postmortem:
            parts.append(f"复盘 outcome={postmortem.get('outcome', '?')}")
            if postmortem.get("note"):
                parts.append(f"备注 {postmortem['note']}")
        return " ".join(str(p) for p in parts)

    def _compose_payload(self, scope: TenantScope, ctx: Dict[str, Any],
                         verification: Optional[Dict[str, Any]],
                         quote: Optional[Dict[str, Any]],
                         reaction: str,
                         postmortem: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        rfq = ctx.get("rfq", {}) or {}
        cm = ctx.get("commercial", {}) or {}
        q = quote or cm.get("quote", {}) or {}
        ver = verification or {}
        return {
            "tenant_id": scope.tenant_id,
            "customer_id": scope.customer_id,
            "group_id": scope.group_id,
            "context_id": ctx.get("context_id"),
            "material": rfq.get("material"),
            "surface": rfq.get("surface"),
            "quantity": rfq.get("quantity"),
            "tolerance": rfq.get("tolerance_grade") or rfq.get("tolerance"),
            "process": rfq.get("process", "CNC"),
            "unit_price": q.get("unit_price"),
            "final_price": q.get("final_price"),
            "currency": q.get("currency", "CNY"),
            "margin_pct": cm.get("margin_pct") or q.get("margin_pct"),
            "lead_time_days": q.get("lead_time_days"),
            "verification_status": ver.get("status"),
            "reaction": reaction,
            "lost_reason": (postmortem or {}).get("outcome") if reaction == "lost" else None,
            "indexed_at": time.time(),
        }
