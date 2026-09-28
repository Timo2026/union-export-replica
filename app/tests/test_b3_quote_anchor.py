"""test_b3_quote_anchor.py — B3 黄金链接 rag_layers + quote_anchor 证据 (任务 #25).

覆盖:
  1. run() 注入 LayeredRAGGateway → 返回 quote_anchor 证据 (L2 历史报价锚点),
     craft 层仍走 rag.py 离线内置库 (MOCK 显式标注, 不冒充在线)
  2. rag_gateway=None → 走原 self.rag 路径, quote_anchor is None (兼容回退)
  3. funasr adapter rag_search 支持 customer_id 透传 (修 rag.py:33 在线路径 TypeError 地雷)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bootstrap import build_controller
from services.crm_memory import CRMMemory
from services.flywheel.vector_store import VectorStore
from services.rag import RAGEvidence
from services.rag_layers import LayeredRAGGateway

_ROOT = Path(__file__).resolve().parent.parent
_SCEN = json.loads((_ROOT / "data" / "golden_scenarios.json").read_text(encoding="utf-8"))["scenarios"]


@pytest.fixture(scope="module")
def ctrl(require_engine):
    return build_controller(use_crm=False)


def _seed_history_crm(tmp_path: Path) -> CRMMemory:
    crm = CRMMemory(db_path=str(tmp_path / "crm-b3.sqlite3"))
    crm.write_rfq({"context_id": "CTX-H1", "state": "DONE",
                   "rfq": {"customer": {"customer_id": "C-9"}, "material": "6061",
                           "surface": "阳极氧化", "quantity": 100,
                           "tolerance_grade": "IT7"}})
    crm.write_quote({"context_id": "CTX-H1", "commercial": {"quote": {
                         "unit_price": 38.5, "final_price": 3850}}},
                    {"status": "VERIFIED"}, {"subject": "hist"})
    return crm


def test_run_with_gateway_emits_quote_anchor(ctrl, tmp_path, monkeypatch):
    # 断言的是离线 MOCK 回退语义 → 强制 funasr 适配离线, 不依赖 :8866 真实服务状态
    if ctrl.rag.f is not None:
        monkeypatch.setattr(ctrl.rag.f, "_online", False)
    crm = _seed_history_crm(tmp_path)
    store = VectorStore(backend="memory")
    gw = LayeredRAGGateway(store=store, crm=crm, funasr=None, rag=ctrl.rag)
    assert gw.index_all_quotes() == 1
    ctrl.rag_gateway = gw
    sc = _SCEN[0]  # S1: 6061 阳极氧化 → PASS
    r = ctrl.run(email_text=sc["email"], customer={"customer_id": "C-9", "name": "锚点客户"})
    anchor = r["quote_anchor"]
    assert anchor["hits"], anchor
    h = anchor["hits"][0]
    assert h["quote_id"] == "CTX-H1"
    assert h["unit_price"] == 38.5
    assert anchor["source"].startswith("vector:")
    # craft 层仍走 rag.py 离线内置库 (显式 MOCK)
    assert r["rag_source"] == "MOCK:builtin-kb"


def test_run_without_gateway_legacy_rag_path(ctrl, monkeypatch):
    if ctrl.rag.f is not None:
        monkeypatch.setattr(ctrl.rag.f, "_online", False)
    ctrl.rag_gateway = None
    sc = _SCEN[0]
    r = ctrl.run(email_text=sc["email"], customer={})
    assert r["quote_anchor"] is None
    assert r["rag_source"] == "MOCK:builtin-kb"


# ---- funasr adapter customer_id 地雷修复 (在线路径曾 TypeError: unexpected keyword) ----
class _Resp:
    def read(self) -> bytes:
        return json.dumps({"results": [{"case_id": "X-1"}]}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_rag_evidence_online_passes_customer_id_without_typeerror(monkeypatch):
    import adapters.funasr_adapter as fa

    seen: list = []

    def fake_urlopen(req, timeout=None):
        seen.append(req.full_url if hasattr(req, "full_url") else str(req))
        return _Resp()

    monkeypatch.setattr(fa.urllib.request, "urlopen", fake_urlopen)
    adapter = fa.FunASRAdapter({})
    adapter._online = True  # 模拟在线, 跳过 /health 真探测
    rag = RAGEvidence(adapter)
    r = rag.search("6061 阳极氧化 工艺", limit=3, customer_id="CUST-9")
    assert r["_mock"] is False
    assert r["hits"] == [{"case_id": "X-1"}]
    assert "customer_id=CUST-9" in seen[-1]
