"""test_e2_skills.py — E2 (#35): rag-ingest / batch-quote / quote-correction skill 打包.

复用既有轮子 (rag_layers / scripts.batch_quote / scripts.quote_correction), skill 层只做
契约封装 + skills.yaml 注册打通 dispatcher 可达 (AUDIT LINK-5/F6 模式)。
"""
from __future__ import annotations

from pathlib import Path

import services.skill_registry as sr
from services.config import load_settings  # noqa: F401  (确保 services 包已加载)

NEW_SKILLS = ["rag-ingest", "batch-quote", "quote-correction"]


def _tool(name: str):
    import importlib.util
    p = Path(__file__).resolve().parent.parent / "skills" / name / "tool.py"
    spec = importlib.util.spec_from_file_location(f"skill_tool_{name}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- 发现与注册 ----

def test_new_skills_discovered_with_contract():
    names = {s.get("name") for s in sr.discover()}
    assert set(NEW_SKILLS) <= names
    for s in sr.discover():
        if s.get("name") in NEW_SKILLS:
            assert (s.get("tool_contract") or {}).get("openai_function"), s["name"]
            assert s.get("iron_rule") == "deterministic"


def test_new_skills_registered_in_skills_yaml():
    import yaml
    root = Path(__file__).resolve().parent.parent
    cfg = yaml.safe_load((root / "config" / "skills.yaml").read_text(encoding="utf-8"))
    keys = set(cfg.get("skills") or {})
    assert {"rag_ingest", "batch_quote", "quote_correction"} <= keys
    for k in ("rag_ingest", "batch_quote", "quote_correction"):
        assert cfg["skills"][k]["enabled"] is True


# ---- rag-ingest ----

class FakeGW:
    def __init__(self):
        self.calls = []

    def ingest_file(self, path, customer_id=None, **kw):
        self.calls.append(("ingest_file", str(path)))
        return {"ok": True, "doc_id": Path(path).stem}

    def index_all_quotes(self):
        self.calls.append(("index_all_quotes",))
        return 42

    def list_ingested_docs(self, customer_id=None):
        return []


def test_rag_ingest_resolves_absolute_path(monkeypatch, tmp_path):
    m = _tool("rag-ingest")
    gw = FakeGW()
    monkeypatch.setattr("services.rag_layers.get_gateway", lambda **kw: gw)
    f = tmp_path / "spec.pdf"
    f.write_bytes(b"x")
    out = m.run(ctx=None, action="ingest_file", file_path=str(f))
    assert out["ok"] is True
    kind, p = gw.calls[0]
    assert Path(p).is_absolute()          # 内核/子进程铁律: 必传绝对路径
    assert kind == "ingest_file"


def test_rag_ingest_reindex_and_bad_args():
    m = _tool("rag-ingest")
    out = m.run(ctx=None, action="ingest_file")   # 缺 file_path
    assert out["ok"] is False and "file_path" in out["error"]


# ---- batch-quote ----

def test_batch_quote_requires_bom_path():
    m = _tool("batch-quote")
    out = m.run(ctx=None, action="quote_bom")
    assert out["ok"] is False and "bom_path" in out["error"]


def test_batch_quote_resolves_paths_and_summarizes(monkeypatch, tmp_path):
    import scripts.batch_quote as bq
    m = _tool("batch-quote")
    bom = tmp_path / "bom.xlsx"
    bom.write_bytes(b"x")

    captured = {}

    def fake_bom_rows(path):
        captured["path"] = path
        return [{"code": "P1", "qty": 2}]

    def fake_quote_bom(rows, ctrl, assets_dir=None, **kw):
        captured["assets"] = assets_dir
        return [{"code": "P1", "qty": 2, "unit_price": 10.0,
                 "total_price": 20.0, "has_step": False}]

    monkeypatch.setattr(bq, "bom_rows", fake_bom_rows)
    monkeypatch.setattr(bq, "quote_bom", fake_quote_bom)

    class Ctx:
        def get_ctrl(self):
            return object()

    out = m.run(ctx=Ctx(), action="quote_bom", bom_path=str(bom),
                assets_dir=str(tmp_path / "assets"))
    assert out["ok"] is True
    assert out["summary"]["n_rows"] == 1
    assert Path(captured["path"]).is_absolute()
    assert Path(captured["assets"]).is_absolute()


# ---- quote-correction ----

def test_quote_correction_delegates_and_marks_proposal_only(monkeypatch):
    import scripts.quote_correction as qc
    m = _tool("quote-correction")

    def fake_correct(gw, corrector, engine_quote, query, customer_id, **kw):
        return {"unit_price": 96.0, "applied": ["price_band_pull"],
                "base_unit_price": engine_quote["unit_price"]}

    monkeypatch.setattr(qc, "correct_quote_with_l2", fake_correct)
    monkeypatch.setattr("services.rag_layers.get_gateway", lambda **kw: FakeGW())
    out = m.run(ctx=None, action="correct",
                engine_quote={"unit_price": 90.0, "context_id": "C1"},
                query="6061 阳极氧化", customer_id="JIEVO")
    assert out["ok"] is True
    assert out["proposal_only"] is True          # 铁律①: 提案非终价
    assert out["iron_rule"] == "deterministic"
    assert out["correction"]["unit_price"] == 96.0


def test_quote_correction_no_anchor_is_honest_noop(monkeypatch):
    import scripts.quote_correction as qc
    m = _tool("quote-correction")
    monkeypatch.setattr(qc, "correct_quote_with_l2",
                        lambda *a, **kw: None)   # 脚本契约: 无召回 → None
    monkeypatch.setattr("services.rag_layers.get_gateway", lambda **kw: FakeGW())
    out = m.run(ctx=None, action="correct",
                engine_quote={"unit_price": 90.0}, query="冷门件",
                customer_id="X")
    assert out["ok"] is False
    assert "no_anchor" in out["reason"]


def test_quote_correction_missing_args():
    m = _tool("quote-correction")
    out = m.run(ctx=None, action="correct", engine_quote={}, query="",
                customer_id="")
    assert out["ok"] is False
