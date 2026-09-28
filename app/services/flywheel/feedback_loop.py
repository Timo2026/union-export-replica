"""flywheel.feedback_loop — 飞轮闭环编排器.

串联飞轮所有组件, 提供两个入口:
  - before_quote(scope, ctx)  → 召回 + 修正建议 (注入黄金链 Step 0)
  - post_quote(scope, ctx, ...)  → 打标 + 索引 (注入 crm.write_quote 钩子)

这两个入口是飞轮转一圈的"上半圈"(读) 和"下半圈"(写).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .tenant import TenantScope, resolve_tenant
from .vector_store import VectorStore, get_vector_store
from .quote_indexer import QuoteIndexer
from .similar_recall import SimilarRecall
from .price_corrector import PriceCorrector, CorrectionResult
from .reaction_labeler import ReactionLabeler, LabelResult

log = logging.getLogger(__name__)


class FeedbackLoop:
    """飞轮闭环编排器 — 单例风格."""

    def __init__(self, store: Optional[VectorStore] = None,
                 indexer: Optional[QuoteIndexer] = None,
                 recall: Optional[SimilarRecall] = None,
                 corrector: Optional[PriceCorrector] = None,
                 labeler: Optional[ReactionLabeler] = None):
        self.store = store or get_vector_store()
        self.indexer = indexer or QuoteIndexer(self.store)
        self.recall = recall or SimilarRecall(self.store)
        self.corrector = corrector or PriceCorrector()
        self.labeler = labeler or ReactionLabeler()

    # ============ 上半圈: 报价前 (读) ============

    def before_quote(self, scope_or_ctx: Any,
                     ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """报价前: 召回历史 + 修正建议.

        用法:
            loop = FeedbackLoop()
            scope = resolve_tenant(ctx)
            advice = loop.before_quote(scope, ctx)
            # advice["correction"] 注入 ctx["commercial"]["flywheel_correction"]

        Args:
            scope_or_ctx: TenantScope 或 Context dict (自动解析租户)
            ctx: Context dict (若第一参已是 scope 则必传)
        """
        if isinstance(scope_or_ctx, TenantScope):
            scope = scope_or_ctx
            if ctx is None:
                raise ValueError("scope 模式必须传 ctx")
        else:
            ctx = scope_or_ctx
            scope = resolve_tenant(ctx)

        recall_result = self.recall.before_quote(scope, ctx)
        cm = ctx.get("commercial", {}) or {}
        engine_quote = cm.get("quote", {}) or {}
        engine_sha = engine_quote.get("_sha16") or engine_quote.get("sha16")

        correction_result = self.corrector.correct(
            engine_quote, recall_result, scope.tenant_id, engine_sha,
        )

        return {
            "scope": {"tenant_id": scope.tenant_id, "is_group": scope.is_group},
            "recall": recall_result,
            "correction": self.corrector.result_to_dict(correction_result),
            "customer_profile": self._extract_profile(ctx, recall_result),
        }

    # ============ 下半圈: 报价后 (写) ============

    def post_quote(self, scope_or_ctx: Any,
                   ctx: Optional[Dict[str, Any]] = None,
                   verification: Optional[Dict[str, Any]] = None,
                   quote: Optional[Dict[str, Any]] = None,
                   reaction: str = "pending",
                   postmortem: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """报价后: 打标 + 向量索引.

        应在 crm_memory.write_quote() 之后调用 (不阻塞主流程).
        """
        if isinstance(scope_or_ctx, TenantScope):
            scope = scope_or_ctx
            if ctx is None:
                raise ValueError("scope 模式必须传 ctx")
        else:
            ctx = scope_or_ctx
            scope = resolve_tenant(ctx)

        # 打标 (如有时间信号)
        label = self.labeler.label(
            ctx=ctx,
            quote_sent_at=ctx.get("_quote_sent_at"),
        )

        # 实际写入用打标结果覆盖传入 reaction (除非显式指定)
        actual_reaction = reaction if reaction != "pending" else label.reaction

        # 向量索引
        indexed = self.indexer.index_quote(
            scope, ctx, verification, quote, actual_reaction, postmortem,
        )

        return {
            "scope": {"tenant_id": scope.tenant_id},
            "reaction": actual_reaction,
            "label_reason": label.reason,
            "label_confidence": label.confidence,
            "indexed": indexed,
        }

    # ============ 工具 ============

    def _extract_profile(self, ctx: Dict[str, Any],
                         recall: Dict[str, Any]) -> Dict[str, Any]:
        """从 Context + 召回结果合成客户画像快照 (供 reply 个性化)."""
        cust = ctx.get("customer", {}) or {}
        sample_count = recall.get("sample_count", 0)
        band = recall.get("price_band", {})
        confidence = recall.get("confidence", 0.0)

        # 客户分层 (粗)
        if sample_count >= 20 and confidence > 0.5:
            tier = "A"
        elif sample_count >= 5:
            tier = "B"
        elif sample_count >= 1:
            tier = "C"
        else:
            tier = "D"

        return {
            "customer_id": cust.get("customer_id"),
            "name": cust.get("name"),
            "country": cust.get("country"),
            "tier": tier,
            "sample_count": sample_count,
            "price_band": band,
            "cold_start": recall.get("_cold_start", False),
        }

    def stats(self) -> Dict[str, Any]:
        """飞轮运行统计 (给 UI / 监控)."""
        collections = self.store.list_collections()
        tenant_collections = [c for c in collections if c.startswith("tenant_")]
        public_collections = [c for c in collections if not c.startswith("tenant_")]
        return {
            "backend": self.store.mode,
            "total_collections": len(collections),
            "tenant_collections": len(tenant_collections),
            "public_collections": len(public_collections),
            "collections": collections,
        }


# 单例
_global: Optional[FeedbackLoop] = None


def get_loop(**kw: Any) -> FeedbackLoop:
    global _global
    if _global is None:
        _global = FeedbackLoop(**kw)
    return _global


def reset_global() -> None:
    global _global
    _global = None
