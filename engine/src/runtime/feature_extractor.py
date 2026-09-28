# -*- coding: utf-8 -*-
"""C1 DFM 特征实测：只读遍历 STEP B-rep 拓扑，提取孔/壁厚/圆角/内直角。

定位：闭合 DFM 人工确认项中的「最小壁厚 / 孔径 / 孔深」三项（装夹基准仍留人工）。

关键设计（详见 docs/DFM特征实测feature_extractor详细设计.md）：
- 纯 OCP(OpenCASCADE) 拓扑遍历，不做几何写入，不修改客户原始 STEP。
- 壁厚：复用 BRepMesh 网格化 + 纯 numpy 手写「点到三角面距离」。
  ⚠️ 禁止 scipy / trimesh.proximity.ProximityQuery / trimesh.convex_hull
  （本环境 scipy 不可用会静默失败）。采样点取实体内部点（非表面/包围盒边缘）。
- 任何异常一律返回 None（绝不抛异常），保证上传/DFM 链路向后兼容。

输出 schema 见设计文档 §2.2。
"""
import math
import time
from threading import Thread

# ─────────────────────────────────────────────────────────────
# 模块级常量（禁止硬编码：所有阈值/采样点/分位/超时集中于此）
# ─────────────────────────────────────────────────────────────
_THROUGH_TOL_MM = 0.05        # 通孔判定：|孔深 − 轴向板厚| < 此值(mm)
_AXIS_PARALLEL_DOT = 0.999    # 轴平行判定：|dot(dir1,dir2)| > 此值
_AXIS_COLINEAR_TOL_MM = 0.01  # 阶梯孔聚簇：两平行轴线的间距 < 此值(mm)
_TIMEOUT_S = 5.0              # 硬超时(秒)，超时返回 partial
_MESH_DEFLECTION = 0.2        # 网格化 deflection(mm)，收紧以获得更准壁厚
_INTERIOR_SAMPLE_N = 300      # 壁厚内部采样点数(每轮)
_INTERIOR_RETRY_N = 6         # 内部采样最多重试轮数
_MIN_INTERIOR_POINTS = 50     # 内部采样点下限，低于此值壁厚判 None
_SURFACE_CLEARANCE_MM = 0.5   # 距表面清除距离：丢弃距表面小于此值的采样点(噪声，非实体深处)
_MIN_WALL_QUANTILE = 0.5      # 壁厚取「点面距」0.5% 分位(百分比，近似最小值)
_SOLID_CLASSIFIER_TOL = 0.01   # SolidClassifier 空间判定容差(mm)
_UNIT_SUSPECT_MAX_MM = 2000.0  # bbox 任一维度超过此值 → 单位疑点(米/毫米陷阱)
_RIGHT_ANGLE_DOT_TOL = 0.087   # cos(85°)：两平面法向 |dot| 低于此值判≈垂直(直角)
_CONCAVE_PROBE_EPS_MM = 0.1    # 凹凸判定探针偏移量(mm)，沿角平分方向
_THREAD_SUSPECT_TOL_MM = 0.2   # 螺纹底孔直径匹配容差(mm)

# 常见公制螺纹底孔直径(mm)：螺纹规格 → 底孔直径。仅用于 thread_suspect 提示，
# 不冒充螺纹参数（B-rep 中螺纹通常被建模为光圆柱）。
_TAP_DRILL_SIZES_MM = (
    (1.6, "M2"), (2.05, "M2.5"), (2.5, "M3"), (3.3, "M4"),
    (4.2, "M5"), (5.0, "M6"), (6.8, "M8"), (8.5, "M10"),
    (10.2, "M12"), (12.0, "M14"), (14.0, "M16"), (17.5, "M20"),
)


def extract_features(step_path):
    """提取 STEP 特征（只读）。任何异常 → None，绝不抛异常。

    返回 dict（schema §2.2）或 None（文件缺失/解析失败/损坏）。
    硬超时达 _TIMEOUT_S 时返回 partial 结果（stats.partial=True）。
    """
    if not step_path:
        return None
    try:
        holder = {}

        def _worker():
            try:
                holder["result"] = _extract_impl(str(step_path))
            except Exception as exc:  # noqa: BLE001 —— 降级承诺：绝不外抛
                print(f"[feature_extractor] worker failed: {exc}", flush=True)
                holder["result"] = None

        t = Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=_TIMEOUT_S)
        if t.is_alive():
            print("[feature_extractor] hard timeout, return partial", flush=True)
            return _partial_timeout()
        return holder.get("result")
    except Exception as exc:  # noqa: BLE001
        print(f"[feature_extractor] failed: {exc}", flush=True)
        return None


# ─────────────────────────────────────────────────────────────
# 主实现
# ─────────────────────────────────────────────────────────────
def _extract_impl(step_path):
    import os
    if not os.path.exists(step_path):
        return None

    t0 = time.time()

    # 读入（复用 step_parser 已验证的毫米制路径，规避 cascadion 米制陷阱）
    shape = _read_step_shape(step_path)
    if shape is None:
        return None

    xmin, ymin, zmin, xmax, ymax, zmax = _shape_bbox(shape)
    dims = (xmax - xmin, ymax - ymin, zmax - zmin)
    warnings = []
    unknowns = []
    confidence = "high"

    unit_suspect = max(dims) > _UNIT_SUSPECT_MAX_MM
    if unit_suspect:
        warnings.append("bbox 最大维度超 2000mm，可能存在米/毫米单位疑点")
        confidence = "medium"

    # 面级分类统计
    face_stats = _classify_faces(shape, xmin, ymin, zmin, xmax, ymax, zmax)
    face_count = face_stats["face_count"]
    freeform_faces = face_stats["freeform_face_count"]
    if freeform_faces > 0:
        warnings.append(f"{freeform_faces} 个自由曲面，孔可能漏检，置信度降级")
        confidence = "medium"

    # 孔提取（圆柱面）
    holes = _extract_holes(shape, dims)
    hole_summary = _hole_summary(holes)
    if holes and any(_tap_suspect(h["d_mm"]) for h in holes):
        n_suspect = sum(1 for h in holes if h["thread_suspect"])
        warnings.append(
            f"thread_suspect: {n_suspect} 个光圆柱孔可能为螺纹底孔，需按图纸确认规格"
        )

    # 圆角（Torus 过渡面）
    fillets = _extract_fillets(shape)

    # 内直角（凹直角边）
    right_angle_edges, rae_note = _count_concave_right_angles(shape)
    if rae_note:
        warnings.append(rae_note)

    # 平面面积(dm²)
    plane_area_dm2 = _plane_area_dm2(shape)

    # 最小壁厚（纯 numpy 点面距，内部采样）
    min_wall_mm = _min_wall_numpy(shape, (xmin, ymin, zmin, xmax, ymax, zmax), dims)
    if min_wall_mm is None:
        unknowns.append("最小壁厚（内部采样不足或网格化失败）")
        if confidence == "high":
            confidence = "medium"

    if not holes:
        unknowns.append("孔")
    if fillets is None or fillets.get("torus_count", 0) == 0:
        unknowns.append("圆角(Torus 过渡面，Chamfer 倒角不在本期范围)")

    if face_stats["cone_face_count"] > 0:
        unknowns.append(
            f"{face_stats['cone_face_count']} 个锥面(沉头/倒角)未解析为独立孔径特征"
        )

    duration_ms = int((time.time() - t0) * 1000)

    return {
        "holes": holes,
        "hole_summary": hole_summary,
        "min_wall_mm": min_wall_mm,
        "fillets": fillets,
        "right_angle_edges": right_angle_edges,
        "plane_area_dm2": plane_area_dm2,
        "stats": {
            "face_count": face_count,
            "cyl_face_count": face_stats["cyl_face_count"],
            "torus_face_count": face_stats["torus_face_count"],
            "cone_face_count": face_stats["cone_face_count"],
            "plane_face_count": face_stats["plane_face_count"],
            "freeform_face_count": freeform_faces,
            "solid_count": face_stats["solid_count"],
            "duration_ms": duration_ms,
            "partial": False,
        },
        "confidence": confidence,
        "warnings": warnings,
        "unknowns": unknowns,
    }


def _partial_timeout():
    """硬超时降级：返回空 features + partial 标记。"""
    return {
        "holes": [],
        "hole_summary": {"count": 0, "min_d_mm": None, "max_ld_ratio": None,
                         "by_diameter": {}},
        "min_wall_mm": None,
        "fillets": None,
        "right_angle_edges": None,
        "plane_area_dm2": None,
        "stats": {"face_count": 0, "cyl_face_count": 0, "torus_face_count": 0,
                  "cone_face_count": 0, "plane_face_count": 0,
                  "freeform_face_count": 0, "solid_count": 0,
                  "duration_ms": int(_TIMEOUT_S * 1000), "partial": True},
        "confidence": "low",
        "warnings": [f"特征提取超过 {_TIMEOUT_S}s 硬超时，返回部分结果"],
        "unknowns": ["孔", "最小壁厚", "圆角", "内直角"],
    }


# ─────────────────────────────────────────────────────────────
# OCP 基础工具函数
# ─────────────────────────────────────────────────────────────
def _read_step_shape(step_path):
    from OCP.STEPControl import STEPControl_Reader
    reader = STEPControl_Reader()
    if reader.ReadFile(step_path) != 1:
        return None
    if reader.TransferRoots() == 0:
        return None
    shape = reader.OneShape()
    if shape.IsNull():
        return None
    return shape


def _shape_bbox(shape):
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    box = Bnd_Box()
    add_fn = getattr(BRepBndLib, "AddOptimal_s", None) or getattr(BRepBndLib, "Add_s")
    add_fn(shape, box)
    return box.Get()


def _classify_faces(shape, xmin, ymin, zmin, xmax, ymax, zmax):
    """遍历面分类统计，返回各类面计数 + 实体数。"""
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType

    stats = {"face_count": 0, "cyl_face_count": 0, "torus_face_count": 0,
             "cone_face_count": 0, "plane_face_count": 0, "freeform_face_count": 0,
             "solid_count": 0}

    exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        t = BRepAdaptor_Surface(face).GetType()
        stats["face_count"] += 1
        if t == GeomAbs_SurfaceType.GeomAbs_Cylinder:
            stats["cyl_face_count"] += 1
        elif t == GeomAbs_SurfaceType.GeomAbs_Torus:
            stats["torus_face_count"] += 1
        elif t == GeomAbs_SurfaceType.GeomAbs_Cone:
            stats["cone_face_count"] += 1
        elif t == GeomAbs_SurfaceType.GeomAbs_Plane:
            stats["plane_face_count"] += 1
        else:
            stats["freeform_face_count"] += 1
        exp.Next()

    exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID)
    while exp.More():
        stats["solid_count"] += 1
        exp.Next()
    return stats


def _face_bbox_projection(face, axis_vec):
    """面 bbox 沿给定轴向的投影长度(用于孔深)。"""
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    box = Bnd_Box()
    add_fn = getattr(BRepBndLib, "AddOptimal_s", None) or getattr(BRepBndLib, "Add_s")
    add_fn(face, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()

    ax, ay, az = axis_vec
    norm = math.sqrt(ax * ax + ay * ay + az * az) or 1.0
    ax, ay, az = ax / norm, ay / norm, az / norm

    corners = (
        (xmin, ymin, zmin), (xmax, ymin, zmin), (xmin, ymax, zmin), (xmax, ymax, zmin),
        (xmin, ymin, zmax), (xmax, ymin, zmax), (xmin, ymax, zmax), (xmax, ymax, zmax),
    )
    proj = [x * ax + y * ay + z * az for (x, y, z) in corners]
    return max(proj) - min(proj)


# ─────────────────────────────────────────────────────────────
# 孔提取
# ─────────────────────────────────────────────────────────────
def _extract_holes(shape, dims):
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_ShapeEnum, TopAbs_Orientation
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType

    holes = []
    exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        ad = BRepAdaptor_Surface(face)
        if ad.GetType() != GeomAbs_SurfaceType.GeomAbs_Cylinder:
            exp.Next()
            continue

        cyl = ad.Cylinder()
        d_mm = round(float(cyl.Radius()) * 2.0, 4)
        axis = cyl.Axis()
        origin = axis.Location()
        direction = axis.Direction()
        dir_vec = (float(direction.X()), float(direction.Y()), float(direction.Z()))

        # 内孔 vs 外圆柱：面朝向 REVERSED 判内孔（孔内表面）
        is_inner = face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED

        # 孔深 = 面 bbox 沿轴向投影长度
        depth_mm = round(_face_bbox_projection(face, dir_vec), 4)

        # 通/盲：|孔深 − 沿轴板厚| < 容差 → 通孔
        plate_thickness = _bbox_projection(dims, dir_vec)
        through = abs(depth_mm - plate_thickness) < _THROUGH_TOL_MM

        hole = {
            "d_mm": d_mm,
            "depth_mm": depth_mm,
            "ld_ratio": round(depth_mm / d_mm, 3) if d_mm else None,
            "through": bool(through),
            "axis": [round(v, 6) for v in dir_vec],
            "thread_suspect": _tap_suspect(d_mm),
            "inner": bool(is_inner),
            "segment_group": None,
            # 内部临时字段（聚簇用，输出前删除）
            "_axis_abs": (abs(dir_vec[0]), abs(dir_vec[1]), abs(dir_vec[2])),
            "_axis_origin": (float(origin.X()), float(origin.Y()), float(origin.Z())),
        }
        holes.append(hole)
        exp.Next()

    _cluster_segment_groups(holes)
    _finalize_holes(holes)
    return holes


def _bbox_projection(dims, axis_vec):
    """整块 bbox 的 3 个维度沿轴向的投影(近似该方向总长)。"""
    ax, ay, az = (abs(axis_vec[0]), abs(axis_vec[1]), abs(axis_vec[2]))
    norm = math.sqrt(ax * ax + ay * ay + az * az) or 1.0
    ax, ay, az = ax / norm, ay / norm, az / norm
    return dims[0] * ax + dims[1] * ay + dims[2] * az


def _tap_suspect(d_mm):
    for drill, _spec in _TAP_DRILL_SIZES_MM:
        if abs(d_mm - drill) <= _THREAD_SUSPECT_TOL_MM:
            return True
    return False


def _axes_colinear(h1, h2):
    a1 = h1["_axis_abs"]
    a2 = h2["_axis_abs"]
    dot = abs(a1[0] * a2[0] + a1[1] * a2[1] + a1[2] * a2[2])
    if dot < _AXIS_PARALLEL_DOT:
        return False
    # 平行线之间距 = |(P2-P1) × dir|（dir 已归一/模=1）
    p1 = h1["_axis_origin"]
    p2 = h2["_axis_origin"]
    dx, dy, dz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
    # 用 a1（单位方向，abs 后仍为单位向量的分量符号组合，取带符号方向）
    ax, ay, az = a1
    cross = (
        dy * az - dz * ay,
        dz * ax - dx * az,
        dx * ay - dy * ax,
    )
    dist = math.sqrt(cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2)
    return dist < _AXIS_COLINEAR_TOL_MM


def _cluster_segment_groups(holes):
    """轴共线且半径不同 → 聚簇为阶梯孔组。O(n²) 小数据无压力。"""
    n = len(holes)
    if n < 2:
        return
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if _axes_colinear(holes[i], holes[j]):
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    seg = 0
    for members in groups.values():
        radii = {holes[i]["d_mm"] for i in members}
        if len(members) > 1 and len(radii) > 1:
            seg += 1
            label = f"g{seg}"
            for i in members:
                holes[i]["segment_group"] = label


def _finalize_holes(holes):
    for h in holes:
        h.pop("_axis_abs", None)
        h.pop("_axis_origin", None)


def _hole_summary(holes):
    if not holes:
        return {"count": 0, "min_d_mm": None, "max_ld_ratio": None, "by_diameter": {}}
    diameters = [h["d_mm"] for h in holes]
    ld_ratios = [h["ld_ratio"] for h in holes if h["ld_ratio"] is not None]
    by_diameter = {}
    for d in diameters:
        key = f"{d:g}"
        by_diameter[key] = by_diameter.get(key, 0) + 1
    return {
        "count": len(holes),
        "min_d_mm": round(min(diameters), 4),
        "max_ld_ratio": round(max(ld_ratios), 3) if ld_ratios else None,
        "by_diameter": by_diameter,
    }


# ─────────────────────────────────────────────────────────────
# 圆角 / 内直角
# ─────────────────────────────────────────────────────────────
def _extract_fillets(shape):
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType

    minor_radii = []
    exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        ad = BRepAdaptor_Surface(face)
        if ad.GetType() == GeomAbs_SurfaceType.GeomAbs_Torus:
            minor_radii.append(float(ad.Torus().MinorRadius()))
        exp.Next()
    if not minor_radii:
        return {"min_r_mm": None, "torus_count": 0}
    return {"min_r_mm": round(min(minor_radii), 4), "torus_count": len(minor_radii)}


def _count_concave_right_angles(shape):
    """统计内直角(凹直角边)数量。近似实现：相邻平面夹角≈90° 且为凹边。

    凹凸判定用 SolidClassifier 沿角平分方向探针：探针点在实体内 → 凹边(内直角)。
    """
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopAbs import TopAbs_ShapeEnum, TopAbs_Orientation, TopAbs_State
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.BRep import BRep_Tool
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt

    # 边 → 相邻面 映射
    emap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(
        shape, TopAbs_ShapeEnum.TopAbs_EDGE, TopAbs_ShapeEnum.TopAbs_FACE, emap
    )

    def _face_normal_outward(face):
        # 仅处理平面（内直角 = 相邻两平面夹角≈90°）；gp_Ax3.Direction() 即平面法向
        ad = BRepAdaptor_Surface(face)
        if ad.GetType() != GeomAbs_SurfaceType.GeomAbs_Plane:
            return None
        d = ad.Plane().Axis().Direction()
        n = (float(d.X()), float(d.Y()), float(d.Z()))
        if face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
            n = (-n[0], -n[1], -n[2])
        return n

    def _edge_midpoint(edge):
        u0, u1 = 0.0, 0.0
        curve = BRep_Tool.Curve_s(edge, u0, u1)
        if curve is None:
            return None
        p = curve.Value((u0 + u1) / 2.0)
        return (float(p.X()), float(p.Y()), float(p.Z()))

    clf = BRepClass3d_SolidClassifier()
    clf.Load(shape)

    concave_count = 0
    total_right = 0
    classifier_ok = True

    exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_EDGE)
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        faces = emap.FindFromKey(edge)
        if faces.Size() != 2:
            exp.Next()
            continue
        f1 = TopoDS.Face_s(faces.First())
        f2 = TopoDS.Face_s(faces.Last())
        n1 = _face_normal_outward(f1)
        n2 = _face_normal_outward(f2)
        if n1 is None or n2 is None:
            exp.Next()
            continue
        dot = n1[0] * n2[0] + n1[1] * n2[1] + n1[2] * n2[2]
        if abs(dot) > _RIGHT_ANGLE_DOT_TOL:
            exp.Next()
            continue

        # 直角边
        total_right += 1
        mid = _edge_midpoint(edge)
        if mid is None:
            exp.Next()
            continue
        # 角平分方向 = n1 + n2（直角时两法向接近正交，和向量指向外侧）
        bn = (n1[0] + n2[0], n1[1] + n2[1], n1[2] + n2[2])
        bnorm = math.sqrt(bn[0] ** 2 + bn[1] ** 2 + bn[2] ** 2)
        if bnorm < 1e-9:
            exp.Next()
            continue
        bx, by, bz = bn[0] / bnorm, bn[1] / bnorm, bn[2] / bnorm
        probe = gp_Pnt(
            mid[0] + bx * _CONCAVE_PROBE_EPS_MM,
            mid[1] + by * _CONCAVE_PROBE_EPS_MM,
            mid[2] + bz * _CONCAVE_PROBE_EPS_MM,
        )
        try:
            clf.Perform(probe, _SOLID_CLASSIFIER_TOL)
            if clf.State() == TopAbs_State.TopAbs_IN:
                concave_count += 1
        except Exception:
            classifier_ok = False
        exp.Next()

    note = None
    if not classifier_ok:
        note = "内直角凹凸判定依赖 SolidClassifier，部分探针失败，计数可能不完整"
    return concave_count, note


# 注意：上面的 _face_normal_outward 对 Plane 用 ad.Plane().Axis()，但对 Axis 需要
# 取 Ax1 的 Direction。此处 Plane() 返回 gp_Pln，其 Axis() 是 gp_Ax3，Direction 为法向。

# ─────────────────────────────────────────────────────────────
# 平面面积
# ─────────────────────────────────────────────────────────────
def _plane_area_dm2(shape):
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    area_sum = 0.0
    exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        if BRepAdaptor_Surface(face).GetType() == GeomAbs_SurfaceType.GeomAbs_Plane:
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, props)
            area_sum += abs(float(props.Mass()))
        exp.Next()
    return round(area_sum / 10000.0, 4)  # mm² → dm²


# ─────────────────────────────────────────────────────────────
# 最小壁厚（纯 numpy 点到三角面距离）
# ─────────────────────────────────────────────────────────────
def _min_wall_numpy(shape, bbox, dims):
    try:
        import numpy as np
        verts, tris = _mesh_triangulation(shape, _MESH_DEFLECTION)
        if verts is None or verts.shape[0] < 4 or tris.shape[0] < 1:
            return None
        interior = _sample_interior_points(shape, bbox, _INTERIOR_SAMPLE_N)
        if interior is None or interior.shape[0] < _MIN_INTERIOR_POINTS:
            return None
        dists = _points_to_tris_min_dist_numpy(interior, verts, tris)
        # 丢弃贴表面/孔壁的噪声点(本质是网格化精度以下的"表面"点，会使距离趋近 0)
        deep = dists[dists >= _SURFACE_CLEARANCE_MM]
        if deep.shape[0] < _MIN_INTERIOR_POINTS:
            return None
        # 单侧最近面距离 → 壁厚(两侧表面间距) = 2 × 距离；取 0.5% 分位近似最小值
        value = 2.0 * float(np.percentile(deep, _MIN_WALL_QUANTILE))
        return {
            "value": round(value, 3),
            "method": "numpy_point_face",
            "confidence": "approximate",
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[feature_extractor] min_wall failed: {exc}", flush=True)
        return None


def _mesh_triangulation(shape, deflection):
    import numpy as np
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRep import BRep_Tool
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    mesh = BRepMesh_IncrementalMesh(shape, deflection)
    mesh.Perform()

    all_verts = []
    all_tris = []
    exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None or tri.NbTriangles() < 1:
            exp.Next()
            continue
        trsf = loc.Transformation()
        base = len(all_verts)
        for i in range(1, tri.NbNodes() + 1):
            p = tri.Node(i).Transformed(trsf)
            all_verts.append((float(p.X()), float(p.Y()), float(p.Z())))
        for i in range(1, tri.NbTriangles() + 1):
            n1, n2, n3 = tri.Triangle(i).Get()
            all_tris.append((base + n1 - 1, base + n2 - 1, base + n3 - 1))
        exp.Next()

    if not all_verts or not all_tris:
        return None, None
    return (
        np.asarray(all_verts, dtype=np.float64),
        np.asarray(all_tris, dtype=np.int64),
    )


def _sample_interior_points(shape, bbox, n_target):
    import numpy as np
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_State
    from OCP.gp import gp_Pnt

    xmin, ymin, zmin, xmax, ymax, zmax = bbox
    rng = np.random.default_rng(42)  # 固定种子，可复现

    clf = BRepClass3d_SolidClassifier()
    clf.Load(shape)

    pts = []
    for _ in range(_INTERIOR_RETRY_N):
        xs = rng.uniform(xmin, xmax, n_target)
        ys = rng.uniform(ymin, ymax, n_target)
        zs = rng.uniform(zmin, zmax, n_target)
        for x, y, z in zip(xs, ys, zs):
            p = gp_Pnt(float(x), float(y), float(z))
            try:
                clf.Perform(p, _SOLID_CLASSIFIER_TOL)
            except Exception:
                continue
            if clf.State() == TopAbs_State.TopAbs_IN:
                pts.append((float(x), float(y), float(z)))
        if len(pts) >= n_target:
            break

    if not pts:
        return None
    return np.asarray(pts[:n_target], dtype=np.float64)


def _points_to_tris_min_dist_numpy(points, verts, tris):
    """每个采样点到所有三角形的最小距离(纯 numpy，无 scipy 依赖)。

    采用 Ericson(2004)「Real-Time Collision Detection」最近点算法，向量化到
    T 个三角形；外层循环 K 个采样点，逐点求到 T 个三角形的最小距离。
    """
    import numpy as np

    v0 = verts[tris[:, 0]]
    v1 = verts[tris[:, 1]]
    v2 = verts[tris[:, 2]]

    n_points = points.shape[0]
    result = np.empty(n_points, dtype=np.float64)
    for k in range(n_points):
        p = points[k]
        result[k] = np.sqrt(np.min(_point_tris_sqdist(p, v0, v1, v2)))
    return result


def _point_tris_sqdist(p, a, b, c):
    """p(3,) 到 T 个三角形 (a,b,c 各为 (T,3)) 的距离平方，返回 (T,)。"""
    import numpy as np

    ab = b - a
    ac = c - a
    ap = p - a
    d1 = np.einsum("ij,ij->i", ab, ap)
    d2 = np.einsum("ij,ij->i", ac, ap)

    bp = p - b
    d3 = np.einsum("ij,ij->i", ab, bp)
    d4 = np.einsum("ij,ij->i", ac, bp)

    cp = p - c
    d5 = np.einsum("ij,ij->i", ab, cp)
    d6 = np.einsum("ij,ij->i", ac, cp)

    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2

    # 默认：三角形内部区域
    denom = va + vb + vc
    safe = denom != 0
    v = np.zeros_like(d1)
    w = np.zeros_like(d1)
    v[safe] = vb[safe] / denom[safe]
    w[safe] = vc[safe] / denom[safe]
    closest = a + ab * v[:, None] + ac * w[:, None]
    dist2 = np.sum((p - closest) ** 2, axis=1)

    # 各 Voronoi 区域覆盖（后写覆盖前写，优先级正确）
    m = (d1 <= 0) & (d2 <= 0)
    dist2[m] = np.sum((p - a[m]) ** 2, axis=1)

    m = (d3 >= 0) & (d4 <= d3)
    dist2[m] = np.sum((p - b[m]) ** 2, axis=1)

    m = (d6 >= 0) & (d5 <= d6)
    dist2[m] = np.sum((p - c[m]) ** 2, axis=1)

    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    if np.any(m):
        d1m = d1[m]
        d3m = d3[m]
        denom = d1m - d3m
        t = np.zeros_like(d1m)
        safe = denom != 0
        t[safe] = np.clip(d1m[safe] / denom[safe], 0.0, 1.0)
        q = a[m] + ab[m] * t[:, None]
        dist2[m] = np.sum((p - q) ** 2, axis=1)

    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    if np.any(m):
        d2m = d2[m]
        d6m = d6[m]
        denom = d2m - d6m
        t = np.zeros_like(d2m)
        safe = denom != 0
        t[safe] = np.clip(d2m[safe] / denom[safe], 0.0, 1.0)
        q = a[m] + ac[m] * t[:, None]
        dist2[m] = np.sum((p - q) ** 2, axis=1)

    m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    if np.any(m):
        num = d4[m] - d3[m]
        denom = num + (d5[m] - d6[m])
        t = np.zeros_like(num)
        safe = denom != 0
        t[safe] = np.clip(num[safe] / denom[safe], 0.0, 1.0)
        q = b[m] + (c[m] - b[m]) * t[:, None]
        dist2[m] = np.sum((p - q) ** 2, axis=1)

    return dist2