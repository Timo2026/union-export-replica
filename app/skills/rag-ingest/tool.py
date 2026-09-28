"""rag_ingest — 文档入库 / 报价索引重建 Skill (复用 services.rag_layers)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def run(ctx, action: str = "ingest_file",
        file_path: str = "",
        customer_id: str = "",
        **kwargs) -> Dict[str, Any]:
    from services.rag_layers import get_gateway
    gw = get_gateway()

    if action == "ingest_file":
        if not file_path:
            return {"ok": False, "error": "file_path 必填",
                    "skill": "rag_ingest", "iron_rule": "deterministic"}
        p = Path(file_path).resolve()          # 内核/子进程铁律: 绝对路径
        if not p.exists():
            return {"ok": False, "error": f"文件不存在: {p}",
                    "skill": "rag_ingest", "iron_rule": "deterministic"}
        res = gw.ingest_file(str(p), customer_id=customer_id or None)
        return {**res, "skill": "rag_ingest", "iron_rule": "deterministic"}

    if action == "reindex_quotes":
        n = gw.index_all_quotes()
        return {"ok": True, "reindexed": n,
                "skill": "rag_ingest", "iron_rule": "deterministic"}

    if action == "list_docs":
        docs = gw.list_ingested_docs(customer_id=customer_id or None)
        return {"ok": True, "docs": docs,
                "skill": "rag_ingest", "iron_rule": "deterministic"}

    return {"ok": False, "error": f"未知 action: {action}",
            "skill": "rag_ingest", "iron_rule": "deterministic"}
