"""step_thumbnail.py — STEP 文件几何摘要 + SVG 缩略图 (v2.4.0 控制台 3D tab).

策略:
  - 调 timo.step_geometry() 拿 bbox + volume + mass + features_count
  - 生成 SVG 缩略图 (外接盒 + 特征计数标注)
  - 缓存: data/thumbnails/{sha256(step_bytes)}.svg

不依赖 matplotlib/Pillow/three.js — 纯 stdlib, 浏览器原生 <svg> 渲染。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _ROOT / "data" / "thumbnails"


def _bbox_to_svg(bbox: Dict[str, float], features_count: int,
                 volume_cm3: Optional[float], mass_g: Optional[float]) -> str:
    """bbox = {x_min, y_min, z_min, x_max, y_max, z_max} (mm)."""
    try:
        x0, y0, z0 = float(bbox["x_min"]), float(bbox["y_min"]), float(bbox["z_min"])
        x1, y1, z1 = float(bbox["x_max"]), float(bbox["y_max"]), float(bbox["z_max"])
    except Exception:
        return _fallback_svg("无法解析 bbox")

    dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
    if dx <= 0 or dy <= 0 or dz <= 0:
        return _fallback_svg("bbox 无效")

    # 等距投影: x → 屏幕 x, y → 屏幕 y, z → 屏幕 x (轻微偏移) 给立体感
    margin = 20
    base = 240
    sx, sy = base, base
    # 按最长边缩放到 base
    longest = max(dx, dy, dz)
    scale = base / longest if longest > 0 else 1.0
    w = (dx + dz * 0.4) * scale + margin * 2
    h = (dy + dz * 0.4) * scale + margin * 2

    def P(x: float, y: float, z: float, ox: float, oy: float) -> tuple:
        return (ox + (x - x0) * scale + (z - z0) * scale * 0.4,
                oy + (y1 - y) * scale - (z - z0) * scale * 0.4)

    ox, oy = margin, margin
    # 8 顶点
    p000 = P(x0, y0, z0, ox, oy)
    p100 = P(x1, y0, z0, ox, oy)
    p010 = P(x0, y1, z0, ox, oy)
    p110 = P(x1, y1, z0, ox, oy)
    p001 = P(x0, y0, z1, ox, oy)
    p101 = P(x1, y0, z1, ox, oy)
    p011 = P(x0, y1, z1, ox, oy)
    p111 = P(x1, y1, z1, ox, oy)

    def fmt(pt): return f"{pt[0]:.1f},{pt[1]:.1f}"

    vol_txt = f"{volume_cm3:.1f} cm³" if volume_cm3 else "—"
    mass_txt = f"{mass_g:.1f} g" if mass_g else "—"
    feat_txt = f"{int(features_count)} 个特征" if features_count else "—"
    label_w = max(dx, dy, dz)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h+50:.0f}" width="{w:.0f}" height="{h+50:.0f}" style="background:#0b1020;border-radius:8px">
  <g stroke="#6366f1" stroke-width="1.2" fill="rgba(99,102,241,0.18)">
    <!-- back face -->
    <polygon points="{fmt(p001)} {fmt(p101)} {fmt(p111)} {fmt(p011)}" fill="rgba(99,102,241,0.08)"/>
    <!-- front face -->
    <polygon points="{fmt(p000)} {fmt(p100)} {fmt(p110)} {fmt(p010)}"/>
    <!-- edges -->
    <line x1="{p000[0]:.1f}" y1="{p000[1]:.1f}" x2="{p001[0]:.1f}" y2="{p001[1]:.1f}"/>
    <line x1="{p100[0]:.1f}" y1="{p100[1]:.1f}" x2="{p101[0]:.1f}" y2="{p101[1]:.1f}"/>
    <line x1="{p110[0]:.1f}" y1="{p110[1]:.1f}" x2="{p111[0]:.1f}" y2="{p111[1]:.1f}"/>
    <line x1="{p010[0]:.1f}" y1="{p010[1]:.1f}" x2="{p011[0]:.1f}" y2="{p011[1]:.1f}"/>
  </g>
  <g fill="#8b96b8" font-family="ui-monospace,Consolas,monospace" font-size="11">
    <text x="{margin}" y="{h+18:.0f}">L:{dx:.1f}  W:{dy:.1f}  H:{dz:.1f} mm</text>
    <text x="{margin}" y="{h+34:.0f}">体积 {vol_txt} · 质量 {mass_txt} · {feat_txt}</text>
  </g>
</svg>"""


def _fallback_svg(reason: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240" width="240" height="240" '
            f'style="background:#0b1020;border-radius:8px">'
            f'<g fill="#8b96b8" font-family="ui-monospace,Consolas,monospace" font-size="12">'
            f'<text x="120" y="120" text-anchor="middle">{reason}</text>'
            f'<text x="120" y="140" text-anchor="middle">(无法生成 3D 缩略图)</text>'
            f'</g></svg>')


def make_thumbnail(timo, path: str, use_cache: bool = True) -> Dict[str, Any]:
    """生成 STEP 缩略图 SVG + 几何摘要。优先用 sha256 缓存。"""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "reason": f"file not found: {path}"}

    try:
        raw = p.read_bytes()
        h = hashlib.sha256(raw).hexdigest()[:16]
    except Exception as e:
        return {"ok": False, "reason": f"read error: {e!r}"}

    cache_png = _CACHE_DIR / f"{h}.svg"
    if use_cache and cache_png.exists():
        return {"ok": True, "sha256_16": h, "svg": cache_png.read_text(encoding="utf-8"),
                "cached": True,
                "media": [{"kind": "svg", "path": str(cache_png)}]}

    # 真实几何 (timo.step_geometry) — 失败时 fallback SVG, 不阻断 UI
    geo_err = None
    try:
        geo = timo.step_geometry(path, material="6061")
    except Exception as e:
        geo = {}
        geo_err = repr(e)[:200]

    if geo_err or geo.get("error"):
        reason = str(geo.get("error", "") if geo.get("error") else geo_err)[:200]
        fallback = _fallback_svg(f"几何解析失败 ({reason})")
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_png.write_text(fallback, encoding="utf-8")
        except Exception:
            pass
        return {"ok": True, "sha256_16": h, "svg": fallback,
                "cached": False, "bbox": None, "volume_cm3": None, "mass_g": None,
                "features_count": 0, "_source": "fallback:kernel-unavailable",
                "media": [{"kind": "svg", "path": str(cache_png)}]}

    bbox = geo.get("bbox") or {}
    volume = geo.get("volume_cm3")
    mass = geo.get("mass_g")

    # features
    feat_count = 0
    try:
        feats = timo.step_features(path)
        if isinstance(feats, dict):
            feat_count = int(feats.get("features_count", 0) or len(feats.get("features", [])))
        elif isinstance(feats, list):
            feat_count = len(feats)
    except Exception:
        pass

    svg = _bbox_to_svg(bbox, feat_count, volume, mass)
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_png.write_text(svg, encoding="utf-8")
    except Exception:
        pass

    return {
        "ok": True,
        "sha256_16": h,
        "svg": svg,
        "bbox": bbox,
        "volume_cm3": volume,
        "mass_g": mass,
        "features_count": feat_count,
        "cached": False,
        "_source": geo.get("_source"),
        "media": [{"kind": "svg", "path": str(cache_png)}],
    }


if __name__ == "__main__":
    import sys
    from adapters.timo_adapter import TimoAdapter
    from services.config import load_settings
    s = load_settings()
    t = TimoAdapter(s)
    if len(sys.argv) > 1:
        print(make_thumbnail(t, sys.argv[1]))
    else:
        print("usage: python services/step_thumbnail.py <path-to-step>")