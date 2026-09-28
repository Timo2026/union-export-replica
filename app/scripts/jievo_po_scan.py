"""jievo_po_scan.py — D2 杰沃 PO 全量 ingestion 管道 (任务 #31).

scan_po_dir: 目录内 PO-*.pdf → services.po_parser 解析 (排除 -tech-details / .zip).
write_report: 本地 JSON 报告 (data-stays-local, 报告含行项明细, 建议 gitignore).
ingest_pos_to_l2: 有价行项 → quote_history 向量 (L2 锚点); 每 PO 摘要 → ingest_docs.

铁律: 全程只读本地语料, 零网络调用; 真实数据不落仓库.
用法:
    python -m scripts.jievo_po_scan --dir "<杰沃目录>" --report data/jievo_report.json --ingest
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from services.po_parser import parse_po_text
from services.rag_layers import QUOTES_COLLECTION


def _pdf_text(path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:                                   # pragma: no cover
        from PyPDF2 import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)


def po_files(dir_path: str) -> List[Path]:
    """目录内 PO PDF: 排除 -tech-details 与 .zip; 保留 "(1)" 重复副本."""
    return [p for p in sorted(Path(dir_path).glob("PO-*.pdf"))
            if "tech-details" not in p.name.lower() and p.suffix.lower() == ".pdf"]


def scan_po_dir(path: str,
                text_fn: Optional[Callable[[str], str]] = None
                ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    text_fn = text_fn or _pdf_text
    pos: List[Dict[str, Any]] = []
    n_priced = 0
    files = po_files(path)
    for f in files:
        try:
            po = parse_po_text(text_fn(str(f)))
        except Exception:
            po = {"po_id": None, "items": []}
        if not po.get("po_id"):
            continue
        po["file"] = f.name
        pos.append(po)
        n_priced += sum(1 for it in po["items"] if it.get("unit_price") is not None)
    stats = {
        "n_files": len(files),
        "n_po": len(pos),
        "n_items": sum(len(p["items"]) for p in pos),
        "n_priced": n_priced,
        "ok_rate": (len(pos) / len(files)) if files else 0.0,
    }
    return pos, stats


def write_report(report: Dict[str, Any], out_path: str) -> str:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(p)


def _quote_text(it: Dict[str, Any]) -> str:
    return (f"材料:{it.get('material') or ''} 表面:{it.get('surface') or ''} "
            f"公差:{it.get('tolerance') or ''} 单价:{it.get('unit_price')}")


def ingest_pos_to_l2(gw, pos: List[Dict[str, Any]],
                     customer_id: str = "JIEVO") -> Tuple[int, int]:
    """有价行项 → QUOTES_COLLECTION (B3 quote_anchor 可用); PO 摘要 → INGEST_COLLECTION."""
    n_q = n_d = 0
    for po in pos:
        po_id = po.get("po_id") or "UNKNOWN"
        parts = []
        for it in po.get("items", []):
            if it.get("unit_price") is None:
                continue
            text = _quote_text(it)
            vec = gw.embedder.embed(text)
            gw.store.upsert(
                QUOTES_COLLECTION, f"{customer_id}:{po_id}:{it.get('article')}", vec,
                {"kind": "quote", "customer_id": customer_id,
                 "quote_id": f"{po_id}:{it.get('article')}", "text": text,
                 "material": it.get("material"), "surface": it.get("surface"),
                 "tolerance": it.get("tolerance"), "unit_price": it["unit_price"],
                 "qty": it.get("qty"), "part": it.get("part")})
            n_q += 1
            parts.append(f"{it.get('part')} {it.get('material') or ''} "
                         f"{it.get('qty')}件 ¥{it['unit_price']}")
        summary = (f"历史生产订单 {po_id}: {len(po.get('items', []))} 行项; "
                   + "; ".join(parts) + f"; 合计 {po.get('footer_total')}")
        if gw.ingest_document(f"{customer_id}:{po_id}", summary,
                              customer_id=customer_id, tags=["jievo-po"]).get("ok"):
            n_d += 1
    return n_q, n_d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="杰沃 PO PDF 目录")
    ap.add_argument("--report", default="data/jievo_po_report.json")
    ap.add_argument("--ingest", action="store_true",
                    help="同时灌入 L2 向量库 (使用 settings.vector_backend)")
    ap.add_argument("--customer", default="JIEVO")
    args = ap.parse_args()

    pos, stats = scan_po_dir(args.dir)
    write_report({"source": str(args.dir), "stats": stats, "pos": pos}, args.report)
    print(f"[jievo] n_files={stats['n_files']} n_po={stats['n_po']} "
          f"n_items={stats['n_items']} n_priced={stats['n_priced']} "
          f"ok_rate={stats['ok_rate']:.2%} report={args.report}")
    if args.ingest:
        from bootstrap import build_controller
        gw = build_controller().rag_gateway
        if gw is None:
            print("[jievo] rag_gateway 不可用, 跳过 ingest")
            return 1
        n_q, n_d = ingest_pos_to_l2(gw, pos, customer_id=args.customer)
        print(f"[jievo] ingested quotes={n_q} docs={n_d} backend={gw.store.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
