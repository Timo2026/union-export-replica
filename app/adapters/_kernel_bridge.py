"""_kernel_bridge.py — 离线确定性内核桥.

由 TimoAdapter 用引擎自带 .venv python 以子进程方式调用 (PYTHONPATH=engine_src)。
从 stdin 读 {"func": "...", "args": {...}}, 直接调用真实引擎函数, 向 stdout 打印单行 JSON。

支持 func:
  conflict_check : src.neuro_core.conflict_check.ConflictChecker.check
  calc_quote     : app.main_lite.calc_quote
只用真实代码, 无任何示意/硬编码系数。
"""
import json
import sys


def _conflict_check(args):
    from src.neuro_core.conflict_check import ConflictChecker
    cc = ConflictChecker()
    r = cc.check({"material": args.get("material", ""),
                  "surface_treatment": args.get("surface", args.get("surface_treatment", ""))})
    return {"valid": r["valid"], "conflicts": r["conflicts"],
            "warnings": r["warnings"], "total_issues": r["total_issues"]}


def _calc_quote(args):
    from app.main_lite import calc_quote
    kw = {k: v for k, v in args.items() if k in {
        "material", "surface", "quantity", "weight_kg", "max_dim_mm",
        "surface_area_dm2", "tolerance", "roughness_ra", "thread_count",
        "dim_x", "dim_y", "dim_z", "price_mode"}}
    return calc_quote(**kw)


def _step_geometry(args):
    """真实 OCP B-rep: bbox + 体积 + 按材料密度算重量 (供几何驱动报价)."""
    from src.runtime.step_parser import (extract_bbox_from_step,
                                         get_material_density)
    path = args.get("path", "")
    material = args.get("material", "6061")
    bb = extract_bbox_from_step(path) or {}
    vol_mm3 = bb.get("volume_mm3")
    density = get_material_density(material) or 2.7
    weight_kg = round((vol_mm3 / 1000.0) * density / 1000.0, 4) if vol_mm3 else None
    dims = [bb.get("dim_x"), bb.get("dim_y"), bb.get("dim_z")]
    dims = [d for d in dims if d]
    # 表面积粗估 (dm2): 用 bbox 六面 (保守上界)
    area_dm2 = None
    if len(dims) == 3:
        l, w, h = dims
        area_dm2 = round(2 * (l * w + l * h + w * h) / 10000.0, 4)
    return {"bbox_mm": dims, "max_dim_mm": max(dims) if dims else None,
            "volume_mm3": vol_mm3, "volume_source": bb.get("volume_source"),
            "density": density, "weight_kg": weight_kg,
            "surface_area_dm2": area_dm2, "file_size": bb.get("file_size"),
            "error": bb.get("error")}


def _step_features(args):
    """C1 特征实测 (孔/壁厚/圆角). 有 5s 硬超时, 大文件返回 partial; 失败返回 error 不抛。"""
    try:
        from src.runtime.feature_extractor import extract_features
        r = extract_features(args.get("path", ""))
        if r is None:
            return {"ok": False, "error": "extract_features returned None"}
        hs = r.get("hole_summary", {}) or {}
        return {"ok": True,
                "hole_count": hs.get("count"),
                "thread_suspect": r.get("stats", {}).get("thread_suspect"),
                "min_wall_mm": (r.get("min_wall_mm") or {}).get("value")
                if isinstance(r.get("min_wall_mm"), dict) else r.get("min_wall_mm"),
                "fillets": r.get("fillets"),
                "plane_area_dm2": r.get("plane_area_dm2"),
                "partial": r.get("stats", {}).get("partial", False),
                "confidence": r.get("confidence")}
    except Exception as e:  # noqa
        return {"ok": False, "error": repr(e)}


_DISPATCH = {"conflict_check": _conflict_check, "calc_quote": _calc_quote,
             "step_geometry": _step_geometry, "step_features": _step_features}


def main():
    raw = sys.stdin.read()
    req = json.loads(raw)
    func = req.get("func")
    args = req.get("args", {}) or {}
    if func not in _DISPATCH:
        print(json.dumps({"error": f"unknown func: {func}"}, ensure_ascii=False))
        sys.exit(2)
    try:
        out = _DISPATCH[func](args)
    except Exception as e:  # noqa
        import traceback
        print(json.dumps({"error": repr(e), "tb": traceback.format_exc()[-800:]}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
