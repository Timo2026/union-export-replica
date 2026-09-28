"""po_parser.py — 杰沃/Xometry 生产订单 (PO) PDF 文本 → 结构化行项 (任务 #30 D1).

实证格式 (pypdf 抽取, PO-C1066077-621644):
  Production Order / 生产订单  PO-C1066077-621644
  10#712422 CDS240701-A.stp            ← 行项头: <pos>#<article> <零件图号>
  Material / 材料 : 铝合金  - 6061
  Finish / 后处理 : Anodize (Black) / 阳极氧化  ( 黑色 ); 亮光
  ...
  Part Marking / 零件标记 :1 ¥ 298.94 ¥ 298.94   ← 行尾: qty 单价 总价
  Price net / 单价 :                              ← 页脚合计, 之后不再解析行项
  ¥ 550.00

原则: 纯文本解析, 不依赖网络; 解析不到的字段留 None, 不臆造。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_PO_ID_RE = re.compile(r"PO-C\d{6,7}-\d+")     # 实证: 客户代码 6/7 位均存在
_ITEM_HEAD_RE = re.compile(r"^(\d+)#(\d+)\s+(\S+)")            # pos#article part.stp
_QTY_PRICE_RE = re.compile(r"(\d+)\s*¥\s*([\d.,]+)\s*¥\s*([\d.,]+)")
_MATERIAL_RE = re.compile(r"Material\s*/\s*材料\s*:\s*(.+)")
_ALLOY_RE = re.compile(r"(\d{3,4})")
_SURFACE_RE = re.compile(r"Finish\s*/\s*后处理\s*:\s*(.+)")
_TOL_RE = re.compile(r"Tolerance/\s*公差\s*:\s*(.*)")
_FOOTER_RE = re.compile(r"Price net\s*/\s*单价")
_FOOTER_AMT_RE = re.compile(r"¥\s*([\d.,]+)")


def _num(s: str) -> Optional[float]:
    s = s.strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_po_text(text: str) -> Dict[str, Any]:
    """PO 全文 → {po_id, items:[{pos,article,part,qty,unit_price,total,
    material,surface,tolerance,notes}], footer_total}。"""
    m = _PO_ID_RE.search(text or "")
    po_id = m.group(0) if m else None

    footer_pos = _FOOTER_RE.search(text or "")
    body = text[:footer_pos.start()] if footer_pos else text
    footer_total = None
    if footer_pos:
        am = _FOOTER_AMT_RE.search(text[footer_pos.end():])
        footer_total = _num(am.group(1)) if am else None

    items: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for line in body.splitlines():
        head = _ITEM_HEAD_RE.match(line.strip())
        if head:
            cur = {"pos": int(head.group(1)), "article": head.group(2),
                   "part": head.group(3), "qty": None, "unit_price": None,
                   "total": None, "material": None, "surface": None,
                   "tolerance": None, "notes": None}
            items.append(cur)
            continue
        if cur is None:
            continue
        mm = _MATERIAL_RE.search(line)
        if mm:
            alloy = _ALLOY_RE.search(mm.group(1))
            cur["material"] = alloy.group(1) if alloy else mm.group(1).strip()
            continue
        ms = _SURFACE_RE.search(line)
        if ms:
            cur["surface"] = ms.group(1).strip()
            continue
        mt = _TOL_RE.search(line)
        if mt:
            cur["tolerance"] = mt.group(1).strip() or None
            continue
        if "客户备注" in line:
            cur["notes"] = line.split(":", 1)[-1].strip() or None
        qp = _QTY_PRICE_RE.search(line)
        if qp and cur["unit_price"] is None:
            cur["qty"] = int(qp.group(1))
            cur["unit_price"] = _num(qp.group(2))
            cur["total"] = _num(qp.group(3))
    return {"po_id": po_id, "items": items, "footer_total": footer_total}


def parse_po_file(path: str) -> Dict[str, Any]:
    """PO PDF 文件 → parse_po_text; 缺文件/缺库/无文本显式标注。"""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "file not found", "path": str(path)}
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except Exception:
            return {"ok": False, "error": "pypdf not installed", "path": str(path)}
    try:
        r = PdfReader(path)
        text = "\n".join((pg.extract_text() or "") for pg in r.pages)
    except Exception as e:  # noqa
        return {"ok": False, "error": repr(e), "path": str(path)}
    out = parse_po_text(text)
    out["ok"] = out["po_id"] is not None
    out["path"] = str(path)
    out["_source"] = "pypdf+regex"
    return out
