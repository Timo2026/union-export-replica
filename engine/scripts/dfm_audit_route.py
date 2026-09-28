# -*- coding: utf-8 -*-
"""
DFM 审核 + 工艺路线生成
对 112 个零件做可制造性审核和工艺路线生成

输入：
  - data/batch_quote_test2/常规机加件/*.STEP  (112 个 STEP 文件)
  - output/test2_pdf_extract.csv              (PDF 提取结果)

输出：
  - output/test2_dfm_audit.csv        DFM 审核结果
  - output/test2_process_route.csv    工艺路线
  - output/test2_dfm_route_report.md  DFM+工艺路线报告
"""
from __future__ import annotations

import os
import re
import sys
import time
import glob
import csv
import math
import traceback
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# ---------- 路径 ----------
# 脚本在 scripts/ 下，ROOT 为项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEP_DIR = os.path.join(ROOT, "data", "batch_quote_test2", "常规机加件")
PDF_CSV = os.path.join(ROOT, "output", "test2_pdf_extract.csv")
OUT_AUDIT = os.path.join(ROOT, "output", "test2_dfm_audit.csv")
OUT_ROUTE = os.path.join(ROOT, "output", "test2_process_route.csv")
OUT_REPORT = os.path.join(ROOT, "output", "test2_dfm_route_report.md")

# ---------- SURF_INVALID 黑名单（与 app/main_lite.py 保持一致）----------
SURF_INVALID = {
    ("6061", "发黑"): "铝合金不做发黑处理（发黑是钢铁氧化层工艺）",
    ("al6061", "发黑"): "铝合金不做发黑处理",
    ("7075", "发黑"): "铝合金不做发黑处理",
    ("6061", "磷化"): "铝合金不做磷化处理（磷化为钢铁转化膜）",
    ("al6061", "磷化"): "铝合金不做磷化处理",
    ("7075", "磷化"): "铝合金不做磷化处理",
    ("6061", "镀锌"): "铝合金通常阳极氧化而非镀锌",
    ("al6061", "镀锌"): "铝合金通常阳极氧化而非镀锌",
    ("7075", "镀锌"): "铝合金通常阳极氧化而非镀锌",
    ("304", "镀锌"): "不锈钢本身耐腐蚀，不需镀锌",
    ("sus304", "镀锌"): "不锈钢本身耐腐蚀，不需镀锌",
    ("316l", "镀锌"): "不锈钢本身耐腐蚀，不需镀锌",
    ("sus316", "镀锌"): "不锈钢本身耐腐蚀，不需镀锌",
    ("304", "磷化"): "不锈钢磷化效果差，不常用",
    ("sus304", "磷化"): "不锈钢磷化效果差，不常用",
    ("316l", "磷化"): "不锈钢磷化效果差，不常用",
    ("sus316", "磷化"): "不锈钢磷化效果差，不常用",
    ("304", "阳极氧化"): "不锈钢不做阳极氧化（阳极氧化为铝/钛工艺）",
    ("sus304", "阳极氧化"): "不锈钢不做阳极氧化",
    ("316l", "阳极氧化"): "不锈钢不做阳极氧化",
    ("sus316", "阳极氧化"): "不锈钢不做阳极氧化",
    ("tc4", "发黑"): "钛合金不做发黑处理",
    ("钛合金", "发黑"): "钛合金不做发黑处理",
    ("tc4", "镀锌"): "钛合金不做镀锌",
    ("钛合金", "镀锌"): "钛合金不做镀锌",
    ("tc4", "磷化"): "钛合金不做磷化",
    ("钛合金", "磷化"): "钛合金不做磷化",
    ("tc4", "镀铬"): "钛合金不做镀铬",
    ("钛合金", "镀铬"): "钛合金不做镀铬",
    ("黄铜", "阳极氧化"): "黄铜不做阳极氧化",
    ("h59", "阳极氧化"): "黄铜不做阳极氧化",
    ("黄铜", "磷化"): "黄铜不做磷化处理",
    ("h59", "磷化"): "黄铜不做磷化处理",
    ("q235", "阳极氧化"): "钢不做阳极氧化（阳极氧化为铝/钛工艺）",
    ("45钢", "阳极氧化"): "45钢不做阳极氧化",
    ("45#", "阳极氧化"): "45钢不做阳极氧化",
    ("45钢", "喷漆"): "45钢通常发黑/镀锌/镀铬/磷化，不做喷漆",
    ("45#", "喷漆"): "45钢通常发黑/镀锌/镀铬/磷化，不做喷漆",
}

# 非金属件（注塑成型，不做机加 DFM）
NON_METAL_MATERIALS = {"ABS", "POM", "PC", "PA", "PP", "PE", "PVC", "PTFE", "PMMA"}

# ---------- 材料归一化 ----------
def normalize_material(mat: str) -> tuple[str, str]:
    """返回 (材料键 lower, 材料显示名)"""
    if not mat:
        return ("", "")
    m = mat.strip()
    ml = m.lower()
    # 提取核心材料键
    if "6061" in m or "al6061" in ml:
        return ("6061", "6061铝合金")
    if "7075" in m:
        return ("7075", "7075铝合金")
    if "316l" in ml or "316" in ml and "l" in ml:
        return ("316l", "316L不锈钢")
    if "316" in ml:
        return ("316l", "316不锈钢")
    if "304" in ml:
        return ("304", "304不锈钢")
    if "440c" in ml:
        return ("440c", "440C不锈钢")
    if "tc4" in ml or "钛合金" in m:
        return ("tc4", "TC4钛合金")
    if "yg8" in ml or "钨" in m or "硬质合金" in m:
        return ("yg8", "YG8钨合金")
    if "黄铜" in m or "h59" in ml or "h62" in ml:
        return ("黄铜", "黄铜")
    if "q235" in ml:
        return ("q235", "Q235碳钢")
    if "45" in m and ("钢" in m or "#" in m):
        return ("45钢", "45钢")
    if "abs" in ml:
        return ("abs", "ABS")
    if "pom" in ml:
        return ("pom", "POM")
    return (ml, m)


def is_non_metal(mat: str) -> bool:
    m = mat.strip().upper()
    return any(nm in m for nm in NON_METAL_MATERIALS)


# ---------- 表面处理兼容性 ----------
def check_surface_compat(material: str, surface: str) -> tuple[bool, str]:
    """返回 (兼容, 原因)"""
    if not surface or surface == "无" or surface == "选择黑色原料":
        return (True, "")
    mat_key, _ = normalize_material(material)
    # 表面处理可能是组合（喷砂+阳极氧化+喷漆），逐项检查
    parts = re.split(r"[+＋]", surface)
    parts = [p.strip() for p in parts if p.strip()]
    for s in parts:
        # 标准化表面名
        s_lower = s.lower()
        # 查黑名单
        reason = (
            SURF_INVALID.get((mat_key, s))
            or SURF_INVALID.get((mat_key, s_lower))
        )
        if reason:
            return (False, f"{material}+{s}: {reason}")
    return (True, "")


# ---------- 螺纹孔解析 ----------
@dataclass
class ThreadInfo:
    count: int = 0
    min_diameter: float = 999.0  # mm
    spec_list: list = field(default_factory=list)
    has_small_hole: bool = False  # M2 以下
    has_deep_hole: bool = False  # 深径比>5（无法从 PDF 判断，默认 False）


def parse_thread_spec(spec: str) -> ThreadInfo:
    info = ThreadInfo()
    if not spec or not spec.strip():
        return info
    # 形如 "13×M4-6H; 3×M2-6H" 或 "22×M6-6H; 22×M4-6H; 8×M6; 4×M5-6H; 2×M3"
    parts = re.split(r"[;；]", spec)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 匹配 数量×M直径
        m = re.search(r"(\d+)\s*[×xX]\s*M([\d.]+)", part)
        if m:
            cnt = int(m.group(1))
            dia = float(m.group(2))
            info.count += cnt
            info.min_diameter = min(info.min_diameter, dia)
            info.spec_list.append(f"{cnt}×M{dia}")
            if dia < 2.0:
                info.has_small_hole = True
    return info


# ---------- 公差/粗糙度解析 ----------
def parse_tolerance(tol: str) -> tuple[str, float]:
    """返回 (公差等级, 评分)  评分 0-100"""
    if not tol:
        return ("未知", 95)
    t = tol.lower()
    if "f" in t and ("1804" in t or "2768" in t or "精细" in t):
        return ("精细", 75)
    if "c" in t and ("1804" in t or "2768" in t or "粗糙" in t):
        return ("粗糙", 100)
    if "m" in t and ("1804" in t or "2768" in t or "中等" in t):
        return ("中等", 95)
    if "精细" in t:
        return ("精细", 75)
    if "粗糙" in t:
        return ("粗糙", 100)
    return ("中等", 95)


def parse_roughness(ra: str) -> tuple[float, float, str]:
    """返回 (Ra值, 评分, 备注)  Ra=0 表示未找到"""
    if not ra or not ra.strip():
        return (0.0, 95, "未指定")
    m = re.search(r"Ra?([\d.]+)", ra, re.IGNORECASE)
    if not m:
        return (0.0, 95, "未指定")
    val = float(m.group(1))
    if val <= 0.4:
        return (val, 70, "需磨削")
    if val <= 0.8:
        return (val, 85, "需精磨/精车")
    if val <= 1.6:
        return (val, 95, "精加工")
    return (val, 100, "粗加工即可")


# ---------- STEP 几何解析 ----------
@dataclass
class StepGeom:
    ok: bool = False
    bbox_dims: tuple = (0, 0, 0)  # 排序后 (min, mid, max) mm
    bbox_max: float = 0.0
    faces: int = 0
    edges: int = 0
    verts: int = 0
    volume_mm3: float = 0.0
    fill_ratio: float = 1.0  # 体积/凸包体积
    eq_wall_mm: float = 0.0  # 等效壁厚
    degrade: bool = False  # 降级评估
    error: str = ""


def parse_step(step_path: str, file_size: int) -> StepGeom:
    """用 cadquery 解析 STEP，返回几何信息"""
    geom = StepGeom()
    try:
        import cadquery as cq
        shape = cq.importers.importStep(step_path)
        solids = shape.vals()
        if not solids:
            geom.error = "no solid"
            return geom
        # 合并所有 solid 的 bbox
        s0 = solids[0]
        bb = s0.BoundingBox()
        xmin, xmax = bb.xmin, bb.xmax
        ymin, ymax = bb.ymin, bb.ymax
        zmin, zmax = bb.zmin, bb.zmax
        total_vol = s0.Volume()
        total_faces = len(s0.Faces())
        total_edges = len(s0.Edges())
        total_verts = len(s0.Vertices())
        for s in solids[1:]:
            b2 = s.BoundingBox()
            xmin = min(xmin, b2.xmin); xmax = max(xmax, b2.xmax)
            ymin = min(ymin, b2.ymin); ymax = max(ymax, b2.ymax)
            zmin = min(zmin, b2.zmin); zmax = max(zmax, b2.zmax)
            total_vol += s.Volume()
            total_faces += len(s.Faces())
            total_edges += len(s.Edges())
            total_verts += len(s.Vertices())

        dx, dy, dz = xmax - xmin, ymax - ymin, zmax - zmin
        dims = sorted([dx, dy, dz])
        geom.bbox_dims = (dims[0], dims[1], dims[2])
        geom.bbox_max = dims[2]
        geom.faces = total_faces
        geom.edges = total_edges
        geom.verts = total_verts
        geom.volume_mm3 = total_vol

        # 用 tessellate 计算填充率和等效壁厚
        try:
            tess = s0.tessellate(1.0)
            v = np.array([[vt.x, vt.y, vt.z] for vt in tess[0]])
            f = np.array(tess[1])
            import trimesh
            mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
            hull = mesh.convex_hull
            if hull.volume > 0:
                geom.fill_ratio = float(mesh.volume / hull.volume)
            # 等效壁厚 = 体积 / 投影面积（中维度×大维度）
            if dims[1] > 0 and dims[2] > 0:
                geom.eq_wall_mm = float(total_vol / (dims[1] * dims[2]))
        except Exception as e:
            # tessellate 失败，用简化估算
            if dims[1] > 0 and dims[2] > 0:
                geom.eq_wall_mm = float(total_vol / (dims[1] * dims[2]))
            geom.fill_ratio = 0.5  # 未知，给中间值

        geom.ok = True
        return geom
    except Exception as e:
        geom.error = str(e)[:100]
        geom.degrade = True
        # 降级：用文件大小估算
        # STEP 1KB ≈ 10 面（经验值）
        est_faces = int(file_size / 100)
        geom.faces = est_faces
        geom.edges = int(est_faces * 2.5)
        geom.verts = int(est_faces * 1.5)
        return geom


# ---------- DFM 审核 ----------
@dataclass
class DfmResult:
    min_wall_assessment: str = ""
    hole_assessment: str = ""
    complexity_level: str = ""
    size_class: str = ""
    surface_feasibility: str = ""
    tolerance_feasibility: str = ""
    tool_accessibility: str = ""
    dfm_score: float = 0.0
    dfm_issues: str = ""
    dfm_recommendations: str = ""
    # 内部评分
    _score_wall: float = 100
    _score_hole: float = 100
    _score_complex: float = 100
    _score_size: float = 100
    _score_surf: float = 100
    _score_tol: float = 100
    _score_tool: float = 100


def dfm_audit(
    part_number: str,
    part_name: str,
    material: str,
    surface: str,
    tolerance: str,
    roughness: str,
    thread_spec: str,
    geom: StepGeom,
) -> DfmResult:
    r = DfmResult()
    issues = []
    recs = []

    # 非金属件特殊处理
    if is_non_metal(material):
        r.min_wall_assessment = "非金属，注塑成型"
        r.hole_assessment = "非金属，注塑成型"
        r.complexity_level = "非金属，注塑成型"
        r.size_class = "非金属，注塑成型"
        r.surface_feasibility = "非金属，注塑成型"
        r.tolerance_feasibility = "非金属，注塑成型"
        r.tool_accessibility = "非金属，注塑成型"
        r.dfm_score = 100.0
        r.dfm_issues = "非金属件，注塑成型，不做机加 DFM 审核"
        r.dfm_recommendations = "注塑模具开发，无需机加工艺路线"
        return r

    # 1. 壁厚评估
    if geom.ok and geom.eq_wall_mm > 0:
        w = geom.eq_wall_mm
        if w < 1.0:
            r.min_wall_assessment = f"⚠薄壁 {w:.2f}mm，加工困难"
            r._score_wall = 50
            issues.append(f"薄壁({w:.2f}mm)")
            recs.append("增加支撑/装夹防变形")
        elif w < 2.0:
            r.min_wall_assessment = f"注意刚性 {w:.2f}mm"
            r._score_wall = 75
            issues.append(f"壁薄({w:.2f}mm)")
            recs.append("注意装夹刚性")
        elif w < 5.0:
            r.min_wall_assessment = f"正常 {w:.2f}mm"
            r._score_wall = 95
        else:
            r.min_wall_assessment = f"厚实 {w:.2f}mm"
            r._score_wall = 100
    else:
        r.min_wall_assessment = "未知(降级)"
        r._score_wall = 80

    # 2. 孔特征评估
    ti = parse_thread_spec(thread_spec)
    if ti.count == 0:
        r.hole_assessment = "无螺纹孔"
        r._score_hole = 95
    else:
        if ti.has_small_hole:
            r.hole_assessment = f"⚠小孔 M{ti.min_diameter}g，加工困难（{ti.count}孔）"
            r._score_hole = 60
            issues.append(f"小孔M{ti.min_diameter}")
            recs.append("使用精密小丝锥/定心钻")
        elif ti.min_diameter < 3.0:
            r.hole_assessment = f"注意 M{ti.min_diameter}，{ti.count}孔"
            r._score_hole = 80
        else:
            r.hole_assessment = f"正常 M{ti.min_diameter}，{ti.count}孔"
            r._score_hole = 95

    # 3. 结构复杂度
    if geom.degrade:
        r.complexity_level = f"降级估算(面数~{geom.faces})"
        r._score_complex = 80
    else:
        f_cnt = geom.faces
        if f_cnt > 500:
            r.complexity_level = f"复杂({f_cnt}面/{geom.edges}边)"
            r._score_complex = 70
            issues.append(f"结构复杂({f_cnt}面)")
            recs.append("多工序分步加工")
        elif f_cnt > 200:
            r.complexity_level = f"中等({f_cnt}面/{geom.edges}边)"
            r._score_complex = 90
        else:
            r.complexity_level = f"简单({f_cnt}面/{geom.edges}边)"
            r._score_complex = 100

    # 4. 尺寸评估
    if geom.ok:
        max_d = geom.bbox_max
        if max_d > 500:
            r.size_class = f"大件 {max_d:.0f}mm，需大机床"
            r._score_size = 75
            issues.append(f"大尺寸({max_d:.0f}mm)")
            recs.append("选用大行程机床")
        elif max_d > 200:
            r.size_class = f"中等 {max_d:.0f}mm"
            r._score_size = 95
        else:
            r.size_class = f"小件 {max_d:.0f}mm"
            r._score_size = 100
    else:
        r.size_class = "未知(降级)"
        r._score_size = 85

    # 5. 表面处理可行性
    ok, reason = check_surface_compat(material, surface)
    if ok:
        r.surface_feasibility = f"兼容: {material}+{surface}"
        r._score_surf = 100
    else:
        r.surface_feasibility = f"⚠不兼容: {reason}"
        r._score_surf = 40
        issues.append(f"表面不兼容({material}+{surface})")
        recs.append(f"更换表面处理: {reason}")

    # 6. 公差可行性
    tol_level, tol_score = parse_tolerance(tolerance)
    ra_val, ra_score, ra_note = parse_roughness(roughness)
    r._score_tol = (tol_score + ra_score) / 2
    parts = [f"公差{tol_level}"]
    if ra_val > 0:
        parts.append(f"Ra{ra_val}({ra_note})")
    else:
        parts.append("Ra未指定")
    r.tolerance_feasibility = "+".join(parts)
    if tol_level == "精细":
        issues.append("精细公差")
        recs.append("增加精磨工序")
    if ra_val > 0 and ra_val <= 0.4:
        issues.append(f"高粗糙度要求Ra{ra_val}")
        recs.append("增加磨削工序")

    # 7. 刀具可达性
    if geom.ok:
        d_min, d_mid, d_max = geom.bbox_dims
        # 深腔判断：max/min > 10 且 min < 20
        if d_max / max(d_min, 0.1) > 10 and d_min < 20:
            r.tool_accessibility = f"⚠深腔/窄槽 {d_max:.0f}/{d_min:.1f}，需特殊刀具"
            r._score_tool = 70
            issues.append("深腔/窄槽")
            recs.append("使用加长刀具/深孔钻")
        elif d_min < 5:
            r.tool_accessibility = f"⚠薄板 {d_min:.1f}mm，刚性差"
            r._score_tool = 75
            issues.append(f"薄板({d_min:.1f}mm)")
            recs.append("真空吸盘装夹")
        else:
            r.tool_accessibility = "良好"
            r._score_tool = 90
    else:
        r.tool_accessibility = "未知(降级)"
        r._score_tool = 80

    # 综合评分（加权）
    r.dfm_score = (
        r._score_wall * 0.20
        + r._score_hole * 0.15
        + r._score_complex * 0.15
        + r._score_size * 0.10
        + r._score_surf * 0.15
        + r._score_tol * 0.15
        + r._score_tool * 0.10
    )
    r.dfm_issues = "; ".join(issues) if issues else "无"
    r.dfm_recommendations = "; ".join(recs) if recs else "无"
    return r


# ---------- 工艺路线生成 ----------
@dataclass
class RouteResult:
    process_type: str = ""  # 车/铣/车铣复合/注塑
    route_steps: list = field(default_factory=list)
    estimated_time_min: float = 0.0
    required_machine: str = ""
    required_tools: str = ""


def gen_route(
    part_number: str,
    part_name: str,
    material: str,
    surface: str,
    tolerance: str,
    roughness: str,
    thread_spec: str,
    geom: StepGeom,
    dfm: DfmResult,
) -> RouteResult:
    r = RouteResult()

    # 非金属件
    if is_non_metal(material):
        r.process_type = "注塑"
        r.route_steps = ["注塑成型", "去毛刺", "检验"]
        r.estimated_time_min = 5.0
        r.required_machine = "注塑机"
        r.required_tools = "注塑模具"
        return r

    # 判断主工艺类型：旋转体 vs 板类/壳体
    is_rotational = False
    is_plate = False
    if geom.ok:
        d_min, d_mid, d_max = geom.bbox_dims
        # 旋转体：两个维度接近（差<30%），第三个明显长（>2倍）
        if d_min > 0 and d_mid > 0:
            ratio_short = abs(d_min - d_mid) / max(d_min, d_mid)
            ratio_long = d_max / d_mid
            if ratio_short < 0.3 and ratio_long > 2.0:
                is_rotational = True
            # 板类：一个维度明显小（<其他两个的30%）
            if d_min < d_mid * 0.3:
                is_plate = True

    # 零件名暗示
    name_hints_rot = ["轴", "轮", "套", "杆", "柱", "销"]
    name_hints_plate = ["板", "盖", "壳", "座", "架", "块", "片", "支架", "连杆"]
    if any(h in part_name for h in name_hints_rot):
        # 含旋转体特征词，但板类词优先级也高，综合判断
        if not is_plate and any(h in part_name for h in ["板", "盖", "壳"]):
            is_plate = True
        else:
            is_rotational = True
    if any(h in part_name for h in name_hints_plate):
        if not is_rotational:
            is_plate = True

    if is_rotational and not is_plate:
        r.process_type = "车"
    elif is_plate:
        r.process_type = "铣"
    else:
        r.process_type = "车铣复合"

    # 工序生成
    steps = []
    tools = []
    ti = parse_thread_spec(thread_spec)
    ra_val = parse_roughness(roughness)[0]
    tol_level = parse_tolerance(tolerance)[0]

    # 1. 毛坯准备
    mat_key, mat_disp = normalize_material(material)
    if "铝" in mat_disp:
        blank = "铝棒料/板材下料"
    elif "钢" in mat_disp or "铁" in mat_disp:
        blank = "棒料/板材锯切下料"
    elif "钛" in mat_disp:
        blank = "钛合金棒料下料"
    elif "黄铜" in mat_disp:
        blank = "黄铜棒料下料"
    elif "钨" in mat_disp or "硬质合金" in mat_disp:
        blank = "硬质合金毛坯"
    else:
        blank = "下料"
    steps.append(blank)

    # 2. 粗加工
    if r.process_type == "车":
        steps.append("车端面/钻中心孔")
        steps.append("粗车外圆/钻孔")
        tools.extend(["车刀", "中心钻", "钻头"])
    elif r.process_type == "铣":
        steps.append("铣基准面/粗铣轮廓")
        tools.extend(["面铣刀", "立铣刀"])
    else:
        steps.append("车端面/铣基准面")
        steps.append("粗车外圆/粗铣轮廓")
        tools.extend(["车刀", "面铣刀", "立铣刀"])

    # 3. 半精加工
    if r.process_type == "车":
        steps.append("半精车台阶/车槽")
        tools.append("切槽刀")
    elif r.process_type == "铣":
        steps.append("半精铣轮廓/铣槽/钻孔")
        tools.extend(["立铣刀", "钻头"])
    else:
        steps.append("半精车/半精铣/钻孔")
        tools.extend(["立铣刀", "钻头"])

    # 4. 精加工
    if r.process_type == "车":
        steps.append("精车外圆/端面")
        tools.append("精车刀")
    elif r.process_type == "铣":
        steps.append("精铣轮廓/精铣平面")
        tools.append("精铣刀")
    else:
        steps.append("精车/精铣")
        tools.append("精铣刀")

    # 5. 螺纹加工
    if ti.count > 0:
        if ti.min_diameter < 3:
            steps.append(f"攻丝({ti.count}孔，含小孔M{ti.min_diameter})")
            tools.append("小丝锥")
        else:
            steps.append(f"攻丝/车螺纹({ti.count}孔)")
            tools.append("丝锥/螺纹刀")

    # 6. 磨削（高粗糙度要求）
    if ra_val > 0 and ra_val <= 0.8:
        steps.append(f"磨削(满足Ra{ra_val})")
        tools.append("砂轮")
    if tol_level == "精细":
        steps.append("精磨(满足精细公差)")
        tools.append("精磨砂轮")

    # 7. 热处理（钨合金/钛合金/精细公差钢件）
    if "钨" in mat_disp or "硬质合金" in mat_disp:
        steps.append("热处理(时效硬化)")
    elif "钛" in mat_disp:
        steps.append("去应力退火")
    elif tol_level == "精细" and ("钢" in mat_disp or "铁" in mat_disp):
        steps.append("淬火+回火")

    # 8. 表面处理
    if surface and surface not in ("无", ""):
        # 拆分组合表面处理
        parts = re.split(r"[+＋]", surface)
        parts = [p.strip() for p in parts if p.strip() and p.strip() != "无"]
        if parts:
            steps.append("表面处理: " + "+".join(parts))
            if "阳极氧化" in surface:
                tools.append("阳极氧化槽")
            if "喷砂" in surface:
                tools.append("喷砂设备")
            if "喷漆" in surface:
                tools.append("喷漆设备")
            if "发黑" in surface:
                tools.append("发黑炉")
            if "镀铬" in surface or "镀锌" in surface or "镀镍" in surface:
                tools.append("电镀槽")
            if "DLC" in surface or "涂层" in surface or "氮化钛" in surface:
                tools.append("PVD涂层设备")
            if "钝化" in surface:
                tools.append("钝化槽")

    # 9. 检验
    steps.append("尺寸检验/粗糙度检验")

    r.route_steps = steps
    r.required_tools = ", ".join(sorted(set(tools)))

    # 估算加工时间
    if geom.ok:
        # 基础时间 = 体积^0.5 × 复杂度系数
        base = math.sqrt(geom.volume_mm3) * 0.15
        complex_coef = 1.0 + geom.faces / 500.0
        thread_time = ti.count * 1.5
        surf_time = 10 if surface and surface != "无" else 0
        r.estimated_time_min = round(base * complex_coef + thread_time + surf_time, 1)
    else:
        r.estimated_time_min = round(30 + ti.count * 1.5, 1)

    # 机床选择
    if geom.ok:
        max_d = geom.bbox_max
        if max_d > 500:
            size_tag = "大行程"
        elif max_d > 200:
            size_tag = "中型"
        else:
            size_tag = "小型"
    else:
        size_tag = "中型"
    if r.process_type == "车":
        r.required_machine = f"{size_tag}数控车床"
    elif r.process_type == "铣":
        r.required_machine = f"{size_tag}三轴加工中心"
    else:
        r.required_machine = f"{size_tag}车铣复合中心"

    return r


# ---------- 主流程 ----------
def main():
    print(f"[INFO] ROOT = {ROOT}")
    print(f"[INFO] STEP_DIR = {STEP_DIR}")

    # 读取 PDF 提取 CSV
    pdf_rows = []
    with open(PDF_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pdf_rows.append(row)
    print(f"[INFO] PDF rows: {len(pdf_rows)}")

    # 建立 part_number → step_path 映射
    step_files = glob.glob(os.path.join(STEP_DIR, "*.STEP"))
    step_map = {}
    for sp in step_files:
        base = os.path.basename(sp)
        # 1010001-戳卡夹外壳-V1.0.STEP → 1010001
        m = re.match(r"(\d+)-", base)
        if m:
            step_map[m.group(1)] = sp
    print(f"[INFO] STEP files: {len(step_files)}, mapped: {len(step_map)}")

    # 处理每个零件
    audit_rows = []
    route_rows = []
    t_start = time.time()

    for i, row in enumerate(pdf_rows, 1):
        pno = row["part_number"].strip()
        pname = row["part_name"].strip()
        material = row.get("material", "").strip()
        surface = row.get("surface_treatment", "").strip()
        tolerance = row.get("tolerance", "").strip()
        roughness = row.get("roughness_ra", "").strip()
        thread_spec = row.get("thread_spec", "").strip()

        # 找 STEP 文件
        step_path = step_map.get(pno, "")
        file_size = os.path.getsize(step_path) if step_path else 0

        # 解析 STEP
        if step_path:
            geom = parse_step(step_path, file_size)
        else:
            geom = StepGeom(ok=False, degrade=True, error="STEP文件缺失")
        dt = time.time() - t_start

        # DFM 审核
        dfm = dfm_audit(pno, pname, material, surface, tolerance, roughness, thread_spec, geom)

        # 工艺路线
        route = gen_route(pno, pname, material, surface, tolerance, roughness, thread_spec, geom, dfm)

        # 写入 audit 行
        audit_rows.append({
            "part_number": pno,
            "part_name": pname,
            "material": material,
            "min_wall_assessment": dfm.min_wall_assessment,
            "hole_assessment": dfm.hole_assessment,
            "complexity_level": dfm.complexity_level,
            "size_class": dfm.size_class,
            "surface_feasibility": dfm.surface_feasibility,
            "tolerance_feasibility": dfm.tolerance_feasibility,
            "tool_accessibility": dfm.tool_accessibility,
            "dfm_score": round(dfm.dfm_score, 1),
            "dfm_issues": dfm.dfm_issues,
            "dfm_recommendations": dfm.dfm_recommendations,
        })

        # 写入 route 行
        route_rows.append({
            "part_number": pno,
            "part_name": pname,
            "material": material,
            "process_type": route.process_type,
            "route_steps": " | ".join(route.route_steps),
            "estimated_machining_time_min": route.estimated_time_min,
            "required_machine": route.required_machine,
            "required_tools": route.required_tools,
        })

        status = "OK" if geom.ok else "DEGRADE"
        print(f"[{i}/{len(pdf_rows)}] {pno} {pname[:20]:20s} score={dfm.dfm_score:5.1f} {route.process_type} {status} t={dt:.1f}s")

    # 写 CSV
    audit_cols = ["part_number", "part_name", "material", "min_wall_assessment",
                  "hole_assessment", "complexity_level", "size_class",
                  "surface_feasibility", "tolerance_feasibility", "tool_accessibility",
                  "dfm_score", "dfm_issues", "dfm_recommendations"]
    with open(OUT_AUDIT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=audit_cols)
        w.writeheader()
        w.writerows(audit_rows)
    print(f"[OK] 写入 {OUT_AUDIT} ({len(audit_rows)} 行)")

    route_cols = ["part_number", "part_name", "material", "process_type",
                  "route_steps", "estimated_machining_time_min",
                  "required_machine", "required_tools"]
    with open(OUT_ROUTE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=route_cols)
        w.writeheader()
        w.writerows(route_rows)
    print(f"[OK] 写入 {OUT_ROUTE} ({len(route_rows)} 行)")

    # 生成报告
    write_report(audit_rows, route_rows)
    print(f"[OK] 写入 {OUT_REPORT}")

    print(f"[DONE] 总耗时 {time.time()-t_start:.1f}s")


def write_report(audit_rows: list, route_rows: list):
    # 统计
    total = len(audit_rows)
    scores = [r["dfm_score"] for r in audit_rows]
    pass_cnt = sum(1 for s in scores if s > 80)
    warn_cnt = sum(1 for s in scores if 60 <= s <= 80)
    fail_cnt = sum(1 for s in scores if s < 60)

    # 非金属件单独统计
    non_metal = sum(1 for r in audit_rows if "非金属" in r["min_wall_assessment"])
    metal_total = total - non_metal

    # DFM 问题分布
    issue_types = {
        "薄壁": 0, "小孔": 0, "深孔": 0, "复杂结构": 0,
        "大尺寸": 0, "不兼容表面": 0, "精密公差": 0, "高粗糙度": 0,
        "深腔/窄槽": 0, "薄板": 0,
    }
    for r in audit_rows:
        iss = r["dfm_issues"]
        if "薄壁" in iss: issue_types["薄壁"] += 1
        if "壁薄" in iss: issue_types["薄壁"] += 1
        if "小孔" in iss: issue_types["小孔"] += 1
        if "深孔" in iss: issue_types["深孔"] += 1
        if "结构复杂" in iss: issue_types["复杂结构"] += 1
        if "大尺寸" in iss: issue_types["大尺寸"] += 1
        if "表面不兼容" in iss: issue_types["不兼容表面"] += 1
        if "精细公差" in iss: issue_types["精密公差"] += 1
        if "高粗糙度" in iss: issue_types["高粗糙度"] += 1
        if "深腔" in iss: issue_types["深腔/窄槽"] += 1
        if "薄板" in iss: issue_types["薄板"] += 1

    # 工艺路线统计
    route_types = {"车": 0, "铣": 0, "车铣复合": 0, "注塑": 0}
    step_counts = []
    for r in route_rows:
        route_types[r["process_type"]] = route_types.get(r["process_type"], 0) + 1
        sc = r["route_steps"].count("|") + 1
        step_counts.append(sc)

    avg_steps = sum(step_counts) / len(step_counts) if step_counts else 0
    max_steps = max(step_counts) if step_counts else 0
    min_steps = min(step_counts) if step_counts else 0

    # DFM 问题 Top10
    sorted_rows = sorted(audit_rows, key=lambda x: x["dfm_score"])
    top10 = sorted_rows[:10]

    # 工艺路线示例（选不同类型各1-2个）
    examples = []
    for pt in ["车", "铣", "车铣复合", "注塑"]:
        for r in route_rows:
            if r["process_type"] == pt:
                examples.append(r)
                break

    # 写报告
    lines = []
    lines.append("# DFM 审核 + 工艺路线生成报告")
    lines.append("")
    lines.append(f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**零件总数**: {total}（金属件 {metal_total}，非金属件 {non_metal}）")
    lines.append("")

    lines.append("## 1. DFM 审核统计")
    lines.append("")
    lines.append("| 等级 | 数量 | 占比 | 说明 |")
    lines.append("|------|------|------|------|")
    lines.append(f"| ✅ 良好(>80) | {pass_cnt} | {pass_cnt/total*100:.1f}% | 可直接加工 |")
    lines.append(f"| ⚠ 注意(60-80) | {warn_cnt} | {warn_cnt/total*100:.1f}% | 需关注工艺细节 |")
    lines.append(f"| ❌ 问题(<60) | {fail_cnt} | {fail_cnt/total*100:.1f}% | 需工艺优化或设计变更 |")
    lines.append(f"| **平均分** | **{sum(scores)/total:.1f}** | | |")
    lines.append("")

    lines.append("## 2. DFM 问题分布")
    lines.append("")
    lines.append("| 问题类型 | 数量 | 占比 |")
    lines.append("|----------|------|------|")
    for k, v in sorted(issue_types.items(), key=lambda x: -x[1]):
        if v > 0:
            lines.append(f"| {k} | {v} | {v/metal_total*100:.1f}% |")
    lines.append("")

    lines.append("## 3. 工艺路线统计")
    lines.append("")
    lines.append("| 工艺类型 | 数量 | 占比 |")
    lines.append("|----------|------|------|")
    type_labels = {"车": "车削类", "铣": "铣削类", "车铣复合": "车铣复合类", "注塑": "注塑类"}
    for k, v in route_types.items():
        if v > 0:
            label = type_labels.get(k, k)
            lines.append(f"| {label} | {v} | {v/total*100:.1f}% |")
    lines.append("")
    lines.append(f"- **平均工序数**: {avg_steps:.1f}")
    lines.append(f"- **最长工序**: {max_steps} 步")
    lines.append(f"- **最短工序**: {min_steps} 步")
    lines.append("")

    lines.append("## 4. DFM 问题 Top10 零件清单")
    lines.append("")
    lines.append("| 排名 | 零件号 | 零件名 | 材料 | DFM分 | 主要问题 |")
    lines.append("|------|--------|--------|------|-------|----------|")
    for i, r in enumerate(top10, 1):
        lines.append(f"| {i} | {r['part_number']} | {r['part_name']} | {r['material']} | {r['dfm_score']} | {r['dfm_issues'][:50]} |")
    lines.append("")

    lines.append("## 5. 工艺路线示例")
    lines.append("")
    for r in examples:
        audit = next((a for a in audit_rows if a["part_number"] == r["part_number"]), None)
        lines.append(f"### {r['part_number']} - {r['part_name']}")
        lines.append("")
        lines.append(f"- **材料**: {r['material']}")
        lines.append(f"- **工艺类型**: {r['process_type']}")
        lines.append(f"- **DFM 评分**: {audit['dfm_score'] if audit else 'N/A'}")
        lines.append(f"- **机床**: {r['required_machine']}")
        lines.append(f"- **刀具**: {r['required_tools']}")
        lines.append(f"- **预计工时**: {r['estimated_machining_time_min']} min")
        lines.append(f"- **工艺路线**:")
        lines.append("")
        steps = r["route_steps"].split(" | ")
        for j, s in enumerate(steps, 1):
            lines.append(f"  {j}. {s}")
        lines.append("")

    lines.append("## 6. DFM 评分明细")
    lines.append("")
    lines.append("| 零件号 | 零件名 | 材料 | DFM分 | 壁厚 | 孔 | 复杂度 | 尺寸 | 表面 | 公差 | 刀具 |")
    lines.append("|--------|--------|------|-------|------|-----|--------|------|------|------|------|")
    for r in audit_rows:
        lines.append(f"| {r['part_number']} | {r['part_name']} | {r['material']} | {r['dfm_score']} | {r['min_wall_assessment'][:15]} | {r['hole_assessment'][:15]} | {r['complexity_level'][:12]} | {r['size_class'][:12]} | {r['surface_feasibility'][:15]} | {r['tolerance_feasibility'][:15]} | {r['tool_accessibility'][:12]} |")
    lines.append("")

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()