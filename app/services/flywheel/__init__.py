"""services.flywheel — v6.2 商业飞轮 (Flywheel)

把"单笔交易精密机器"升级为"跨交易复利机器":
  - 报价数据飞轮: 报价 → 向量索引 → 相似召回 → 分级修正 → 复盘回流
  - 客户跟进飞轮: 询盘 → 报价 → 沉默检测 → 跟进 → 反馈 → 复盘
  - 三层记忆:    Fact(SQLite) + Episodic(events) + Semantic(Qdrant)
  - 双层沙箱:    tenant = customer_id (默认) / tenant = group_id (集团)

铁律兼容:
  - 铁律①: PriceCorrector 只调系数, 不改 Timo 确定性数字
  - 铁律③: tenant_id 作为 Context 强制元字段注入
  - 铁律④: similar_recall 只提供 evidence_chip, 不改数字

降级策略:
  - Qdrant 不可用 → 内存 dict + 余弦相似 (zero-dep)
  - Embedding 服务不可用 → HashEmbedder (确定性伪向量, 仅 dev)
  - 飞轮关闭 → 黄金链照常跑 (飞轮是增强层, 非阻塞)
"""
from .vector_store import VectorStore, get_vector_store
from .tenant import resolve_tenant, TenantScope
from .quote_indexer import QuoteIndexer
from .similar_recall import SimilarRecall
from .price_corrector import PriceCorrector, CorrectionTier
from .reaction_labeler import ReactionLabeler, Reaction
from .feedback_loop import FeedbackLoop

__all__ = [
    "VectorStore", "get_vector_store",
    "resolve_tenant", "TenantScope",
    "QuoteIndexer", "SimilarRecall",
    "PriceCorrector", "CorrectionTier",
    "ReactionLabeler", "Reaction",
    "FeedbackLoop",
]
