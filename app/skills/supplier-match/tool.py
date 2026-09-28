"""supplier_match — 7 维打分 TopN 供应商匹配."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def run(ctx, rfq: Dict[str, Any] | None = None, top_n: int = 3, **kwargs) -> Dict[str, Any]:
    rfq = dict(rfq or ctx.scratch.get("rfq") or {})
    if not rfq:
        return {"ok": False, "skill": "supplier_match", "error": "rfq required"}
    top_n = max(1, min(int(top_n or 3), 5))
    from supplier_module.matcher import match_top_n
    from supplier_module.supplier_db import init_suppliers_db, list_suppliers, seed_default_suppliers
    root = Path(__file__).resolve().parent.parent.parent
    db = root / "data" / "suppliers.sqlite3"
    try:
        init_suppliers_db(db)
        seed_default_suppliers(db)
        try:
            candidates = list_suppliers(db)
        except TypeError:
            candidates = list_suppliers()
        matched = match_top_n(rfq, candidates, top_n=top_n)
    except Exception as e:  # noqa
        return {"ok": False, "skill": "supplier_match", "error": repr(e)}
    items = []
    for row in matched or []:
        if isinstance(row, (list, tuple)) and len(row) == 2:
            items.append({"score": row[0], "supplier": row[1]})
        else:
            items.append({"score": row.get("score") if isinstance(row, dict) else None,
                          "supplier": row})
    return {
        "ok": True,
        "skill": "supplier_match",
        "iron_rule": "deterministic",
        "top_n": top_n,
        "matched": items,
        "_source": "supplier_module.matcher.match_top_n",
    }


def _accepts_db(fn) -> bool:
    import inspect
    try:
        sig = inspect.signature(fn)
        return "db" in sig.parameters or "db_path" in sig.parameters or "path" in sig.parameters
    except (TypeError, ValueError):
        return False
