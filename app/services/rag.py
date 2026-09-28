"""rag.py — 历史制造经验检索 (援: 证据支撑).

优先 funasr-gui /rag/search (embedding@:1278 + SQLite FTS5 + RRF);
离线时用内置案例库兜底并显式标注 _mock, 不冒充生产检索。
"""
from __future__ import annotations

from typing import Any, Dict, List

# 内置兜底案例库 (对齐工艺禁忌矩阵, 仅离线证据支撑用)
_FALLBACK_CASES: List[Dict[str, Any]] = [
    {"case_id": "KB-304-ANOD", "topic": "304 阳极氧化",
     "note": "304/316L 不锈钢自然钝化, 不做阳极氧化; 推荐钝化或电解抛光。"},
    {"case_id": "KB-TC4-IT5", "topic": "TC4 IT5 精密公差",
     "note": "钛合金 IT4/IT5 超常规 CNC 经济公差, 需精密磨削/慢走丝, 强制人工复核。"},
    {"case_id": "KB-AL-ZINC", "topic": "铝合金镀锌",
     "note": "6061/7075 铝合金不适合镀锌, 推荐阳极氧化或镀镍。"},
    {"case_id": "KB-6061-ANOD", "topic": "6061 阳极氧化",
     "note": "6061 阳极氧化为常规工艺, 可直接加工。"},
    # E1 #34: 自 rag_search.MOCK_KB 并入 (离线兜底唯一源, 消除双库重叠)
    {"case_id": "KB-CARBON-BLACK", "topic": "碳钢 发黑",
     "note": "发黑+油封, 盐雾试验 ≥24h。"},
    {"case_id": "KB-WHITESPOT", "topic": "M37 阀块 白斑",
     "note": "白斑 postmortem: 返工经济性 < 折价接收。"},
    {"case_id": "KB-DFM-WALL", "topic": "薄壁 装夹",
     "note": "铝合金 CNC 壁厚 ≥1.5mm, 钢铁 ≥1.0mm, 低于需复核。"},
]


class RAGEvidence:
    def __init__(self, funasr_adapter):
        self.f = funasr_adapter

    def search(self, query: str, limit: int = 3, customer_id: str = None) -> Dict[str, Any]:
        """检索历史制造经验 (援: 证据支撑).
        
        customer_id: 可选, 传递至 funasr-gui RAG 层做客户过滤。
        """
        if self.f is not None and getattr(self.f, "online", False):
            return self.f.rag_search(query, limit=limit, customer_id=customer_id)
        hits = [c for c in _FALLBACK_CASES
                if any(tok in query for tok in c["topic"].split())] or _FALLBACK_CASES[:limit]
        result = {"hits": hits[:limit], "_mock": True, "_source": "MOCK:builtin-kb"}
        if customer_id:
            result["customer_id"] = customer_id
        return result

    def ask(self, query: str, limit: int = 3, customer_id: str = None) -> Dict[str, Any]:
        """问答式检索 (支持 customer_id 过滤)。"""
        if self.f is not None and getattr(self.f, "online", False):
            return self.f.rag_ask(query, limit=limit, customer_id=customer_id)
        return {"answer": "", "sources": [], "_mock": True}
