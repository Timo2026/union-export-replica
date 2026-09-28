"""tests/test_spark_writer.py — T11: spark-output dashboard 实时注入 (3 用例).

覆盖:
  1. 单 dispatch 写入 + 模板占位符替换
  2. 多 dispatch 合并 (STATE 增量更新)
  3. 模板完整性 (不破坏非占位符内容)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

import pytest


def _ensure_dashboard_template(root: Path) -> Path:
    """写一个最小 dashboard.html 模板 (含占位符)."""
    spark = root / "spark-output"
    spark.mkdir(parents=True, exist_ok=True)
    tmpl = spark / "dashboard.html"
    if not tmpl.exists():
        tmpl.write_text("""<!DOCTYPE html>
<html>
<head><title>SparkSkillsHub</title></head>
<body>
<header><h1>$PROJECT</h1><p>$DESCRIPTION</p></header>
<main>
<script>window.__SPARK_STATE__ = /*__SPARK_STATE_INJECT__*/null;</script>
</main>
</body>
</html>""", encoding="utf-8")
    return tmpl


# ---- 1. 单 dispatch 写入 ----
def test_single_dispatch_write(tmp_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_root)
    _ensure_dashboard_template(tmp_root)
    from services import spark_writer
    # 写一个 dispatch context
    spark_writer.append_context("disp-001", {
        "done": True,
        "summary": "S1 PASS · auto approved",
        "fields": {"verdict": "PASS", "context_id": "RFQ-001", "unit_price": 76.53},
    })
    # 更新 dashboard
    ok = spark_writer.update_dashboard()
    assert ok is True

    # 检查 spark-output/context/disp-001.json
    ctx_file = tmp_root / "spark-output" / "context" / "disp-001.json"
    assert ctx_file.exists()
    data = json.loads(ctx_file.read_text(encoding="utf-8"))
    assert data["dispatch_id"] == "disp-001"
    assert data["summary"] == "S1 PASS · auto approved"

    # 检查 dashboard.html 含 STATE 注入
    dash = tmp_root / "spark-output" / "dashboard.html"
    assert dash.exists()
    html = dash.read_text(encoding="utf-8")
    assert "/*__SPARK_STATE_INJECT__*/null" not in html, "占位符未被替换"
    assert "disp-001" in html
    assert "RFQ-001" in html


# ---- 2. 多 dispatch 合并 ----
def test_multiple_dispatches_merge(tmp_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_root)
    _ensure_dashboard_template(tmp_root)
    from services import spark_writer
    # 写 3 个 dispatch
    for i, kind in enumerate(["PASS", "HITL", "BLOCKED"], start=1):
        spark_writer.append_context(f"disp-{i:03d}", {
            "done": True,
            "summary": f"Mail {i}: {kind}",
            "fields": {"verdict": kind},
        })
    # 更新
    ok = spark_writer.update_dashboard()
    assert ok is True
    # STATE 应含 3 个 context
    state = spark_writer.get_state()
    assert len(state["contexts"]) == 3
    assert "disp-001" in state["contexts"]
    assert "disp-003" in state["contexts"]
    assert state["contexts"]["disp-002"]["fields"]["verdict"] == "HITL"


# ---- 3. 模板完整性 (不破坏其它内容) ----
def test_template_integrity(tmp_root: Path, monkeypatch) -> None:
    """更新 dashboard 后, 非占位符内容应保持不变."""
    monkeypatch.chdir(tmp_root)
    tmpl = _ensure_dashboard_template(tmp_root)
    original = tmpl.read_text(encoding="utf-8")
    # 取一些非占位符片段
    fragments = [
        "<!DOCTYPE html>", "<title>SparkSkillsHub</title>",
        "<h1>$PROJECT</h1>", "<p>$DESCRIPTION</p>",
    ]
    for f in fragments:
        assert f in original

    from services import spark_writer
    spark_writer.append_context("test-disp", {"done": True, "summary": "x"})
    spark_writer.update_dashboard()

    rendered = (tmp_root / "spark-output" / "dashboard.html").read_text(encoding="utf-8")
    for f in fragments:
        assert f in rendered, f"模板片段 '{f}' 被破坏"


# ---- 4. 模板缺失 → 返 False 不静默 ----
def test_template_missing_returns_false(tmp_root: Path, monkeypatch) -> None:
    """模板文件不存在 → update_dashboard 返 False + 不写 dashboard."""
    monkeypatch.chdir(tmp_root)
    # 确保 spark-output 目录存在但无 dashboard.html
    (tmp_root / "spark-output").mkdir(parents=True, exist_ok=True)
    dash = tmp_root / "spark-output" / "dashboard.html"
    if dash.exists():
        dash.unlink()
    from services import spark_writer
    assert spark_writer.update_dashboard() is False
    assert not dash.exists()


# ---- 5. atomic write: 失败时 tmp 文件清理 ----
def test_atomic_write(tmp_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_root)
    _ensure_dashboard_template(tmp_root)
    from services import spark_writer
    spark_writer.append_context("atomic-test", {"done": True, "summary": "atomic"})
    spark_writer.update_dashboard()
    # 没有 .tmp 残留
    tmps = list((tmp_root / "spark-output").glob("*.tmp"))
    assert all("dashboard" not in t.name for t in tmps)
