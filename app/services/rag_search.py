"""services.rag_search — RAG 接入点 (直接调用本地 ragflow 服务, 替代薄封装 services/rag.py).

ragflow 是项目 tools/ragflow/ 内嵌的工业级 RAG 引擎 (Docker 部署).

铁律:
  - 不可达时 fallback 到内置 mock KB, 不静默冒充
  - Hybrid Search (向量 + 关键词), 支持命名实体识别
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

DEFAULT_RAGFLOW_URL = os.environ.get("RAGFLOW_URL", "http://127.0.0.1:9380")
DEFAULT_TIMEOUT_S = 10
DEFAULT_DATASET = os.environ.get("RAGFLOW_DATASET", "industry_experience")


def health(base_url: str = DEFAULT_RAGFLOW_URL, timeout_s: float = 3.0) -> bool:
    """检查本地 ragflow 服务."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/v1/health", timeout=timeout_s) as r:
            return r.status == 200
    except Exception:
        return False


def search(query: str, top_k: int = 4, dataset: str = DEFAULT_DATASET,
           base_url: str = DEFAULT_RAGFLOW_URL, timeout_s: float = DEFAULT_TIMEOUT_S,
           **filters: Any) -> Dict[str, Any]:
    """调本地 ragflow 检索.

    输出: {hits: [{case_id, title, snippet, score, source}], mock: bool, _source}
    """
    if not health(base_url, timeout_s=2.0):
        # Fallback: 内置 mock KB
        log.warning("[rag_search] ragflow 不可达, 用内置 mock KB")
        return _mock_search(query, top_k)

    payload = json.dumps({
        "query": query, "top_k": top_k, "dataset": dataset,
        "filters": filters, "method": "hybrid",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(f"{base_url}/api/v1/search",
                                    data=payload,
                                    headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read())
            return {
                "hits": data.get("hits", []),
                "mock": False,
                "_source": f"ragflow@{base_url}",
            }
    except Exception as e:
        log.warning("[rag_search] HTTP 失败, fallback mock: %r", e)
        return _mock_search(query, top_k)


def _mock_search(query: str, top_k: int) -> Dict[str, Any]:
    """离线兜底 — 唯一内置案例库在 services.rag._FALLBACK_CASES (E1 #34 收敛双库)。"""
    from services.rag import _FALLBACK_CASES
    hits = [c for c in _FALLBACK_CASES
            if any(tok in query for tok in c["topic"].split())] or _FALLBACK_CASES[:top_k]
    return {"hits": [{"case_id": c["case_id"], "title": c["topic"],
                      "snippet": c["note"], "score": 0.9}
                     for c in hits[:top_k]],
            "mock": True, "_source": "builtin-kb-fallback(services.rag)"}


def ingest_document(doc_path: str, dataset: str = DEFAULT_DATASET,
                   base_url: str = DEFAULT_RAGFLOW_URL) -> bool:
    """上传文档到 ragflow (管理员操作)."""
    if not health(base_url, timeout_s=2.0):
        log.warning("[rag_search] ragflow 不可达, 跳过 ingest")
        return False
    try:
        import urllib.request, mimetypes
        p = Path(doc_path)
        with open(p, "rb") as f:
            data = f.read()
        boundary = "----ragflow"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{p.name}"\r\n'
            f"Content-Type: {mimetypes.guess_type(str(p))[0] or 'application/octet-stream'}\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{base_url}/api/v1/datasets/{dataset}/documents",
                                    data=body,
                                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception as e:
        log.warning("[rag_search] ingest 失败: %r", e)
        return False
