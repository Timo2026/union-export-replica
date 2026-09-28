"""check_dfm — Timo ConflictChecker (确定性, 铁律①)."""
from __future__ import annotations

from typing import Any, Dict


def run(ctx, material: str = "", surface: str = "", process: str = "",
        tolerance_grade: str = "", rfq: Dict[str, Any] | None = None,
        **kwargs) -> Dict[str, Any]:
    rfq = dict(rfq or ctx.scratch.get("rfq") or {})
    material = material or rfq.get("material") or ""
    surface = surface or rfq.get("surface") or ""
    tolerance_grade = tolerance_grade or rfq.get("tolerance_grade") or ""
    if not material:
        return {"ok": False, "skill": "check_dfm", "error": "material required"}
    ctrl = ctx.get_ctrl()
    timo = ctx.timo or getattr(ctrl, "timo", None)
    try:
        out = timo.conflict_check(material=material, surface=surface,
                                  tolerance_grade=tolerance_grade)
    except Exception as e:  # noqa
        return {"ok": False, "skill": "check_dfm", "error": repr(e), "iron_rule": "deterministic"}
    if not isinstance(out, dict):
        out = {"valid": bool(out), "raw": out}
    conflicts = out.get("conflicts") or []
    warnings = out.get("warnings") or []
    valid = out.get("valid")
    if valid is None:
        valid = not conflicts
    result = {
        "ok": True,
        "skill": "check_dfm",
        "iron_rule": "deterministic",
        "valid": bool(valid),
        "conflicts": conflicts,
        "warnings": warnings,
        "total_issues": out.get("total_issues", len(conflicts) + len(warnings)),
        "dfm_valid": bool(valid),
        "_source": out.get("_source", "timo:conflict_check"),
        "raw": out,
    }
    ctx.scratch["dfm"] = result
    return result
