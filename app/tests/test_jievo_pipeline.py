"""test_jievo_pipeline.py — D2 杰沃 PO 全量 ingestion 管道 (任务 #31).

管道: scan_po_dir (解析目录内 PO PDF) → write_report (本地 JSON, gitignored)
      → ingest_pos_to_l2 (每行项 → quote_history 向量 + PO 摘要 → ingest_docs)。
铁律: data-stays-local — 全部落本地, 无任何网络调用; 真实语料测试缺目录即 skip。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.flywheel.vector_store import VectorStore
from services.rag_layers import INGEST_COLLECTION, QUOTES_COLLECTION, HybridEmbedder, LayeredRAGGateway

_JIEVO = Path("C:/Users/<user>/Music/qianyi/演示/批量报价/杰沃/杰沃")

SAMPLE_TEXT = """Production Order / 生产订单  PO-C1066077-621644
10#712422 CDS240701-A.stp
Material / 材料 : 铝合金  - 6061
Finish / 后处理 : Anodize (Black) / 阳极氧化  ( 黑色 ); 亮光
Part Marking / 零件标记 :1 ¥ 298.94 ¥ 298.94
20#712428 CDS240701-B.stp
Material / 材料 : 铝合金  - 6061
Part Marking / 零件标记 :2 ¥ 125.50 ¥ 251.06
Price net / 单价 :
¥ 550.00
"""


@pytest.fixture
def gw():
    return LayeredRAGGateway(store=VectorStore(backend="memory"), crm=None, funasr=None,
                             embedder=HybridEmbedder(url="http://127.0.0.1:59999/v1"))


# ---------- scan ----------
def test_scan_po_dir_counts_and_items(tmp_path, monkeypatch):
    """scan 用注入的 text_fn 读文本 → 与真实 pypdf 解耦, 逻辑可测。"""
    from scripts.jievo_po_scan import scan_po_dir
    (tmp_path / "PO-C1066077-621644.pdf").write_bytes(b"%PDF-fake")
    (tmp_path / "PO-C1066077-621644-tech-details.pdf").write_bytes(b"x")   # 排除
    (tmp_path / "PO-C1066077-621644-drawings.zip").write_bytes(b"x")       # 排除
    pos, stats = scan_po_dir(str(tmp_path), text_fn=lambda p: SAMPLE_TEXT)
    assert stats["n_po"] == 1 and stats["n_items"] == 2
    assert stats["n_priced"] == 2 and pos[0]["po_id"] == "PO-C1066077-621644"


def test_write_report_local_json(tmp_path):
    from scripts.jievo_po_scan import write_report
    out = tmp_path / "report.json"
    write_report({"pos": [{"po_id": "X"}]}, str(out))
    assert json.loads(out.read_text(encoding="utf-8"))["pos"][0]["po_id"] == "X"


# ---------- L2 ingest ----------
def test_ingest_pos_to_l2_vectors_items_and_docs(gw):
    from scripts.jievo_po_scan import ingest_pos_to_l2
    from services.po_parser import parse_po_text
    po = parse_po_text(SAMPLE_TEXT)
    n_q, n_d = ingest_pos_to_l2(gw, [po], customer_id="JIEVO")
    assert n_q == 2                                   # 两个行项 → quote_history
    assert n_d == 1                                   # PO 摘要 → ingest_docs
    assert gw.store.count(QUOTES_COLLECTION) == 2
    assert gw.store.count(INGEST_COLLECTION) == 1
    hits = gw.list_similar_quotes("6061 阳极氧化", customer_id="JIEVO", limit=5)
    assert any(h["payload"]["unit_price"] == 298.94 for h in hits)


def test_ingest_pos_skips_unpriced_items(gw):
    from scripts.jievo_po_scan import ingest_pos_to_l2
    po = {"po_id": "PO-C1-2", "items": [
        {"article": "9", "part": "a.stp", "qty": 1, "unit_price": None,
         "material": "6061", "surface": None, "tolerance": None}]}
    n_q, n_d = ingest_pos_to_l2(gw, [po], customer_id="JIEVO")
    assert n_q == 0 and n_d == 1                      # 无价行项不锚定, 但 PO 文档仍入库


def test_end_to_end_real_corpus_local_only():
    """真实 391 项语料端到端 (缺目录环境自动 skip)。只读, 不落仓库。"""
    if not _JIEVO.exists():
        pytest.skip("杰沃语料不在本机")
    from scripts.jievo_po_scan import ingest_pos_to_l2, scan_po_dir
    pos, stats = scan_po_dir(str(_JIEVO))
    assert stats["n_po"] >= 129
    assert stats["ok_rate"] >= 0.99
    gw = LayeredRAGGateway(store=VectorStore(backend="memory"), crm=None, funasr=None,
                           embedder=HybridEmbedder(url="http://127.0.0.1:59999/v1"))
    n_q, n_d = ingest_pos_to_l2(gw, pos, customer_id="JIEVO")
    assert n_d == stats["n_po"]
    assert n_q >= 400                                 # 实证 ~480 有价行项
