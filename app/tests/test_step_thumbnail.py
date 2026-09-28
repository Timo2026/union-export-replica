"""test_step_thumbnail.py — v2.4.0 控制台 3D STEP 缩略图测试.

覆盖:
  - 真实 STEP → 几何摘要 + SVG (本机可能引擎不可用, 走 fallback)
  - fallback SVG: 引擎不可用时仍返回 ok=True + svg
  - 缓存命中: 第二次相同文件走 cache, 复用 SVG
  - bbox→svg 文本正确包含 viewBox + stroke + 标签
  - 文件不存在 → ok=False
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from services import step_thumbnail as st


def _fake_timo():
    """轻量 stub: 不真正调 cnc-ai-brain。"""
    class _T:
        def step_geometry(self, path, material="6061"):
            return {"error": "kernel bridge failed: "}
        def step_features(self, path):
            return {"features_count": 0}
    return _T()


def _real_timo():
    class _T:
        def step_geometry(self, path, material="6061"):
            return {
                "_source": "vendored-kernel",
                "bbox": {"x_min": 0, "y_min": 0, "z_min": 0, "x_max": 100, "y_max": 50, "z_max": 10},
                "volume_cm3": 12.5,
                "mass_g": 33.9,
            }
        def step_features(self, path):
            return {"features_count": 4}
    return _T()


def _step(tmp_path: Path, name: str = "demo.step", body: bytes = b"ISO-10303-21; fake step file") -> Path:
    p = tmp_path / name
    p.write_bytes(body)
    return p


def test_make_thumbnail_fallback_when_kernel_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_CACHE_DIR", tmp_path / "thumbnails")
    p = _step(tmp_path)
    out = st.make_thumbnail(_fake_timo(), str(p))
    assert out["ok"] is True
    assert out["_source"].startswith("fallback")
    assert "<svg" in out["svg"]
    assert "几何解析失败" in out["svg"]


def test_make_thumbnail_real_geometry_to_svg(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_CACHE_DIR", tmp_path / "thumbnails")
    p = _step(tmp_path)
    out = st.make_thumbnail(_real_timo(), str(p))
    assert out["ok"] is True
    assert out["_source"] == "vendored-kernel"
    assert out["bbox"]["x_max"] == 100
    assert out["volume_cm3"] == 12.5
    assert out["mass_g"] == 33.9
    assert out["features_count"] == 4
    svg = out["svg"]
    assert "<svg" in svg
    assert "L:" in svg  # bbox 标签
    assert "体积" in svg
    assert "stroke=\"#6366f1\"" in svg  # accent 颜色


def test_make_thumbnail_cache_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_CACHE_DIR", tmp_path / "thumbnails")
    p = _step(tmp_path)
    out1 = st.make_thumbnail(_real_timo(), str(p), use_cache=False)
    assert out1["cached"] is False
    out2 = st.make_thumbnail(_real_timo(), str(p), use_cache=True)
    assert out2["cached"] is True
    assert out2["sha256_16"] == out1["sha256_16"]


def test_make_thumbnail_cache_skip_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_CACHE_DIR", tmp_path / "thumbnails")
    p = _step(tmp_path)
    out1 = st.make_thumbnail(_real_timo(), str(p), use_cache=False)
    out2 = st.make_thumbnail(_real_timo(), str(p), use_cache=False)
    assert out2["cached"] is False
    # 即便不命中 cache, sha 一致
    assert out2["sha256_16"] == out1["sha256_16"]


def test_make_thumbnail_file_not_found(tmp_path):
    out = st.make_thumbnail(_real_timo(), str(tmp_path / "ghost.step"))
    assert out["ok"] is False
    assert "not found" in out["reason"]


def test_make_thumbnail_different_files_different_sha(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_CACHE_DIR", tmp_path / "thumbnails")
    a = _step(tmp_path, name="a.step", body=b"file A body")
    b = _step(tmp_path, name="b.step", body=b"file B body")
    oa = st.make_thumbnail(_real_timo(), str(a), use_cache=False)
    ob = st.make_thumbnail(_real_timo(), str(b), use_cache=False)
    assert oa["sha256_16"] != ob["sha256_16"]


def test_bbox_to_svg_contains_dimensions(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_CACHE_DIR", tmp_path / "thumbnails")
    svg = st._bbox_to_svg(
        {"x_min": 0, "y_min": 0, "z_min": 0, "x_max": 60, "y_max": 30, "z_max": 5},
        features_count=3, volume_cm3=8.0, mass_g=21.0)
    assert "L:60.0" in svg
    assert "W:30.0" in svg
    assert "H:5.0" in svg
    assert "8.0 cm³" in svg
    assert "21.0 g" in svg
    assert "3 个特征" in svg


def test_bbox_to_svg_fallback_on_empty_bbox():
    svg = st._bbox_to_svg({}, 0, None, None)
    assert "无法解析" in svg
    svg2 = st._bbox_to_svg({"x_min": 0, "y_min": 0, "z_min": 0, "x_max": 0, "y_max": 0, "z_max": 0}, 0, None, None)
    assert "bbox 无效" in svg2


def test_fallback_svg_text():
    svg = st._fallback_svg("some reason")
    assert "some reason" in svg
    assert "<svg" in svg