"""test_rag_ingest.py — C2 上传→RAG ingestion (任务 #28).

三层覆盖:
  1. LayeredRAGGateway.ingest_document / ingest_file / search_ingested (L2.5 文档集合)
  2. POST /v1/rag/ingest + GET /v1/rag/search 端点 (monkeypatch api_server._CTRL, 不碰真实 crm)
  3. webui RAG 上传入口存在性

铁律: 被 zip-slip 拒绝的条目不落盘不入库; 缺依赖/空文本显式 skipped 计数, 不静默。
"""
from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace
from typing import List, Tuple

import pytest
from fastapi.testclient import TestClient

import services.api_server as api_server
from services.flywheel.vector_store import VectorStore
from services.rag_layers import HybridEmbedder, LayeredRAGGateway

INGEST_COLLECTION = "ingest_docs"


def _make_zip(entries: List[Tuple[bytes, bytes]]) -> bytes:
    """store-only zip (同 test_file_intake 手工字节法)。"""
    local_parts, central_parts = [], []
    offset = 0
    for name, data in entries:
        crc = zlib.crc32(data) & 0xFFFFFFFF
        lh = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0,
                         crc, len(data), len(data), len(name), 0) + name
        local_parts.append(lh + data)
        ch = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50,
                         20, 20, 0, 0, 0, 0,
                         crc, len(data), len(data),
                         len(name), 0, 0, 0, 0,
                         0, offset) + name
        central_parts.append(ch)
        offset += len(lh) + len(data)
    local_blob = b"".join(local_parts)
    central_blob = b"".join(central_parts)
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0,
                       len(entries), len(entries),
                       len(central_blob), len(local_blob), 0)
    return local_blob + central_blob + eocd


@pytest.fixture
def gw(tmp_path):
    store = VectorStore(backend="memory")
    emb = HybridEmbedder(url="http://127.0.0.1:59999/v1")   # 必离线 → 确定性 hash
    return LayeredRAGGateway(store=store, crm=None, funasr=None, embedder=emb)


# ---------- 1. gateway 级 ----------
def test_ingest_document_roundtrip_and_search(gw):
    r = gw.ingest_document("doc-1", "6061 阳极氧化 表面处理规范", customer_id="C-7", tags=["spec"])
    assert r["ok"] is True and r["id"] == "doc-1"
    hits = gw.search_ingested("阳极氧化", customer_id="C-7", limit=3)
    assert any(h["id"] == "doc-1" for h in hits)
    # 其他客户过滤不可见
    assert all(h["id"] != "doc-1" for h in gw.search_ingested("阳极氧化", customer_id="C-8"))


def test_ingest_file_txt_and_csv(gw, tmp_path):
    p1 = tmp_path / "notes.txt"
    p1.write_text("钛合金 IT5 需精密磨削", encoding="utf-8")
    r1 = gw.ingest_file(str(p1), customer_id="C-1")
    assert r1["ok"] is True and r1["n_docs"] == 1
    p2 = tmp_path / "bom.csv"
    p2.write_text("material,qty\n6061,50\n", encoding="utf-8")
    r2 = gw.ingest_file(str(p2), customer_id="C-1")
    assert r2["ok"] is True and r2["n_docs"] == 1
    ids = [h["id"] for cid in ("C-1",) for h in gw.search_ingested("6061", customer_id=cid, limit=10)]
    assert p1.name in ids and p2.name in ids


def test_ingest_file_zip_multi_and_rejected(gw, tmp_path):
    zb = tmp_path / "pack.zip"
    zb.write_bytes(_make_zip([
        (b"readme.txt", b"anodizing spec for 6061"),
        (b"docs/notes.txt", b"passivation note for 304"),
        (b"../evil.txt", b"BAD"),
    ]))
    r = gw.ingest_file(str(zb), customer_id="C-2", extract_dir=str(tmp_path / "x"))
    assert r["ok"] is True and r["n_docs"] == 2
    assert r["rejected"] == [{"name": "../evil.txt", "reason": "zip_slip"}]
    ids = [h["id"] for h in gw.search_ingested("anodizing", customer_id="C-2", limit=10)]
    assert any("readme.txt" in i for i in ids)
    assert not any("evil" in i for i in ids)


def test_ingest_file_unsupported_kind(gw, tmp_path):
    p = tmp_path / "binary.exe"
    p.write_bytes(b"MZ\x00\x01")
    r = gw.ingest_file(str(p))
    assert r["ok"] is False and r["n_docs"] == 0 and r["reason"]


# ---------- 2. 端点级 (monkeypatch _CTRL, 不依赖真实引擎) ----------
@pytest.fixture
def client_with_gw(gw):
    fake = SimpleNamespace(timo=None, funasr=None, settings={}, rag_gateway=gw)
    api_server._CTRL = fake
    with TestClient(api_server.app) as c:
        yield c
    api_server._CTRL = None


def test_rag_ingest_endpoint_txt(client_with_gw, gw):
    r = client_with_gw.post("/v1/rag/ingest",
                            files={"file": ("spec.txt", io.BytesIO("电解抛光规范".encode()), "text/plain")},
                            data={"customer_id": "C-API"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["n_docs"] == 1
    hits = client_with_gw.get("/v1/rag/search",
                              params={"q": "电解抛光", "customer_id": "C-API"}).json()["hits"]
    assert any(h["id"] == "spec.txt" for h in hits)


def test_rag_ingest_endpoint_zip_rejected_visible(client_with_gw):
    zb = _make_zip([(b"ok.txt", b"good note"), (b"../bad.txt", b"BAD")])
    body = client_with_gw.post("/v1/rag/ingest",
                               files={"file": ("m.zip", io.BytesIO(zb), "application/zip")}).json()
    assert body["n_docs"] == 1
    assert [e["reason"] for e in body["rejected"]] == ["zip_slip"]


def test_rag_ingest_endpoint_unsupported_200_skipped(client_with_gw):
    body = client_with_gw.post("/v1/rag/ingest",
                               files={"file": ("x.bin", io.BytesIO(b"\x00\x01"), "application/octet-stream")}).json()
    assert body["ok"] is False and body["n_docs"] == 0


# ---------- 3. webui 入口 ----------
def test_webui_has_rag_ingest_tab(require_engine):
    with TestClient(api_server.app) as c:
        html = c.get("/webui").text
    assert 'data-tab="rag"' in html, "webui 缺 RAG 上传 tab 按钮"
    assert 'id="tab-rag"' in html, "webui 缺 RAG tab 面板"
    assert "/v1/rag/ingest" in html, "webui 缺 ingest 端点调用"
    assert "/v1/rag/docs" in html, "webui 缺文档清单/删除入口"


# ---------- 4. C3 增量更新 + 重启持久 (任务 #29) ----------
def test_delete_ingested_doc(gw):
    gw.ingest_document("d1", "6061 阳极氧化规范", customer_id="C-1")
    gw.ingest_document("d2", "304 钝化规范", customer_id="C-1")
    assert gw.delete_ingested_doc("d1") is True
    assert gw.delete_ingested_doc("d1") is False          # 幂等: 不存在返回 False
    ids = [h["id"] for h in gw.search_ingested("阳极氧化", customer_id="C-1", limit=5)]
    assert "d1" not in ids and "d2" in ids


def test_list_ingested_docs_meta(gw):
    gw.ingest_document("d1", "阳极氧化" * 10, customer_id="C-1", tags=["spec", "alu"])
    docs = gw.list_ingested_docs(customer_id="C-1")
    assert len(docs) == 1
    d = docs[0]
    assert d["id"] == "d1" and d["customer_id"] == "C-1"
    assert d["chars"] == 40 and d["tags"] == ["spec", "alu"]
    assert "text" not in d                                  # 列表不回全文
    assert d["indexed_at"] > 0


def test_ingest_update_same_id_replaces(gw):
    gw.ingest_document("d1", "旧版本内容 alpha")
    gw.ingest_document("d1", "新版本内容 beta")
    docs = gw.list_ingested_docs()
    assert len(docs) == 1 and docs[0]["id"] == "d1"


def test_file_backend_persistence_survives_restart(tmp_path, monkeypatch):
    from services.flywheel.vector_store import VectorStore
    fpath = str(tmp_path / "vecs.json")
    monkeypatch.setenv("UEA_VECTOR_DB_PATH", fpath)
    s1 = VectorStore(backend="file")
    s1.upsert("ingest_docs", "k1", [0.1, 0.2, 0.3], {"customer_id": "C-1", "text": "hello"})
    s1.upsert("ingest_docs", "k2", [0.2, 0.3, 0.4], {"customer_id": "C-1", "text": "world"})
    assert Path(fpath).exists()
    s1.delete("ingest_docs", "k2")
    s2 = VectorStore(backend="file")                          # 模拟重启
    assert s2.count("ingest_docs") == 1
    hits = s2.search("ingest_docs", [0.1, 0.2, 0.3], limit=5)
    assert [h["id"] for h in hits] == ["k1"]
    assert hits[0]["payload"]["text"] == "hello"
    assert s2.delete("ingest_docs", "k1") is True
    assert VectorStore(backend="file").count("ingest_docs") == 0   # 删除也持久


def test_rag_docs_endpoints(client_with_gw, gw):
    gw.ingest_document("e1", "电解抛光工艺", customer_id="C-API")
    body = client_with_gw.get("/v1/rag/docs").json()
    assert body["count"] == 1 and body["docs"][0]["id"] == "e1"
    assert client_with_gw.delete("/v1/rag/docs/e1").json()["deleted"] is True
    assert client_with_gw.delete("/v1/rag/docs/e1").status_code == 404
    assert client_with_gw.get("/v1/rag/docs").json()["count"] == 0
