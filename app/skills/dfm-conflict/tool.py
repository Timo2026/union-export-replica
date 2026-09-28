"""dfm-conflict skill — 委托 adapters/timo_adapter.ConflictChecker (v6.0.0 最小补全)."""
from __future__ import annotations
from typing import Any, Dict


def run(ctx, material: str = "", surface: str = "", **kwargs) -> Dict[str, Any]:
    """DFM 工艺冲突检测. 委托 Timo 内核 ConflictChecker."""
    if not material or not surface:
        return {"ok": False, "skill": "dfm-conflict", "iron_rule": "deterministic",
                "error": "material and surface required"}
    try:
        from adapters.timo_adapter import TimoAdapter
        # 复用现有 ctrl 模式
        timo = getattr(ctx, "timo", None) or _get_timo_from_ctx(ctx)
        if timo is None:
            return {"ok": False, "skill": "dfm-conflict", "iron_rule": "deterministic",
                    "error": "timo adapter not available in ctx"}
        res = timo.conflict_check(material, surface)
        valid = res.get("valid", True)
        return {
            "ok": True, "skill": "dfm-conflict", "iron_rule": "deterministic",
            "valid": valid, "conflicts": res.get("conflicts", []),
            "warnings": res.get("warnings", []), "total_issues": len(res.get("conflicts", [])) + len(res.get("warnings", [])),
            "_source": res.get("_source", "timo.conflict_check"),
        }
    except Exception as e:
        return {"ok": False, "skill": "dfm-conflict", "iron_rule": "deterministic",
                "error": repr(e)}


def _get_timo_from_ctx(ctx):
    try:
        return ctx.get_ctrl().timo
    except Exception:
        return None
