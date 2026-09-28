"""test_quote_correction.py — D4 分级自动矫正接线 + PO 真值精度验证 (任务 #33).

接线: L2 历史锚点 (杰沃 PO → quote_history) → recall dict → v6.2 PriceCorrector
      (分级封顶 cold±5%/warm±10%/hot±15% + 审计链), 铁律: 不改确定性 base_price。
精度: leave-one-out — 评估 PO 自身行项从召回中排除, 防真值泄漏; MAPE 前/后对比。
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest

from services.flywheel.price_corrector import PriceCorrector

_JIEVO = Path("C:/Users/<user>/Music/qianyi/演示/批量报价/杰沃/杰沃")


class FakeGW:
    def __init__(self, hits, points):
        self._hits = hits
        self._points = points

    def list_similar_quotes(self, query, customer_id=None, limit=5):
        return self._hits[:limit]

    class _S:
        def __init__(self, points):
            self._p = points

        def list_points(self, coll):
            return self._p

    @property
    def store(self):
        return FakeGW._S(self._points)


def _hit(price, qid, material="6061", surface="阳极氧化"):
    return {"score": 0.8, "payload": {"unit_price": price, "quote_id": qid,
                                      "material": material, "surface": surface}}


# ---------- recall 构造 ----------
def test_recall_from_l2_band_and_tier():
    from scripts.quote_correction import recall_from_l2
    hits = [_hit(300.0, "PO-C1:11"), _hit(320.0, "PO-C1:12"), _hit(280.0, "PO-C2:21")]
    points = [{"payload": {"customer_id": "JIEVO"}}] * 60
    gw = FakeGW(hits, points)
    rec = recall_from_l2(gw, "6061 阳极氧化", "JIEVO", limit=3)
    assert rec["sample_count"] == 60                      # tier=hot 依据租户全量样本
    assert rec["price_band"]["p50"] == pytest.approx(300.0)
    assert len(rec["similar_won"]) == 3
    assert rec["similar_won"][0]["payload"]["final_price"] == 300.0
    assert 0 < rec["confidence"] <= 1.0


def test_recall_exclude_prefix_prevents_leak():
    from scripts.quote_correction import recall_from_l2
    hits = [_hit(300.0, "PO-C9:99"), _hit(320.0, "PO-C1:12")]
    gw = FakeGW(hits, [])
    rec = recall_from_l2(gw, "q", "JIEVO", exclude_prefix="PO-C9")
    assert len(rec["similar_won"]) == 1
    assert rec["similar_won"][0]["payload"]["context_id"] == "PO-C1:12"


# ---------- 矫正接线 ----------
def test_correct_quote_uses_l2_anchor_hot_cap():
    from scripts.quote_correction import correct_quote_with_l2
    hits = [_hit(300.0, f"PO-C1:{i}") for i in range(10)]
    gw = FakeGW(hits, [{"payload": {"customer_id": "JIEVO"}}] * 60)
    out = correct_quote_with_l2(gw, PriceCorrector(), {"unit_price": 600.0},
                                "6061 阳极氧化", "JIEVO", exclude_prefix="PO-C9")
    assert out is not None
    assert out["tier"] == "hot"
    assert out["correction_pct"] == pytest.approx(-0.15)  # 引擎价 2× 锚点 p50 → 拉回触顶
    assert out["corrected_price"] == 510.0
    assert out["base_price"] == 600.0                     # 确定性原价不动
    assert len(out["audit_chain"]) == 16


def test_correct_quote_no_anchor_returns_none():
    from scripts.quote_correction import correct_quote_with_l2
    gw = FakeGW([], [])
    assert correct_quote_with_l2(gw, PriceCorrector(), {"unit_price": 10.0},
                                 "q", "JIEVO") is None


# ---------- MAPE ----------
def test_mape_math():
    from scripts.quote_correction import mape
    rows = [{"truth": 100.0, "pred": 110.0}, {"truth": 50.0, "pred": 45.0}]
    assert mape(rows) == pytest.approx(10.0)              # (10% + 10%) / 2
    assert mape([]) is None


# ---------- 单项失败不炸整轮 (kernel bridge 并发/坏件容错) ----------
def test_evaluate_po_survives_item_errors(tmp_path, monkeypatch):
    import zipfile
    from scripts import quote_correction as qc
    z = tmp_path / "d.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("PO1-Part9-1-A.stp", "ISO-10303")
        zf.writestr("PO1-Part9-2-B.stp", "ISO-10303")
    po = {"po_id": "PO1", "items": [
        {"article": "1", "part": "A.stp", "qty": 1, "unit_price": 100.0, "material": "6061"},
        {"article": "2", "part": "B.stp", "qty": 1, "unit_price": 200.0, "material": "6061"}]}
    monkeypatch.setattr(qc.fi, "parse_step",
                        lambda p, timo, material="6061", with_features=True: {"geometry": {}})

    class BoomCtrl:
        timo = None

        def run(self, **kw):
            if "B.stp" in kw["email_text"]:
                raise RuntimeError("kernel bridge failed")
            return {"state": "DONE", "quote": {"unit_price": 120.0}, "margin_pct": 25}

    gw = FakeGW([], [])
    rows = qc.evaluate_po(BoomCtrl(), gw, po, str(z), str(tmp_path / "ex"),
                          customer_id="JIEVO")
    assert len(rows) == 2
    ok = [r for r in rows if r["part"] == "A.stp"][0]
    bad = [r for r in rows if r["part"] == "B.stp"][0]
    assert ok["engine_price"] == 120.0 and "error" not in ok
    assert bad["engine_price"] is None and "kernel bridge" in bad["error"]
    assert bad["po_price"] == 200.0                    # 真值仍记录


# ---------- 真实语料 leave-one-out (缺文件 skip) ----------
@pytest.mark.skipif(not _JIEVO.exists(), reason="杰沃语料不在本机")
def test_real_leave_one_out_single_po(tmp_path):
    """1 个真实 PO × 其 STEP → 引擎价 vs PO 真值 + LOO 矫正 (结构断言)."""
    import services.file_intake as fi
    from bootstrap import build_controller
    from scripts.jievo_po_scan import ingest_pos_to_l2, scan_po_dir
    from scripts.quote_correction import evaluate_po
    from services.flywheel.vector_store import VectorStore
    from services.rag_layers import HybridEmbedder, LayeredRAGGateway

    pos, _ = scan_po_dir(str(_JIEVO))
    po = next(p for p in pos if (_JIEVO / f"{p['po_id']}-drawings.zip").exists())
    gw = LayeredRAGGateway(store=VectorStore(backend="memory"), crm=None, funasr=None,
                           embedder=HybridEmbedder(url="http://127.0.0.1:59999/v1"))
    ingest_pos_to_l2(gw, pos, customer_id="JIEVO")       # 全史入库, LOO 排除本 PO
    rows = evaluate_po(build_controller(), gw, po,
                       str(_JIEVO / f"{po['po_id']}-drawings.zip"),
                       str(tmp_path / "ex"), customer_id="JIEVO")
    assert rows, "该 PO 应至少有一个 STEP 行项可评估"
    for r in rows:
        assert r["po_price"] > 0 and r["engine_price"] and r["engine_price"] > 0
        assert r["engine_price"] != r["po_price"]         # 引擎不读 PO 价 (真值独立)
        if r["correction"]:
            assert r["correction"]["base_price"] == r["engine_price"]


# ---------- bridge 路径缺陷 (真实评估 13/13 全崩的根因) ----------
def test_evaluate_po_passes_absolute_step_path(tmp_path, monkeypatch):
    """桥子进程 cwd=engine_src → 相对 STEP 路径必失败, 传路径前必须 resolve 为绝对。"""
    import zipfile
    import scripts.quote_correction as qc
    monkeypatch.chdir(tmp_path)
    (tmp_path / "d").mkdir()
    with zipfile.ZipFile(tmp_path / "d" / "PO-X-drawings.zip", "w") as z:
        z.writestr("PO-X-Part1-a.stp", "ISO-10303-21;")
    seen = []

    def fake_parse_step(path, timo, material="6061", with_features=False):
        seen.append(path)
        return {"ok": True}
    monkeypatch.setattr(qc.fi, "parse_step", fake_parse_step)

    class RunCtrl:
        timo = object()

        def run(self, **kw):
            return {"quote": {}, "state": "HITL"}
    po = {"po_id": "PO-X", "items": [{"article": "1", "part": "a.stp", "qty": 1,
           "unit_price": 110.0, "material": "6061", "surface": None, "tolerance": None}]}
    rows = qc.evaluate_po(RunCtrl(), None, po, "d/PO-X-drawings.zip", "ext")
    assert not rows[0].get("error")
    assert seen and Path(seen[0]).is_absolute()


def test_dedupe_pos_keeps_first_per_po_id():
    from scripts.quote_correction import dedupe_pos
    pos = [{"po_id": "PO-A"}, {"po_id": "PO-B"}, {"po_id": "PO-A"}]
    assert [p["po_id"] for p in dedupe_pos(pos)] == ["PO-A", "PO-B"]


def test_recall_drops_zero_price_anchors():
    """18/422 JIEVO 锚点 unit_price=0 (PO 含 0 元行), 不得污染价格带。"""
    from scripts.quote_correction import recall_from_l2
    hits = [_hit(0.0, "PO-Z:1"), _hit(300.0, "PO-C1:11"),
            _hit(320.0, "PO-C1:12"), _hit(280.0, "PO-C2:21")]
    rec = recall_from_l2(FakeGW(hits, []), "6061", "JIEVO", limit=4)
    assert all(w["payload"]["final_price"] > 0 for w in rec["similar_won"])
    assert len(rec["similar_won"]) == 3
    assert rec["price_band"]["p50"] == pytest.approx(300.0)
