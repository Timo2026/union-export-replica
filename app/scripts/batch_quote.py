"""batch_quote.py — D3 400+常规机加工件 BOM 批量报价管道 (任务 #32).

bom_rows: BOM xlsx/csv → 结构化行 (物料编码/名称/规格→材料+表面/数量; 单价列为空=待报价).
quote_bom: 逐行合成 RFQ 文本喂黄金链 ctrl.run; 目录内 `<code>-*.STEP` 存在则挂 step_facts
           走 OCP 几何驱动定价 (确定性引擎出单价).
铁律: data-stays-local — 只读本机语料, 报告落 data/ (gitignored), 零网络.
用法:
    python -m scripts.batch_quote --bom "<BOM.xlsx>" --assets "<400+常规机加工件目录>" \
        --out data/batch_quote_report.json [--limit N]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import services.file_intake as fi

_STEP_EXT = (".step", ".stp")


def parse_spec(spec: Optional[str]) -> Dict[str, Any]:
    parts = [p.strip() for p in (spec or "").split("+") if p.strip()]
    return {"material": parts[0] if parts else "", "finishes": parts[1:]}


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _price(v: Any) -> Optional[float]:
    try:
        f = float(str(v).replace(",", ""))
        return f
    except (TypeError, ValueError):
        return None


def bom_rows(path: str) -> List[Dict[str, Any]]:
    r = fi.parse_excel(path, max_rows=10 ** 6)
    rows = r.get("rows") or []
    if not rows:
        return []
    header = [str(h or "").strip() for h in rows[0]]
    out = []
    for raw in rows[1:]:
        d = dict(zip(header, list(raw) + [None] * max(0, len(header) - len(raw))))
        code = str(d.get("物料编码") or "").strip()
        if not code or code.lower() == "none":
            continue
        spec = parse_spec(str(d.get("规格") or ""))
        out.append({"idx": _int(d.get("序号")), "code": code,
                    "name": str(d.get("名称") or ""), "spec": str(d.get("规格") or ""),
                    "material": spec["material"], "finishes": spec["finishes"],
                    "qty": _int(d.get("数量"), 1), "unit_price": _price(d.get("单价")),
                    "note": d.get("备注")})
    return out


def find_step(assets_dir: str, code: str) -> Optional[str]:
    for p in sorted(Path(assets_dir).rglob(f"{code}-*")):
        if p.suffix.lower() in _STEP_EXT:
            return str(p)
    return None


def build_rfq_text(row: Dict[str, Any]) -> str:
    finishes = "/".join(row["finishes"]) or "as-machined"
    return (f"quote {row['qty']} pcs {row['material']} parts, "
            f"零件: {row['name']}, 材料: {row['material']}, 表面处理: {finishes}")


def quote_bom(rows: List[Dict[str, Any]], ctrl, assets_dir: Optional[str] = None,
              step_parser: Optional[Callable[..., Dict[str, Any]]] = None,
              customer_name: str = "批量询价",
              customer_id: Optional[str] = None) -> List[Dict[str, Any]]:
    step_parser = step_parser or (lambda p, timo, material="6061",
                                  with_features=True: fi.parse_step(p, timo, material, with_features))
    customer = {"name": customer_name}
    if customer_id:
        customer["customer_id"] = customer_id
    out = []
    for row in rows:
        step_path = find_step(assets_dir, row["code"]) if assets_dir else None
        step_facts = None
        if step_path:
            step_facts = step_parser(step_path, getattr(ctrl, "timo", None),
                                     material=row["material"] or "6061")
        res = ctrl.run(email_text=build_rfq_text(row),
                       customer=customer,
                       step_facts=step_facts, context_id=f"BOM-{row['code']}")
        q = res.get("quote") or {}
        unit = q.get("unit_price")
        out.append({**{k: row[k] for k in ("idx", "code", "name", "qty", "material")},
                    "finishes": row["finishes"], "has_step": bool(step_path),
                    "state": res.get("state"),
                    "verification_status": res.get("verification_status"),
                    "unit_price": unit,
                    "total_price": round(unit * row["qty"], 2) if unit is not None else None,
                    "context_id": f"BOM-{row['code']}"})
    return out


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    priced = [r for r in results if r["unit_price"] is not None]
    return {"n_rows": len(results), "n_quoted": len(priced),
            "n_with_step": sum(1 for r in results if r["has_step"]),
            "quote_rate": round(len(priced) / len(results), 4) if results else 0.0,
            "sum_total": round(sum(r["total_price"] or 0 for r in results), 2)}


def write_report(report: Dict[str, Any], out_path: str) -> str:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bom", required=True)
    ap.add_argument("--assets", default=None, help="STEP/PDF 资产目录 (按物料编码前缀匹配)")
    ap.add_argument("--out", default="data/batch_quote_report.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--customer-id", default=None, help="租户 ID (L2 锚点过滤, 如 JIEVO)")
    args = ap.parse_args()

    rows = bom_rows(args.bom)
    if args.limit:
        rows = rows[:args.limit]
    from bootstrap import build_controller
    results = quote_bom(rows, build_controller(), assets_dir=args.assets,
                        customer_id=args.customer_id)
    stats = summarize(results)
    write_report({"bom": str(args.bom), "assets": args.assets,
                  "stats": stats, "results": results}, args.out)
    print(f"[batch] {json.dumps(stats, ensure_ascii=False)} report={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
