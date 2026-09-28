"""test_rag_layers.py — B1 LayeredRAGGateway 骨架单测 (任务 #23).

四层: L1 customer(SQL真库) / L2 quotes(向量) / L3 conversations(funasr 可缺) / L4 craft(rag.py 真件)
铁律: :1278 embedding 优先, 不可达 → HashEmbedder 确定性降级且显式 MOCK 标注, 绝不冒充在线.
"""
from __future__ import annotations

import pytest

from services.rag_layers import HybridEmbedder, LayeredRAGGateway
from services.crm_memory import CRMMemory
from services.flywheel.vector_store import VectorStore


# ---------- HybridEmbedder ----------
def test_embedder_offline_fallback_deterministic():
    """:59999 不可达 → HashEmbedder 降级, 确定性, degraded+MOCK 标注."""
    emb = HybridEmbedder(url="http://127.0.0.1:59999/v1")
    v1 = emb.embed("6061 阳极氧化")
    v2 = emb.embed("6061 阳极氧化")
    assert v1 == v2 and len(v1) > 0
    assert emb.degraded is True
    assert emb.source == "MOCK:hash-embedder"


def test_embedder_live_transport_injected():
    """注入可用 transport → 在线向量, degraded=False, source live."""
    def fake_post(payload):
        return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
    emb = HybridEmbedder(url="http://x/v1", transport=fake_post)
    v = emb.embed("hi")
    assert v == [0.1, 0.2, 0.3]
    assert emb.degraded is False
    assert emb.source.startswith("live:")


# ---------- Gateway 各层 ----------
@pytest.fixture
def crm(tmp_path):
    return CRMMemory(db_path=str(tmp_path / "crm.sqlite3"))


@pytest.fixture
def store(tmp_path):
    return VectorStore(backend="memory")


def test_layer_craft_offline_hits(crm, store):
    gw = LayeredRAGGateway(store=store, crm=crm)
    r = gw.search("304 阳极氧化 工艺", layers=("craft",), top_k=3)
    craft = r["layers"]["craft"]
    assert len(craft["hits"]) > 0
    assert craft["source"] == "MOCK:builtin-kb"


def test_layer_quotes_vector_roundtrip_and_filter(crm, store):
    gw = LayeredRAGGateway(store=store, crm=crm)
    gw.index_quote(customer_id="C-1", quote_id="Q-1",
                   text="材料:6061 表面:阳极氧化 公差:IT7 单价:42")
    gw.index_quote(customer_id="C-2", quote_id="Q-2",
                   text="材料:TC4 表面:磨削 公差:IT5 单价:880")
    r = gw.search("6061 阳极氧化 IT7", layers=("quotes",), top_k=2)
    hits = r["layers"]["quotes"]["hits"]
    # 只断言 roundtrip 成员关系: 排序属 embedder 内部行为 (64 维 hash 余弦), 非网关契约
    ids = [h["id"] for h in hits]
    assert "C-1:Q-1" in ids and "C-2:Q-2" in ids
    assert all(isinstance(h["score"], float) for h in hits)
    # 客户过滤: 只查 C-2 时不得出现 Q-1
    r2 = gw.search("6061", layers=("quotes",), customer_id="C-2", top_k=5)
    ids = [h["id"] for h in r2["layers"]["quotes"]["hits"]]
    assert all(i.endswith("Q-2") for i in ids)


def test_layer_customer_real_crm(crm, store):
    cid = crm.upsert_customer({"name": "Alice"})
    gw = LayeredRAGGateway(store=store, crm=crm)
    r = gw.search("Alice 的历史", layers=("customer",), customer_id=cid)
    lay = r["layers"]["customer"]
    assert lay["source"].startswith("crm:")
    assert isinstance(lay["hits"], list)


def test_layer_conversations_absent_degrades_not_crash(crm, store):
    gw = LayeredRAGGateway(store=store, crm=crm, funasr=None)
    r = gw.search("客户说过什么", layers=("conversations",))
    conv = r["layers"]["conversations"]
    assert conv["hits"] == []
    assert conv["degraded"] is True


def test_search_default_all_layers_and_evidence_flatten(crm, store):
    gw = LayeredRAGGateway(store=store, crm=crm)
    r = gw.search("6061 bracket 报价", top_k=3)
    assert set(r["layers"]) == {"customer", "quotes", "conversations", "craft"}
    assert r["ok"] is True
    for ev in r["evidence"]:
        assert ev["layer"] in r["layers"]


# ---------- B2: quotes 向量化回填 + list_similar_quotes (任务 #24) ----------
def _seed_quote(crm, cid, ctx, material, surface, tolerance, price):
    crm.write_rfq({"context_id": ctx, "state": "DONE",
                   "rfq": {"customer": {"customer_id": cid}, "material": material,
                           "surface": surface, "quantity": 50,
                           "tolerance_grade": tolerance}})
    crm.write_quote({"context_id": ctx, "commercial": {"quote": {
                         "unit_price": price, "final_price": price * 50,
                         "currency": "CNY", "lead_time_days": 15}}},
                    {"status": "VERIFIED"}, {"subject": "Quote for " + ctx})


def test_iter_quote_docs_joins_rfq_and_quote(crm):
    _seed_quote(crm, "C-1", "CTX-1", "6061", "阳极氧化", "IT7", 42.0)
    docs = list(crm.iter_quote_docs())
    assert len(docs) == 1
    d = docs[0]
    assert d["customer_id"] == "C-1" and d["context_id"] == "CTX-1"
    assert d["material"] == "6061" and d["unit_price"] == 42.0


def test_index_all_quotes_backfills_history(store, crm):
    _seed_quote(crm, "C-1", "CTX-1", "6061", "阳极氧化", "IT7", 42.0)
    _seed_quote(crm, "C-2", "CTX-2", "TC4", "磨削", "IT5", 880.0)
    gw = LayeredRAGGateway(store=store, crm=crm)
    n = gw.index_all_quotes()
    assert n == 2
    assert store.count("quote_history") == 2
    # 幂等: 再跑一次不产生重复点
    assert gw.index_all_quotes() == 2
    assert store.count("quote_history") == 2


def test_list_similar_quotes_customer_filter_and_limit(store, crm):
    _seed_quote(crm, "C-1", "CTX-1", "6061", "阳极氧化", "IT7", 42.0)
    _seed_quote(crm, "C-2", "CTX-2", "TC4", "磨削", "IT5", 880.0)
    _seed_quote(crm, "C-2", "CTX-3", "304", "抛光", "IT6", 96.0)
    gw = LayeredRAGGateway(store=store, crm=crm)
    gw.index_all_quotes()
    hits = gw.list_similar_quotes("TC4 磨削 报价", customer_id="C-2", limit=5)
    assert hits and all(h["payload"]["customer_id"] == "C-2" for h in hits)
    assert len(gw.list_similar_quotes("报价", limit=1)) == 1


# ---------- HybridEmbedder 粘性降级 (B4 收尾: 冷却期内不重复探测) ----------
def test_embedder_sticky_degrade_no_reprobe_within_cooldown():
    """失败后冷却期内直接走 fallback — 否则每次 embed 白付 ~2s 探测税."""
    import time as _t

    calls = []

    def boom(payload):
        calls.append(1)
        raise OSError("connection refused")

    emb = HybridEmbedder(url="http://x/v1", transport=boom, degrade_cooldown_s=3600)
    emb.embed("a")
    n1 = len(calls)
    t0 = _t.time()
    for _ in range(20):
        assert emb.embed("b") == emb.embed("b")
    assert len(calls) == n1 == 1          # 冷却窗口内零重探
    assert emb.degraded is True
    assert emb.source == "MOCK:hash-embedder"
    assert _t.time() - t0 < 1.0           # 降级路径必须快


def test_embedder_reprobes_after_cooldown():
    import time as _t

    calls = []

    def boom(payload):
        calls.append(1)
        raise OSError("refused")

    emb = HybridEmbedder(url="http://x/v1", transport=boom, degrade_cooldown_s=0.05)
    emb.embed("a")
    _t.sleep(0.08)
    emb.embed("a")
    assert len(calls) == 2                # 冷却到期后恢复探测
