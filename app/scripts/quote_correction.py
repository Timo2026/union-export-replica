"""quote_correction.py — D4 分级自动矫正接线 + PO 真值精度验证 (任务 #33).

接线: L2 历史锚点 (杰沃 PO → quote_history) 召回 → recall dict →
      v6.2 services/flywheel/price_corrector.PriceCorrector (cold±5%/warm±10%/hot±15% + 审计链).
精度: leave-one-out — 评估 PO 自身行项从召回中排除 (exclude_prefix=po_id), 防真值泄漏;
      同一 STEP 走引擎出 base_price, MAPE 前/后对比落 data/ 报告 (gitignored, 不上云).
铁律: 只调修正系数, 不改 Timo 确定性数字; data-stays-local, 零网络.
用法:
    python -m scripts.quote_correction --jievo-dir "<杰沃/杰沃>" --pos 8 \
        --out data/quote_accuracy_report.json
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import services.file_intake as fi
from services.flywheel.price_corrector import PriceCorrector
from services.rag_layers import QUOTES_COLLECTION


def recall_from_l2(gw, query: str, customer_id: Optional[str] = None,
                   limit: int = 8,
                   exclude_prefix: Optional[str] = None) -> Dict[str, Any]:
    """L2 向量召回 → PriceCorrector.recall 契约 (similar_won + price_band + tier 样本数)."""
    hits = gw.list_similar_quotes(query, customer_id=customer_id, limit=limit)
    if exclude_prefix:
        hits = [h for h in hits
                if not str(h.get("payload", {}).get("quote_id", "")).startswith(exclude_prefix)]
    hits = [h for h in hits if float(h.get("payload", {}).get("unit_price") or 0) > 0]
    points: List[Dict[str, Any]] = []
    try:
        points = gw.store.list_points(QUOTES_COLLECTION)
    except Exception:
        points = []
    sample_count = sum(1 for p in points
                       if p.get("payload", {}).get("customer_id") == customer_id) \
        if customer_id else len(points)
    prices = sorted(float(h["payload"]["unit_price"]) for h in hits
                    if h.get("payload", {}).get("unit_price") is not None)
    band = {}
    if prices:
        def pct(q: float) -> float:
            return prices[max(0, math.ceil(q * len(prices)) - 1)]
        band = {"p25": pct(0.25), "p50": pct(0.5), "p75": pct(0.75)}
    similar_won = [{"score": h.get("score"),
                    "payload": {"context_id": h["payload"].get("quote_id"),
                                "final_price": h["payload"].get("unit_price"),
                                "material": h["payload"].get("material"),
                                "surface": h["payload"].get("surface")}}
                   for h in hits if h.get("payload", {}).get("unit_price") is not None]
    return {"similar_won": similar_won, "similar_lost": [],
            "price_band": band, "sample_count": sample_count,
            "confidence": min(1.0, len(prices) / 5.0) if prices else 0.0}


def correct_quote_with_l2(gw, corrector: PriceCorrector,
                          engine_quote: Dict[str, Any], query: str,
                          customer_id: str,
                          exclude_prefix: Optional[str] = None) -> Optional[Dict[str, Any]]:
    recall = recall_from_l2(gw, query, customer_id, exclude_prefix=exclude_prefix)
    if not recall["similar_won"]:
        return None
    r = corrector.correct(engine_quote, recall, tenant_id=customer_id)
    out = corrector.result_to_dict(r)
    out["anchor_prices"] = [w["payload"]["final_price"] for w in recall["similar_won"]]
    return out


def mape(rows: List[Dict[str, Any]], pred_key: str = "pred",
         truth_key: str = "truth") -> Optional[float]:
    vals = [abs(r[pred_key] - r[truth_key]) / r[truth_key] * 100.0
            for r in rows if r.get(pred_key) and r.get(truth_key)]
    return round(sum(vals) / len(vals), 2) if vals else None


def match_step(extract_dir: str, part: str) -> Optional[str]:
    for p in sorted(Path(extract_dir).rglob("*")):
        if p.suffix.lower() in (".stp", ".step") and p.name.lower().endswith(part.lower()):
            return str(p)
    return None


def dedupe_pos(pos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for p in pos:
        pid = p.get("po_id")
        if pid not in seen:
            seen.add(pid)
            out.append(p)
    return out


def evaluate_po(ctrl, gw, po: Dict[str, Any], drawings_zip: str, extract_dir: str,
                customer_id: str = "JIEVO",
                corrector: Optional[PriceCorrector] = None) -> List[Dict[str, Any]]:
    corrector = corrector or PriceCorrector()
    # 内核桥子进程 cwd=engine_src, 相对路径必失败 (OCP 三解析器全崩后段错误退出)
    drawings_zip = str(Path(drawings_zip).resolve())
    extract_dir = str(Path(extract_dir).resolve())
    fi.extract_zip(drawings_zip, extract_dir)
    po_id = po.get("po_id") or "UNKNOWN"
    rows = []
    for it in po.get("items", []):
        if it.get("unit_price") is None or not it.get("part"):
            continue
        step = match_step(extract_dir, it["part"])
        if not step:
            continue
        material = (it.get("material") or "6061")
        email_text = (f"quote {it.get('qty') or 1} pcs {material} parts, "
                      f"零件: {it['part']}, 表面处理: {it.get('surface') or 'as-machined'}")
        row = {"po_id": po_id, "article": it.get("article"), "part": it["part"],
               "qty": it.get("qty"), "material": material,
               "surface": it.get("surface"),
               "po_price": it["unit_price"], "engine_price": None,
               "state": None, "correction": None}
        try:
            facts = fi.parse_step(step, ctrl.timo, material=material, with_features=True)
            res = ctrl.run(email_text=email_text, customer={"name": customer_id},
                           step_facts=facts, context_id=f"EVAL-{po_id}-{it.get('article')}")
        except Exception as e:                               # 坏件/bridge 崩溃不炸整轮
            row["error"] = repr(e)[:300]
            rows.append(row)
            continue
        q = res.get("quote") or {}
        engine_price = q.get("unit_price")
        row.update({"state": res.get("state"), "engine_price": engine_price})
        if engine_price:
            query = f"{material} {it.get('surface') or ''}"
            row["correction"] = correct_quote_with_l2(
                gw, corrector, {"unit_price": engine_price,
                                "margin_pct": res.get("margin_pct")},
                query, customer_id, exclude_prefix=f"{po_id}")
        rows.append(row)
    return rows


def build_accuracy_report(all_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    pairs = [{"truth": r["po_price"], "pred": r["engine_price"]} for r in all_rows]
    corr = [{"truth": r["po_price"], "pred": r["correction"]["corrected_price"]}
            for r in all_rows if r.get("correction")]
    return {"n_rows": len(all_rows), "n_corrected": len(corr),
            "mape_engine_pct": mape(pairs),
            "mape_corrected_pct": mape(corr),
            "mape_within_cap_pct": mape(
                [{"truth": r["po_price"],
                  "pred": r["engine_price"] * (1 + max(-0.15, min(0.15,
                          (r["correction"]["corrected_price"] / r["engine_price"]) - 1)))}
                 for r in all_rows if r.get("correction")])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jievo-dir", required=True)
    ap.add_argument("--out", default="data/quote_accuracy_report.json")
    ap.add_argument("--pos", type=int, default=8, help="评估 PO 数 (每个含图纸 zip)")
    ap.add_argument("--customer", default="JIEVO")
    args = ap.parse_args()

    from bootstrap import build_controller
    from scripts.jievo_po_scan import scan_po_dir
    ctrl = build_controller()
    gw = ctrl.rag_gateway
    if gw is None:
        print("[d4] rag_gateway 不可用")
        return 1
    pos, _stats = scan_po_dir(args.jievo_dir)
    pos = dedupe_pos(pos)                                   # "(1)" 副本同 po_id, 防 MAPE 双计
    if gw.store.count(QUOTES_COLLECTION) == 0:
        from scripts.jievo_po_scan import ingest_pos_to_l2
        ingest_pos_to_l2(gw, pos, customer_id=args.customer)
    d = Path(args.jievo_dir)
    tmp = Path(args.out).parent / "_d4_extract"
    all_rows: List[Dict[str, Any]] = []
    for po in pos:
        if len({r["po_id"] for r in all_rows}) >= args.pos:
            break
        z = d / f"{po['po_id']}-drawings.zip"
        if not z.exists():
            continue
        rows = evaluate_po(ctrl, gw, po, str(z), str(tmp / po["po_id"]),
                           customer_id=args.customer)
        all_rows.extend(rows)
        if rows:
            print(f"[d4] {po['po_id']}: {len(rows)} 行项评估完成")
    report = build_accuracy_report(all_rows)
    report["rows"] = all_rows
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[d4] n_rows={report['n_rows']} mape_engine={report['mape_engine_pct']}% "
          f"mape_corrected={report['mape_corrected_pct']}% out={p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
