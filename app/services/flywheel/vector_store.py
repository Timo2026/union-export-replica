"""flywheel.vector_store — 向量库抽象 (Qdrant local embedded + 零依赖兜底).

决策锁定 (2026-09-19): Qdrant 独立服务
  - Dev/QA: qdrant-client embedded local mode (零运维, 单进程)
  - Prod:   docker-compose qdrant 服务 (生产级)

降级策略:
  - qdrant-client 不可用 → InMemoryVectorStore (dict + 余弦相似, 仅 dev)
  - Embedding 服务不可用 → HashEmbedder (确定性伪向量)

租户隔离:
  - 私有集合: payload.tenant_id 过滤
  - 公共集合 (kb_*): 不分租户
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# 尝试导入 Qdrant
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance, VectorParams, PointStruct,
        Filter, FieldCondition, MatchValue,
    )
    _HAS_QDRANT = True
except Exception:
    _HAS_QDRANT = False
    QdrantClient = None  # type: ignore

DEFAULT_DIM = 64  # HashEmbedder 维度 (dev 兜底)
DEFAULT_DIST = "Cosine"


class HashEmbedder:
    """零依赖确定性伪嵌入器 (dev/测试兜底).

    生产应替换为 Qwen3-Embedding 或 sentence-transformers.
    特性: 同样输入 → 同样向量; 不同输入 → 不同向量; 余弦相似有效.
    """

    def __init__(self, dim: int = DEFAULT_DIM):
        self.dim = dim

    def embed(self, text: str) -> List[float]:
        if not text:
            return [0.0] * self.dim
        # 确定性: sha256 → 均匀分桶 → 归一化
        h = hashlib.sha256(text.encode("utf-8")).digest()
        vec = [((h[i % len(h)] * (i + 1)) % 997) / 997.0 for i in range(self.dim)]
        # 词袋信号: 提升相似文本的余弦相似
        tokens = set(text.lower().replace(",", " ").replace(".", " ").split())
        for tok in tokens:
            idx = int(hashlib.md5(tok.encode()).hexdigest()[:4], 16) % self.dim
            vec[idx] += 1.0
        # 归一化 (L2)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class InMemoryVectorStore:
    """零依赖内存向量库 (dict + 余弦相似). 仅 dev/测试."""

    def __init__(self, dim: int = DEFAULT_DIM):
        self._lock = threading.Lock()
        self._collections: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._dim = dim

    def ensure_collection(self, collection: str, dim: int = None) -> None:
        with self._lock:
            self._collections.setdefault(collection, {})

    def upsert(self, collection: str, point_id: str,
               vector: List[float], payload: Dict[str, Any]) -> bool:
        with self._lock:
            self._collections.setdefault(collection, {})
            self._collections[collection][point_id] = {
                "id": point_id, "vector": vector, "payload": payload,
            }
            return True

    def search(self, collection: str, query_vec: List[float],
               limit: int = 5,
               tenant_filter: Optional[str] = None,
               extra_filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        with self._lock:
            points = self._collections.get(collection, {})
            scored = []
            for p in points.values():
                payload = p.get("payload", {})
                # 租户过滤
                if tenant_filter is not None and payload.get("tenant_id") != tenant_filter:
                    continue
                # 额外过滤 (反应类型等)
                if extra_filter:
                    skip = False
                    for k, allowed in extra_filter.items():
                        if isinstance(allowed, list):
                            if payload.get(k) not in allowed:
                                skip = True
                                break
                        elif payload.get(k) != allowed:
                            skip = True
                            break
                    if skip:
                        continue
                score = _cosine(query_vec, p["vector"])
                scored.append((score, p))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                {"id": p["id"], "score": float(s), "payload": p["payload"]}
                for s, p in scored[:limit]
            ]

    def delete(self, collection: str, point_id: str) -> bool:
        with self._lock:
            points = self._collections.get(collection, {})
            return points.pop(point_id, None) is not None

    def list_points(self, collection: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(p) for p in self._collections.get(collection, {}).values()]

    def delete_collection(self, collection: str) -> int:
        with self._lock:
            n = len(self._collections.get(collection, {}))
            self._collections.pop(collection, None)
            return n

    def count(self, collection: str) -> int:
        with self._lock:
            return len(self._collections.get(collection, {}))

    def list_collections(self) -> List[str]:
        with self._lock:
            return list(self._collections.keys())


class JsonFileBackend(InMemoryVectorStore):
    """内存 + JSON 文件落盘 (零依赖重启持久). 写操作即时原子保存。"""

    def __init__(self, dim: int = DEFAULT_DIM, path: Optional[str] = None):
        super().__init__(dim)
        self.path = path or os.environ.get("UEA_VECTOR_DB_PATH", "data/rag_vectors.json")
        self._load()

    def _load(self) -> None:
        p = Path(self.path)
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            with self._lock:
                self._collections = data
        except Exception as e:
            log.warning("[vector_store] file 加载失败, 从空库开始: %r", e)

    def _save(self) -> None:
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with self._lock:
            tmp.write_text(json.dumps(self._collections, ensure_ascii=False),
                           encoding="utf-8")
        tmp.replace(p)

    def upsert(self, collection, point_id, vector, payload) -> bool:
        ok = super().upsert(collection, point_id, vector, payload)
        self._save()
        return ok

    def delete(self, collection, point_id) -> bool:
        ok = super().delete(collection, point_id)
        if ok:
            self._save()
        return ok

    def delete_collection(self, collection) -> int:
        n = super().delete_collection(collection)
        if n:
            self._save()
        return n


class QdrantBackend:
    """Qdrant local embedded 后端 (生产可切 server 模式)."""

    def __init__(self, path: str = "data/.qdrant", host: Optional[str] = None,
                 port: Optional[int] = None, dim: int = DEFAULT_DIM):
        self.dim = dim
        if host and port:
            self._client = QdrantClient(host=host, port=port)
        else:
            os.makedirs(path, exist_ok=True)
            self._client = QdrantClient(path=path)
        self._lock = threading.Lock()

    def ensure_collection(self, collection: str, dim: int = None) -> None:
        d = dim or self.dim
        try:
            self._client.get_collection(collection)
        except Exception:
            self._client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=d, distance=Distance.COSINE),
            )

    def upsert(self, collection: str, point_id: str,
               vector: List[float], payload: Dict[str, Any]) -> bool:
        self.ensure_collection(collection, len(vector))
        pid = _stable_id(point_id)
        self._client.upsert(
            collection_name=collection,
            points=[PointStruct(id=pid, vector=vector, payload=payload)],
        )
        return True

    def search(self, collection: str, query_vec: List[float],
               limit: int = 5, tenant_filter: Optional[str] = None,
               extra_filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        self.ensure_collection(collection, len(query_vec))
        must = []
        if tenant_filter is not None:
            must.append(FieldCondition(key="tenant_id",
                                       match=MatchValue(value=tenant_filter)))
        if extra_filter:
            for k, allowed in extra_filter.items():
                vals = allowed if isinstance(allowed, list) else [allowed]
                for v in vals:
                    must.append(FieldCondition(key=k, match=MatchValue(value=v)))
        flt = Filter(must=must) if must else None
        hits = self._client.search(
            collection_name=collection, query_vector=query_vec,
            limit=limit, query_filter=flt,
        )
        return [{"id": str(h.id), "score": float(h.score), "payload": h.payload or {}} for h in hits]

    def delete(self, collection: str, point_id: str) -> bool:
        try:
            self._client.delete(collection_name=collection,
                                points_selector=[_stable_id(point_id)], wait=True)
            return True
        except Exception:
            return False

    def list_points(self, collection: str) -> List[Dict[str, Any]]:
        try:
            out, offset = [], None
            while True:
                pts, offset = self._client.scroll(collection_name=collection,
                                                  limit=256, offset=offset,
                                                  with_payload=True, with_vectors=True)
                out.extend({"id": str(p.id), "vector": list(p.vector or []),
                            "payload": p.payload or {}} for p in pts)
                if not offset or not pts:
                    break
            return out
        except Exception:
            return []

    def delete_collection(self, collection: str) -> int:
        try:
            self._client.delete_collection(collection)
            return 1
        except Exception:
            return 0

    def count(self, collection: str) -> int:
        try:
            return self._client.count(collection_name=collection).count
        except Exception:
            return 0

    def list_collections(self) -> List[str]:
        try:
            return [c.name for c in self._client.get_collections().collections]
        except Exception:
            return []


def _stable_id(text_id: str) -> str:
    """Qdrant 要求 UUID 或 uint; 用 hash 映射."""
    h = hashlib.md5(text_id.encode("utf-8")).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


class VectorStore:
    """统一向量库门面: Qdrant 优先, 内存兜底.

    用法:
        store = get_vector_store()
        store.upsert(tenant_coll, "RFQ-001", vector, payload)
        hits = store.search(tenant_coll, query_vec, tenant_filter="CUST-X")
    """

    def __init__(self, backend: Optional[str] = None, dim: int = DEFAULT_DIM,
                 embedder: Optional[HashEmbedder] = None):
        self.dim = dim
        self.embedder = embedder or HashEmbedder(dim)
        backend = backend or os.environ.get("UEA_VECTOR_BACKEND", "auto")
        if backend == "qdrant" and _HAS_QDRANT:
            try:
                self._backend: Any = QdrantBackend(dim=dim)
                self._mode = "qdrant"
                log.info("[vector_store] backend=qdrant")
            except Exception as e:
                log.warning("[vector_store] qdrant 初始化失败, 降级内存: %r", e)
                self._backend = InMemoryVectorStore(dim)
                self._mode = "memory"
        elif backend == "memory":
            self._backend = InMemoryVectorStore(dim)
            self._mode = "memory"
        elif backend == "file":
            self._backend = JsonFileBackend(dim)
            self._mode = "file"
            log.info("[vector_store] backend=file (JSON 落盘持久)")
        else:  # auto
            if _HAS_QDRANT:
                try:
                    self._backend = QdrantBackend(dim=dim)
                    self._mode = "qdrant"
                    log.info("[vector_store] backend=qdrant (auto)")
                except Exception:
                    self._backend = InMemoryVectorStore(dim)
                    self._mode = "memory"
            else:
                self._backend = InMemoryVectorStore(dim)
                self._mode = "memory"
                log.info("[vector_store] backend=memory (qdrant-client 未安装)")

    @property
    def mode(self) -> str:
        return self._mode

    def embed(self, text: str) -> List[float]:
        return self.embedder.embed(text)

    def ensure_collection(self, collection: str) -> None:
        self._backend.ensure_collection(collection, self.dim)

    def upsert(self, collection: str, point_id: str, text_or_vec: Any,
               payload: Dict[str, Any]) -> bool:
        vec = text_or_vec if isinstance(text_or_vec, list) else self.embed(text_or_vec)
        self.ensure_collection(collection)
        payload = {**payload, "_indexed_at": time.time()}
        return self._backend.upsert(collection, point_id, vec, payload)

    def search(self, collection: str, query: Any, limit: int = 5,
               tenant_filter: Optional[str] = None,
               extra_filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        qv = query if isinstance(query, list) else self.embed(query)
        return self._backend.search(collection, qv, limit, tenant_filter, extra_filter)

    def delete(self, collection: str, point_id: str) -> bool:
        return self._backend.delete(collection, point_id)

    def list_points(self, collection: str) -> List[Dict[str, Any]]:
        return self._backend.list_points(collection)

    def delete_collection(self, collection: str) -> int:
        return self._backend.delete_collection(collection)

    def count(self, collection: str) -> int:
        return self._backend.count(collection)

    def list_collections(self) -> List[str]:
        return self._backend.list_collections()

    def reset_all(self) -> None:
        """清空所有集合 (测试用)."""
        for coll in self.list_collections():
            self.delete_collection(coll)


_global: Optional[VectorStore] = None


def get_vector_store(**kw: Any) -> VectorStore:
    global _global
    if _global is None:
        _global = VectorStore(**kw)
    return _global


def reset_global() -> None:
    global _global
    _global = None
