"""test_e1_cleanup.py — E1 死代码/重复轮子清理守卫 (任务 #34).

结构性断言: 同名方法定义只允许一份 (防止覆盖式死代码再生)。
"""
from __future__ import annotations

import inspect


def test_quote_calibration_has_single_calibrate_definition():
    from services import quote_calibration
    src = inspect.getsource(quote_calibration)
    assert src.count("def calibrate(") == 1


def test_live_calibrate_is_proposal_only_version():
    """幸存的那份必须是 T6.4 proposal_only 版 (铁律①: 提案副本非权威终价)。"""
    from services.quote_calibration import QuoteCalibration
    qc = QuoteCalibration(crm=None)              # 无 customer_id → 不触库
    calibrated, adj = qc.calibrate({}, {"quantity": 100}, {"unit_price": 100.0})
    assert adj.get("proposal_only") is True
    assert calibrated["unit_price"] == 100.0       # 无历史模型 → 原价不动


def _ctor_accepts_none() -> bool:
    return True


def test_rag_search_fallback_single_source():
    """rag_search 不再自带 MOCK_KB; 离线兜底唯一源 = rag._FALLBACK_CASES; Path 已导入。"""
    import inspect
    import services.rag_search as rs
    from services.rag import _FALLBACK_CASES
    src = inspect.getsource(rs)
    assert "MOCK_KB" not in src
    assert "from pathlib import Path" in src
    ids_all = {c["case_id"] for c in _FALLBACK_CASES}
    assert {"KB-CARBON-BLACK", "KB-WHITESPOT", "KB-DFM-WALL"} <= ids_all
    out = rs._mock_search("碳钢 发黑", 3)
    assert out["mock"] is True
    assert {h["case_id"] for h in out["hits"]} <= ids_all
    assert any(h["case_id"] == "KB-CARBON-BLACK" for h in out["hits"])


# ---- E1-d: 目标毛利单源 (settings.yaml pricing.target_margin_pct) ----

def test_target_margin_pct_helper_reads_config(tmp_path, monkeypatch):
    import services.config as cfg
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text(
        "pricing:\n  target_margin_pct: 30.0\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "_ROOT", tmp_path)
    assert cfg.target_margin_pct() == 30.0


def test_target_margin_pct_real_config_is_25():
    import services.config as cfg
    assert cfg.target_margin_pct() == 25.0


def test_margin_literal_converged_to_config():
    """三处 base_margin = 25.0 硬编码必须消失, 改为读配置。"""
    import inspect
    import services.flywheel_pricing as fp
    import services.quote_calibration as qcl
    src_fp = inspect.getsource(fp)
    src_qc = inspect.getsource(qcl)
    assert "base_margin = 25.0" not in src_fp
    assert "base_margin = 25.0" not in src_qc
    assert "target_margin_pct" in src_fp
    assert src_qc.count("target_margin_pct") >= 2
