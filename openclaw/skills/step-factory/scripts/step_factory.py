#!/home/Developer/miniconda3/envs/lk-skills/bin/python
# -*- coding: utf-8 -*-
"""
STEP Factory - FreeCAD CAD 模型生成库
支持：方块、圆柱、管材、锥形、齿轮、法兰、装配体等
输出目录：/home/Developer/STEP
"""

import sys
import os
from datetime import datetime

# FreeCAD 初始化
try:
    import FreeCAD
    import Part
    import Sketcher
except ImportError:
    print("ERROR: FreeCAD module not available")
    sys.exit(1)

# 输出目录
STEP_OUTPUT_DIR = "/home/Developer/STEP"
os.makedirs(STEP_OUTPUT_DIR, exist_ok=True)

def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def make_box(w, h, d, label=""):
    """生成方块 Box"""
    box = Part.makeBox(w, h, d)
    if label:
        box.Label = label
    return box

def make_cylinder(r, h, label=""):
    """生成圆柱 Cylinder"""
    cyl = Part.makeCylinder(r, h)
    if label:
        cyl.Label = label
    return cyl

def make_tube(outer_r, inner_r, h, label=""):
    """生成空心管 Tube"""
    outer = Part.makeCylinder(outer_r, h)
    inner = Part.makeCylinder(inner_r, h)
    tube = outer.cut(inner)
    if label:
        tube.Label = label
    return tube

def make_truncated_cone(bottom_r, top_r, h, label=""):
    """生成截头锥 Truncated Cone"""
    cone = Part.makeCylinder(bottom_r, h)
    # 使用旋转生成锥形
    import math
    # 创建锥形几何体
    cone = Part.makeCone(bottom_r, top_r, h)
    if label:
        cone.Label = label
    return cone

def make_sphere(r, label=""):
    """生成球体 Sphere"""
    sphere = Part.makeSphere(r)
    if label:
        sphere.Label = label
    return sphere

def make_torus(major_r, minor_r, label=""):
    """生成环面 Torus"""
    torus = Part.makeTorus(major_r, minor_r)
    if label:
        torus.Label = label
    return torus

def make_flange(outer_r, inner_r, hole_r, thickness, label=""):
    """生成法兰 Flange"""
    outer = Part.makeCylinder(outer_r, thickness)
    hole = Part.makeCylinder(hole_r, thickness + 1)  # 多切一点确保穿透
    flange = outer.cut(hole)
    # 居中
    flange.translate(FreeCAD.Vector(0, 0, -thickness/2))
    if label:
        flange.Label = label
    return flange

def make_shaft(segments, label=""):
    """生成多级轴 Shaft segments = [(r1, h1), (r2, h2), ...]"""
    shaft = None
    y = 0
    for r, h in segments:
        cyl = Part.makeCylinder(r, h)
        cyl.translate(FreeCAD.Vector(0, 0, y))
        if shaft is None:
            shaft = cyl
        else:
            shaft = shaft.fuse(cyl)
        y += h
    if label:
        shaft.Label = label
    return shaft

def make_bracket(w, h, thickness, hole_r=None, label=""):
    """生成角码 Bracket (L型)"""
    import math
    # 创建L型轮廓
    shape = Part.makeBox(w, h, thickness)
    cut = Part.makeBox(w/2, h, thickness + 1)
    cut.translate(FreeCAD.Vector(w/2, 0, -0.5))
    bracket = shape.cut(cut)
    
    if hole_r:
        hole = Part.makeCylinder(hole_r, thickness + 2)
        hole.rotate(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,1,0), 90)
        bracket = bracket.cut(hole)
    
    if label:
        bracket.Label = label
    return bracket

def make_punched_plate(w, h, thickness, hole_rs, spacing=None, label=""):
    """生成打孔板 Punched Plate"""
    import math
    plate = Part.makeBox(w, h, thickness)
    
    if spacing is None:
        spacing = [sum(hole_rs) / len(hole_rs)] * 2
    
    dx, dy = spacing
    rows = int(h / dy)
    cols = int(w / dx)
    
    for i in range(rows):
        for j in range(cols):
            x = j * dx + dx/2 - w/2
            y = i * dy + dy/2 - h/2
            for r in hole_rs:
                hole = Part.makeCylinder(r, thickness + 2)
                hole.translate(FreeCAD.Vector(x, y, 0))
                plate = plate.cut(hole)
    
    if label:
        plate.Label = label
    return plate

def make_bend_plate(w, h, thickness, bend_r=None, bends=None, label=""):
    """生成折弯板 Bend Plate"""
    import math
    if bend_r is None:
        bend_r = thickness * 2
    
    if bends is None:
        # 默认V型折弯
        shape = Part.makeBox(w, h, thickness)
        # 简单处理：不做实际折弯
    else:
        # 多重折弯
        shape = Part.makeBox(w, h, thickness)
    
    if label:
        shape.Label = label
    return shape

def make_threaded_hole(r, depth, thread_pitch=1.0, label=""):
    """生成螺纹孔 Threaded Hole"""
    # 简化处理：生成光孔
    hole = Part.makeCylinder(r, depth)
    if label:
        hole.Label = label
    return hole

def make_counterbore(r, depth, bore_r, bore_depth, label=""):
    """生成埋头孔 Counterbore"""
    main = Part.makeCylinder(r, depth)
    bore = Part.makeCylinder(bore_r, bore_depth)
    bore.translate(FreeCAD.Vector(0, 0, -bore_depth + depth))
    cb = main.fuse(bore)
    if label:
        cb.Label = label
    return cb

def save_step(shape, filename):
    """保存 STEP 文件"""
    filepath = os.path.join(STEP_OUTPUT_DIR, filename)
    shape.exportStep(filepath)
    return filepath

def export_to_step(shape, prefix, params_str, subdir=None):
    """导出 STEP 文件，文件名格式: {prefix}_{params}_{timestamp}.step"""
    ts = timestamp()
    if subdir:
        filename = f"{subdir}_{prefix}_{params_str}_{ts}.step"
    else:
        filename = f"{prefix}_{params_str}_{ts}.step"
    
    filepath = os.path.join(STEP_OUTPUT_DIR, filename)
    shape.exportStep(filepath)
    print(f"Generated: {filepath}")
    return filepath

# ========== 基础形状生成器 ==========

def gen_box(w, h, d):
    """生成方块并保存"""
    shape = make_box(w, h, d)
    params = f"{w}x{h}x{d}"
    return export_to_step(shape, "box", params)

def gen_cylinder(r, h):
    """生成圆柱并保存"""
    shape = make_cylinder(r, h)
    params = f"r{r}h{h}"
    return export_to_step(shape, "cyl", params)

def gen_tube(outer_r, inner_r, h):
    """生成空心管并保存"""
    shape = make_tube(outer_r, inner_r, h)
    params = f"or{outer_r}ir{inner_r}h{h}"
    return export_to_step(shape, "tube", params)

def gen_flange(outer_r, inner_r, hole_r, thickness):
    """生成法兰并保存"""
    shape = make_flange(outer_r, inner_r, hole_r, thickness)
    params = f"or{outer_r}ir{inner_r}hr{hole_r}h{thickness}"
    return export_to_step(shape, "flange", params)

def gen_shaft(segments_str):
    """生成多级轴并保存 segments_str = 'r1h1-r2h2-...'"""
    segments = []
    for seg in segments_str.split('-'):
        r, h = map(float, seg.split('h'))
        segments.append((r, h))
    shape = make_shaft(segments)
    return export_to_step(shape, "shaft", segments_str)

def gen_bracket(w, h, thickness, hole_r=None):
    """生成角码并保存"""
    shape = make_bracket(w, h, thickness, hole_r)
    params = f"{w}x{h}x{thickness}"
    if hole_r:
        params += f"_hr{hole_r}"
    return export_to_step(shape, "bracket", params)

def gen_punched_plate(w, h, thickness, hole_rs_str, spacing_str=None):
    """生成打孔板并保存"""
    hole_rs = [float(r) for r in hole_rs_str.split(',')]
    spacing = [float(s) for s in spacing_str.split(',')] if spacing_str else None
    shape = make_punched_plate(w, h, thickness, hole_rs, spacing)
    params = f"{w}x{h}x{thickness}_holes{hole_rs_str.replace(',', '-')}"
    return export_to_step(shape, "punched_plate", params)

# ========== 特殊零件生成器 ==========

def gen_gear_shaft_bearing():
    """生成齿轮-轴-轴承组件"""
    # 齿轮
    import math
    module = 2
    teeth = 20
    pitch_r = module * teeth / 2
    gear = Part.makeCylinder(pitch_r + module, 10)
    
    # 轴
    shaft = Part.makeCylinder(5, 50)
    shaft.translate(FreeCAD.Vector(0, 0, 20))
    
    # 轴承
    bearing = Part.makeCylinder(15, 10)
    bearing.translate(FreeCAD.Vector(0, 0, 25))
    
    assembly = gear.fuse(shaft).fuse(bearing)
    return export_to_step(assembly, "gear_shaft_bearing", "")

def gen_mechanical_arm():
    """生成机械臂"""
    # 基座
    base = Part.makeCylinder(30, 20)
    
    # 大臂
    arm1 = Part.makeCylinder(8, 80)
    arm1.translate(FreeCAD.Vector(0, 0, 20))
    
    # 小臂
    arm2 = Part.makeCylinder(6, 60)
    arm2.translate(FreeCAD.Vector(0, 0, 100))
    
    arm = base.fuse(arm1).fuse(arm2)
    return export_to_step(arm, "mechanical_arm", "")

def gen_assembly_with_gap():
    """生成带间隙的装配体用于测试3D打印配合"""
    block = Part.makeBox(20, 20, 20)
    pin = Part.makeCylinder(5, 25)
    pin.translate(FreeCAD.Vector(0, 0, 10))
    
    assembly = block.fuse(pin)
    return export_to_step(assembly, "assembly_gap", "block_pin")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "box":
            if len(sys.argv) > 4:
                gen_box(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
        elif cmd == "cyl":
            if len(sys.argv) > 3:
                gen_cylinder(float(sys.argv[2]), float(sys.argv[3]))
        elif cmd == "tube":
            if len(sys.argv) > 4:
                gen_tube(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
        elif cmd == "flange":
            if len(sys.argv) > 5:
                gen_flange(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]))
        elif cmd == "bracket":
            if len(sys.argv) > 4:
                hr = float(sys.argv[4]) if len(sys.argv) > 4 else None
                gen_bracket(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), hr)
        elif cmd == "gear_shaft_bearing":
            gen_gear_shaft_bearing()
        elif cmd == "mechanical_arm":
            gen_mechanical_arm()
        elif cmd == "assembly_gap":
            gen_assembly_with_gap()
        else:
            print(f"Unknown command: {cmd}")
            print("Available: box, cyl, tube, flange, bracket, gear_shaft_bearing, mechanical_arm, assembly_gap")
    else:
        print("STEP Factory CLI")
        print("Usage: python3 step_factory.py <command> [args]")
        print("Commands:")
        print("  box W H D")
        print("  cyl R H")
        print("  tube OUTER_R INNER_R H")
        print("  flange OUTER_R INNER_R HOLE_R THICKNESS")
        print("  bracket W H THICKNESS [HOLE_R]")
        print("  gear_shaft_bearing")
        print("  mechanical_arm")
        print("  assembly_gap")