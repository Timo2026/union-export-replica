# -*- coding: utf-8 -*-
import os, math, uuid
from .step_generator import DENSITY, PART_GENERATORS

def _stl_path():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    d = os.path.join(root, "data", "step")
    os.makedirs(d, exist_ok=True)
    return d

def _emit_cylinder_stl(diameter, height, path, segments=40):
    r = diameter / 2.0
    pts = [(r * math.cos(2 * math.pi * i / segments), r * math.sin(2 * math.pi * i / segments)) for i in range(segments)]
    z0, z1 = 0.0, height
    tris = []
    def tri(a, b, c):
        tris.append((a, b, c))
    # bottom fan
    for i in range(segments):
        tri((0, 0, z0), (pts[i][0], pts[i][1], z0), (pts[(i + 1) % segments][0], pts[(i + 1) % segments][1], z0))
    # top fan
    for i in range(segments):
        tri((0, 0, z1), (pts[(i + 1) % segments][0], pts[(i + 1) % segments][1], z1), (pts[i][0], pts[i][1], z1))
    # side quads -> 2 tris each
    for i in range(segments):
        j = (i + 1) % segments
        a = (pts[i][0], pts[i][1], z0); b = (pts[j][0], pts[j][1], z0)
        c = (pts[j][0], pts[j][1], z1); d = (pts[i][0], pts[i][1], z1)
        tri(a, b, c); tri(a, c, d)
    _write_stl(tris, path)
    return path

def _emit_box_stl(w, h, t, path):
    x0, x1 = -w / 2.0, w / 2.0
    y0, y1 = -h / 2.0, h / 2.0
    z0, z1 = 0.0, t
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
         (2, 3, 7, 6), (3, 0, 4, 7)]
    tris = []
    for q in f:
        tris.append((v[q[0]], v[q[1]], v[q[2]]))
        tris.append((v[q[0]], v[q[2]], v[q[3]]))
    _write_stl(tris, path)
    return path

def _write_stl(tris, path):
    with open(path, "w", encoding="ascii") as f:
        f.write("solid cnc_part\n")
        for a, b, c in tris:
            f.write("  facet normal 0 0 0\n    outer loop\n")
            for p in (a, b, c):
                f.write("      vertex %.6f %.6f %.6f\n" % p)
            f.write("    endloop\n  endfacet\n")
        f.write("endsolid cnc_part\n")

def generate_part(part_type, params):
    params = params or {}
    pt = PART_GENERATORS.get(part_type, part_type)
    fid = uuid.uuid4().hex[:10]
    step_file = "%s_%s.step" % (pt, fid)
    stl_file = "%s_%s.stl" % (pt, fid)
    d = _stl_path()
    stl_path = os.path.join(d, stl_file)
    step_path = os.path.join(d, step_file)
    # write a stub STEP (text) + real STL
    try:
        with open(step_path, "w", encoding="ascii") as f:
            f.write("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('procedural'),'2;1');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
    except Exception:
        pass

    def g(key, default):
        try:
            v = params.get(key)
            return float(v) if v is not None else default
        except Exception:
            return default

    bbox = [100.0, 100.0, 20.0]
    vol_cm3 = 0.0
    if pt in ("flange", "ring", "sleeve"):
        od = g("od", g("d", 100.0)); id_ = g("id", 0.0); th = g("thickness", g("t", 20.0))
        height = g("length", th) if pt == "sleeve" else th
        _emit_cylinder_stl(od, height, stl_path)
        bbox = [od, od, height]
        vol_mm3 = math.pi / 4.0 * (od * od - id_ * id_) * height
        vol_cm3 = vol_mm3 / 1000.0
    elif pt in ("shaft", "round", "cylinder"):
        dia = g("d", g("od", 30.0)); length = g("length", 100.0)
        _emit_cylinder_stl(dia, length, stl_path)
        bbox = [dia, dia, length]
        vol_cm3 = (math.pi / 4.0 * dia * dia * length) / 1000.0
    else:  # plate / box / bracket / step_block
        w = g("w", 100.0); h = g("h", 50.0); t = g("t", g("thickness", 10.0))
        _emit_box_stl(w, h, t, stl_path)
        bbox = [w, h, t]
        vol_cm3 = (w * h * t) / 1000.0

    material = params.get("material", "6061")
    density = DENSITY.get(material, 2.8)
    weight_g = vol_cm3 * density
    return {
        "part_type": pt, "step_file": step_file, "stl_file": stl_file,
        "stl_url": "/api/preview/" + stl_file,
        "step_url": "/api/download/" + step_file,
        "bounding_box_mm": [round(b, 2) for b in bbox],
        "volume_mm3": round(vol_cm3 * 1000, 2),
        "volume_cm3": round(vol_cm3, 3),
        "estimated_weight_g": round(weight_g, 2),
        "engine": "procedural-pure-python",
        "volume_warning": False, "volume_warning_reason": "",
    }

def get_engine_status():
    return {"engine": "procedural", "backend": "pure-python-stl", "trimesh": _has_trimesh()}

def _has_trimesh():
    try:
        import trimesh  # noqa
        return True
    except Exception:
        return False
