"""step-analysis skill — 委托 adapters/timo_adapter.step_geometry (v6.0.0 最小补全)."""
from __future__ import annotations
from typing import Any, Dict


def run(ctx, path: str = "", material: str = "6061", **kwargs) -> Dict[str, Any]:
    """STEP 几何解析 (OCP B-rep). 委托 Timo 内核."""
    if not path:
        return {"ok": False, "skill": "step-analysis", "iron_rule": "deterministic",
                "error": "path required"}
    try:
        from adapters.timo_adapter import TimoAdapter
        timo = getattr(ctx, "timo", None) or _get_timo_from_ctx(ctx)
        if timo is None:
            return {"ok": False, "skill": "step-analysis", "iron_rule": "deterministic",
                    "error": "timo adapter not available in ctx"}
        geo = timo.step_geometry(path, material=material)
        feats = timo.step_features(path, material=material) if hasattr(timo, "step_features") else {}
        return {
            "ok": True, "skill": "step-analysis", "iron_rule": "deterministic",
            "bbox_mm": geo.get("bbox_mm") or geo.get("bbox"),
            "volume_mm3": geo.get("volume_mm3"),
            "weight_kg": geo.get("weight_kg"),
            "surface_area_dm2": geo.get("surface_area_dm2"),
            "max_dim_mm": geo.get("max_dim_mm"),
            "features": feats if isinstance(feats, dict) else {},
            "_source": geo.get("_source", "timo.step_geometry"),
        }
    except Exception as e:
        return {"ok": False, "skill": "step-analysis", "iron_rule": "deterministic",
                "error": repr(e)}


def _get_timo_from_ctx(ctx):
    try:
        return ctx.get_ctrl().timo
    except Exception:
        return None
