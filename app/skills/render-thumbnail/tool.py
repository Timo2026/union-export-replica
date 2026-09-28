"""render_thumbnail — STEP → SVG 等角投影缩略图."""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, path: str = "", file: str = "", use_cache: bool = True, **kwargs) -> Dict[str, Any]:
    p = path or file or kwargs.get("step_path") or ""
    if not p:
        return {"ok": False, "skill": "render_thumbnail", "error": "path required"}
    ctrl = ctx.get_ctrl()
    timo = ctx.timo or getattr(ctrl, "timo", None)
    from services.step_thumbnail import make_thumbnail
    try:
        out = make_thumbnail(timo, p, use_cache=use_cache)
    except Exception as e:  # noqa
        return {"ok": False, "skill": "render_thumbnail", "error": repr(e)}
    return {
        "ok": bool(out.get("ok", True)),
        "skill": "render_thumbnail",
        "iron_rule": "deterministic",
        "bbox": out.get("bbox"),
        "volume_cm3": out.get("volume_cm3"),
        "mass_g": out.get("mass_g"),
        "features_count": out.get("features_count"),
        "sha256_16": out.get("sha256_16"),
        "cached": out.get("cached"),
        "svg": out.get("svg"),
        "media": out.get("media"),
        "_source": out.get("_source", "services.step_thumbnail"),
        "raw": out,
    }
