"""orchestrator.py — v2.3.0 供应商流水线编排器（端到端串接）。

流程：PENDING → DESENSITIZED → MATCHED → QUOTED → SELECTED → PO_SENT → CONFIRMED

契约：
  - 必须先 desensitize 才 matcher；任何状态机非法转移抛 IllegalTransitionError
  - 默认 supplier_inbox=MockInbox（数据不出车间）；IMAPInbox 必须 enabled=True
  - 选最高分 + confidence > 0 的供应商；若无返回空
  - 持久化每一步到 data/supplier_pipelines/{context_id}.json（原子写）

调用方式：
  result = run_supplier_pipeline(context_id, customer, rfq, files, ...)
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from supplier_module.desensitize import DesensitizeRequest, desensitize
from supplier_module.matcher import match_top_n
from supplier_module.po_generator import generate_po
from supplier_module.state_machine import (
    State, SupplierPipeline, save_pipeline, load_pipeline, IllegalTransitionError,
)
from supplier_module.supplier_db import (
    init_suppliers_db, seed_default_suppliers, list_suppliers, DB_SCHEMA_VERSION,
)
from supplier_module.supplier_inbox import MockInbox, SupplierInbox
from services.commercial import compute_outsource_markup


@dataclass
class PipelineResult:
    context_id: str
    final_state: State
    matched: List[Tuple[float, Dict[str, Any]]] = field(default_factory=list)
    quotes: List[Dict[str, Any]] = field(default_factory=list)
    selected: Optional[Dict[str, Any]] = None
    po: Optional[Dict[str, Any]] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    failed: bool = False
    error: Optional[str] = None


def _default_db_path(workspace: Optional[Path] = None) -> Path:
    if workspace is None:
        workspace = Path(__file__).resolve().parent.parent
    return workspace / "data" / "suppliers.sqlite3"


def _default_pipeline_dir(workspace: Optional[Path] = None) -> Path:
    if workspace is None:
        workspace = Path(__file__).resolve().parent.parent
    d = workspace / "data" / "supplier_pipelines"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_db(db_path: Path) -> Path:
    init_suppliers_db(db_path)
    seed_default_suppliers(db_path)
    return db_path


def _select_best(quotes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """在已报价的供应商中选最佳：confidence > 0 + 价格不为 0；按 confidence desc、price asc。"""
    valid = [q for q in quotes if q.get("unit_price_cny", 0) > 0]
    if not valid:
        return None
    valid.sort(key=lambda q: (-float(q.get("confidence", 0)),
                                float(q.get("unit_price_cny", 0))))
    return valid[0]


def run_supplier_pipeline(
    context_id: str,
    customer: Dict[str, Any],
    rfq: Dict[str, Any],
    files: Optional[List[Tuple[str, bytes, str]]] = None,
    *,
    workspace: Optional[Path] = None,
    inbox: Optional[SupplierInbox] = None,
    markup_pct: float = 0.0,
    top_n: int = 3,
) -> PipelineResult:
    """端到端跑一条供应商流水线。失败用 PipelineResult.failed=True 表达（不抛）。"""
    workspace = workspace or Path(__file__).resolve().parent.parent
    db_path = _ensure_db(_default_db_path(workspace))
    pipe_dir = _default_pipeline_dir(workspace)

    pipeline = SupplierPipeline(context_id=context_id)
    result = PipelineResult(context_id=context_id, final_state=State.PENDING)

    try:
        # 1. desensitize
        req = DesensitizeRequest(context_id=context_id, customer=customer, files=files or [])
        pkg = desensitize(req)
        pipeline.payload["desensitize"] = {
            "customer_fingerprint": pkg.customer_fingerprint,
            "redacted_fields": pkg.redacted_fields,
            "manifest": pkg.manifest,
        }
        pipeline.transition(State.DESENSITIZED)
        save_pipeline(pipeline, pipe_dir / f"{context_id}.json")

        # 2. match
        candidates = list_suppliers(db_path)
        rfq_for_match = {
            "material": rfq.get("material"),
            "processes": rfq.get("processes") or [rfq.get("process")] if rfq.get("process") else [],
            "quantity": rfq.get("quantity"),
            "promised_lead_time_days": rfq.get("promised_lead_time_days"),
            "tolerance_grade": rfq.get("tolerance_grade"),
            "destination_region": rfq.get("destination_region"),
        }
        matched = match_top_n(rfq_for_match, candidates, top_n=top_n)
        result.matched = matched
        pipeline.payload["matched"] = [
            {"supplier_id": s["id"], "score": sc, "name": s["name"]}
            for sc, s in matched
        ]
        pipeline.transition(State.MATCHED)
        save_pipeline(pipeline, pipe_dir / f"{context_id}.json")

        # 3. fetch quotes (mock 默认)
        inbox = inbox or MockInbox(fallback_unit_price=0.0)
        supplier_ids = [s["id"] for _, s in matched]
        sq_list = inbox.fetch_quotes(pipeline_id=context_id, supplier_ids=supplier_ids)
        # 把 quote 合并回 supplier
        quotes_by_id = {q.supplier_id: q.to_dict() for q in sq_list}
        for sc, s in matched:
            q = quotes_by_id.get(s["id"], {"supplier_id": s["id"], "unit_price_cny": 0.0})
            result.quotes.append({**q, "score": sc, "supplier_name": s["name"]})
        pipeline.payload["quotes"] = result.quotes
        pipeline.transition(State.QUOTED)
        save_pipeline(pipeline, pipe_dir / f"{context_id}.json")

        # 4. select
        best_quote = _select_best(result.quotes)
        if best_quote is None:
            raise ValueError("no valid quote (all zero / no response)")
        best_sid = int(best_quote["supplier_id"])
        selected_supplier = next((s for _, s in matched if s["id"] == best_sid), None)
        if selected_supplier is None:
            raise ValueError(f"selected supplier id={best_sid} not in matched list")
        result.selected = {**best_quote, "supplier": selected_supplier}
        pipeline.payload["selected"] = result.selected
        pipeline.transition(State.SELECTED)
        save_pipeline(pipeline, pipe_dir / f"{context_id}.json")

        # 5. generate PO
        po = generate_po(
            context_id=context_id,
            customer=customer,
            rfq=rfq,
            supplier=selected_supplier,
            quote=best_quote,
            markup_pct=markup_pct,
        )
        result.po = po.to_dict()
        pipeline.payload["po"] = {"context_id": po.context_id,
                                  "supplier_id": po.supplier_id,
                                  "unit_price_cny": po.unit_price_cny,
                                  "total_cny": po.total_cny,
                                  "lead_time_days": po.lead_time_days,
                                  "markup_pct": po.markup_pct,
                                  "sell_price_cny": po.sell_price_cny}
        pipeline.transition(State.PO_SENT)
        save_pipeline(pipeline, pipe_dir / f"{context_id}.json")

        # 6. confirm (mock 模式默认立即确认；真实场景等供应商回执)
        pipeline.transition(State.CONFIRMED)
        save_pipeline(pipeline, pipe_dir / f"{context_id}.json")

        result.final_state = pipeline.state
        result.history = pipeline.history
        result.artifacts = {
            "pipeline_json": str(pipe_dir / f"{context_id}.json"),
            "desensitize_zip_len": len(pkg.zip_bytes),
        }
        return result

    except (IllegalTransitionError, ValueError, KeyError) as e:
        try:
            pipeline.transition(State.FAILED)
        except IllegalTransitionError:
            pass
        save_pipeline(pipeline, pipe_dir / f"{context_id}.json")
        result.final_state = pipeline.state
        result.failed = True
        result.error = f"{type(e).__name__}: {e}"
        result.history = pipeline.history
        return result


def load_pipeline_result(context_id: str,
                          workspace: Optional[Path] = None) -> Optional[PipelineResult]:
    """从磁盘加载一条已完成的流水线（用于审计/复盘）。"""
    workspace = workspace or Path(__file__).resolve().parent.parent
    path = _default_pipeline_dir(workspace) / f"{context_id}.json"
    if not path.exists():
        return None
    p = load_pipeline(path)
    return PipelineResult(
        context_id=p.context_id,
        final_state=p.state,
        history=p.history,
        artifacts=p.payload,
    )