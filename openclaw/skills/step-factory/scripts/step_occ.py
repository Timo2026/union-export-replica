#!/home/Developer/miniconda3/envs/lk-skills/bin/python
# -*- coding: utf-8 -*-
"""
STEP Factory - 基于 OCP (OpenCASCADE Python 绑定) 的 CAD 模型生成器
引擎: /home/Developer/miniconda3/envs/lk-skills/bin/python
输出目录: /home/Developer/STEP
"""
import sys
import os
from datetime import datetime

# OCC/OCP 导入（新一代绑定名 OCP, 无 Core 中间层）
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, 
    BRepPrimAPI_MakeCone, BRepPrimAPI_MakeSphere, 
    BRepPrimAPI_MakeTorus, BRepPrimAPI_MakePrism
)
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse, BRepAlgoAPI_Common
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.gp import gp_Vec, gp_Trsf, gp_Ax1, gp_Pnt
from OCP.GC import GC_MakeArcOfCircle, GC_MakeSegment
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace

STEP_OUTPUT_DIR = "/home/Developer/STEP"
os.makedirs(STEP_OUTPUT_DIR, exist_ok=True)

def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def export_step(shape, filename):
    """导出 STEP 文件"""
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)  # 1 = silent mode
    filepath = os.path.join(STEP_OUTPUT_DIR, filename)
    writer.Write(filepath)
    print(f"OCC_OUTPUT: {filepath}")
    return filepath

def translate_shape(shape, x, y, z):
    """平移形状"""
    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(x, y, z))
    return BRepBuilderAPI_Transform(shape, trsf).Shape()

def rotate_shape(shape, ax, angle):
    """旋转形状"""
    trsf = gp_Trsf()
    trsf.SetRotation(ax, angle)
    return BRepBuilderAPI_Transform(shape, trsf).Shape()

# ========== 基础形状生成器 ==========

def make_box(w, h, d):
    """方块 Box"""
    return BRepPrimAPI_MakeBox(w, h, d).Shape()

def make_cylinder(r, h):
    """圆柱 Cylinder"""
    return BRepPrimAPI_MakeCylinder(r, h).Shape()

def make_tube(outer_r, inner_r, h):
    """空心管 Tube"""
    outer = BRepPrimAPI_MakeCylinder(outer_r, h).Shape()
    inner = BRepPrimAPI_MakeCylinder(inner_r, h).Shape()
    return BRepAlgoAPI_Cut(outer, inner).Shape()

def make_cone(bottom_r, top_r, h):
    """截头锥 Truncated Cone"""
    return BRepPrimAPI_MakeCone(bottom_r, top_r, h).Shape()

def make_sphere(r):
    """球体 Sphere"""
    return BRepPrimAPI_MakeSphere(r).Shape()

def make_torus(major_r, minor_r):
    """环面 Torus"""
    return BRepPrimAPI_MakeTorus(major_r, minor_r).Shape()

# ========== 机械零件生成器 ==========

def make_flange(outer_r, inner_r, hole_r, thickness):
    """法兰 Flange"""
    outer = BRepPrimAPI_MakeCylinder(outer_r, thickness).Shape()
    hole = BRepPrimAPI_MakeCylinder(hole_r, thickness + 2).Shape()
    return BRepAlgoAPI_Cut(outer, hole).Shape()

def make_flange_with_holes(outer_r, inner_r, hole_rs, hole_count, thickness):
    """法兰带孔 Flange with bolt holes"""
    outer = BRepPrimAPI_MakeCylinder(outer_r, thickness).Shape()
    inner_hole = BRepPrimAPI_MakeCylinder(inner_r, thickness + 2).Shape()
    result = BRepAlgoAPI_Cut(outer, inner_hole).Shape()
    
    # 添加螺栓孔
    for i in range(hole_count):
        angle = i * 2 * 3.14159 / hole_count
        x = outer_r * 0.8 * np.cos(angle) if 'np' in dir() else outer_r * 0.8 * __import__('math').cos(angle)
        y = outer_r * 0.8 * __import__('math').sin(angle)
        bolt_hole = BRepPrimAPI_MakeCylinder(hole_rs, thickness + 2).Shape()
        bolt_hole = translate_shape(bolt_hole, x, y, 0)
        result = BRepAlgoAPI_Cut(result, bolt_hole).Shape()
    
    return result

def make_shaft(segments):
    """多级轴 Shaft segments = [(r, h), ...]"""
    if not segments:
        return None
    
    first = True
    result = None
    y = 0
    
    for i, (r, h) in enumerate(segments):
        cyl = BRepPrimAPI_MakeCylinder(r, h).Shape()
        cyl = translate_shape(cyl, 0, y, 0)
        
        if first:
            result = cyl
            first = False
        else:
            result = BRepAlgoAPI_Fuse(result, cyl).Shape()
        
        y += h
    
    return result

def make_bracket(w, h, thickness, hole_r=None):
    """角码 Bracket (L型)"""
    import math
    # 垂直部分
    v = BRepPrimAPI_MakeBox(thickness, h, thickness).Shape()
    # 水平部分
    h_box = BRepPrimAPI_MakeBox(w - thickness, thickness, thickness).Shape()
    h_box = translate_shape(h_box, thickness, 0, 0)
    # 融合
    bracket = BRepAlgoAPI_Fuse(v, h_box).Shape()
    
    if hole_r:
        # 简单方法：在中心偏下位置挖一个垂直的孔
        hole = BRepPrimAPI_MakeCylinder(hole_r, thickness * 3).Shape()
        hole = translate_shape(hole, w / 2, h / 2, -thickness)  # 放在顶部附近
        bracket = BRepAlgoAPI_Cut(bracket, hole).Shape()
    
    return bracket

def make_punched_plate(w, h, thickness, hole_rs, spacing=10):
    """打孔板 Punched Plate"""
    import math
    
    plate = BRepPrimAPI_MakeBox(w, h, thickness).Shape()
    
    rows = max(1, int(h / spacing))
    cols = max(1, int(w / spacing))
    
    for i in range(rows):
        for j in range(cols):
            for r in hole_rs:
                x = j * spacing + spacing / 2 - w / 2
                y = i * spacing + spacing / 2 - h / 2
                hole = BRepPrimAPI_MakeCylinder(r, thickness + 2).Shape()
                hole = translate_shape(hole, x, y, 0)
                plate = BRepAlgoAPI_Cut(plate, hole).Shape()
    
    return plate

def make_gear_wheel(external_r, thickness, tooth_count, module=None):
    """齿轮 Wheel (简化)"""
    import math
    if module is None:
        module = external_r * 2 / tooth_count
    
    pitch_r = module * tooth_count / 2
    gear = BRepPrimAPI_MakeCylinder(pitch_r + module, thickness).Shape()
    
    # 简化为带齿形的圆柱
    return gear

def make_spring(inner_r, outer_r, height, coils):
    """弹簧 Spring (简化)"""
    # 简化: 用环面堆叠
    shape = None
    import math
    pitch = height / coils
    for i in range(coils):
        angle = i * 2 * math.pi
        y = i * pitch
        torus = BRepPrimAPI_MakeTorus((inner_r + outer_r) / 2, (outer_r - inner_r) / 2).Shape()
        torus = translate_shape(torus, 0, y, 0)
        if shape is None:
            shape = torus
        else:
            shape = BRepAlgoAPI_Fuse(shape, torus).Shape()
    return shape

def make_bearing(inner_r, outer_r, thickness, ball_count=8):
    """轴承 Bearing"""
    import math
    # 外圈
    outer = BRepPrimAPI_MakeCylinder(outer_r, thickness).Shape()
    inner = BRepPrimAPI_MakeCylinder(inner_r, thickness + 2).Shape()
    ring = BRepAlgoAPI_Cut(outer, inner).Shape()
    
    # 滚珠
    ball_r = (outer_r - inner_r) / 4
    pitch_circle = (inner_r + outer_r) / 2
    
    for i in range(ball_count):
        angle = i * 2 * math.pi / ball_count
        x = pitch_circle * math.cos(angle)
        y = pitch_circle * math.sin(angle)
        ball = BRepPrimAPI_MakeSphere(ball_r).Shape()
        ball = translate_shape(ball, x, y, thickness / 2)
        ring = BRepAlgoAPI_Fuse(ring, ball).Shape()
    
    return ring

def make_threaded_rod(r, length, pitch):
    """螺纹杆 Threaded Rod (简化)"""
    return BRepPrimAPI_MakeCylinder(r, length).Shape()

def make_washer(inner_r, outer_r, thickness):
    """垫圈 Washer"""
    outer = BRepPrimAPI_MakeCylinder(outer_r, thickness).Shape()
    inner = BRepPrimAPI_MakeCylinder(inner_r, thickness + 2).Shape()
    return BRepAlgoAPI_Cut(outer, inner).Shape()

# ========== 高级形状生成器 ==========

def make_hex_prism(r, h):
    """六角棱柱 Hexagonal Prism"""
    import math
    # 用拉伸多边形创建
    edges = []
    for i in range(6):
        angle1 = i * math.pi / 3
        angle2 = (i + 1) * math.pi / 3
        p1 = gp_Pnt(r * math.cos(angle1), r * math.sin(angle1), 0)
        p2 = gp_Pnt(r * math.cos(angle2), r * math.sin(angle2), 0)
        # .Edge() 直接返回 TopoDS_Edge（OCP 下 .Shape() 返回的是 Shape 基类,
        # MakeWire.Add() 严格只收 TopoDS_Edge — 实测 Edge_s 静态转换不存在）
        edge = BRepBuilderAPI_MakeEdge(GC_MakeSegment(p1, p2).Value()).Edge()
        edges.append(edge)
    
    # 创建闭合线
    wire_builder = BRepBuilderAPI_MakeWire()
    for edge in edges:
        wire_builder.Add(edge)
    # OCP 严格类型: MakeFace 只收 TopoDS_Wire; Shape() 返回的是 Shape 基类
    wire = wire_builder.Wire()
    
    # 创建面并拉伸
    face = BRepBuilderAPI_MakeFace(wire).Shape()
    prism = BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, h)).Shape()
    return prism

def make装配体_block_with_pin(block_w, block_h, block_d, pin_r, pin_h):
    """装配体 Block with Pin"""
    block = BRepPrimAPI_MakeBox(block_w, block_h, block_d).Shape()
    pin = BRepPrimAPI_MakeCylinder(pin_r, pin_h).Shape()
    pin = translate_shape(pin, block_w / 2, block_h / 2, 0)
    return BRepAlgoAPI_Fuse(block, pin).Shape()

# ========== 命令行接口 ==========

def cmd_box(w, h, d):
    shape = make_box(w, h, d)
    filepath = os.path.join(STEP_OUTPUT_DIR, f"occ_box_{w}x{h}x{d}_{timestamp()}.step")
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(filepath)
    print(f"OCC_OUTPUT: {filepath}")
    return filepath

def cmd_cylinder(r, h):
    shape = make_cylinder(r, h)
    filepath = os.path.join(STEP_OUTPUT_DIR, f"occ_cyl_r{r}h{h}_{timestamp()}.step")
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(filepath)
    print(f"OCC_OUTPUT: {filepath}")
    return filepath

def cmd_tube(outer_r, inner_r, h):
    shape = make_tube(outer_r, inner_r, h)
    filepath = os.path.join(STEP_OUTPUT_DIR, f"occ_tube_or{outer_r}ir{inner_r}h{h}_{timestamp()}.step")
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(filepath)
    print(f"OCC_OUTPUT: {filepath}")
    return filepath

def cmd_flange(outer_r, inner_r, hole_r, thickness):
    shape = make_flange(outer_r, inner_r, hole_r, thickness)
    filepath = os.path.join(STEP_OUTPUT_DIR, f"occ_flange_or{outer_r}hr{hole_r}h{thickness}_{timestamp()}.step")
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(filepath)
    print(f"OCC_OUTPUT: {filepath}")
    return filepath

def cmd_bracket(w, h, thickness, hole_r=None):
    shape = make_bracket(w, h, thickness, hole_r)
    params = f"{w}x{h}x{thickness}"
    if hole_r:
        params += f"_hr{hole_r}"
    filepath = os.path.join(STEP_OUTPUT_DIR, f"occ_bracket_{params}_{timestamp()}.step")
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(filepath)
    print(f"OCC_OUTPUT: {filepath}")
    return filepath

def cmd_shaft(segments_str):
    """segments = r1,h1-r2,h2-...  例如: 10,30-8,20-12,40"""
    segments = []
    for seg in segments_str.split('-'):
        r, h = map(float, seg.split(','))
        segments.append((r, h))
    shape = make_shaft(segments)
    filepath = os.path.join(STEP_OUTPUT_DIR, f"occ_shaft_{segments_str}_{timestamp()}.step")
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(filepath)
    print(f"OCC_OUTPUT: {filepath}")
    return filepath

def cmd_punched_plate(w, h, thickness, hole_rs_str, spacing=10):
    hole_rs = [float(r) for r in hole_rs_str.split(',')]
    shape = make_punched_plate(w, h, thickness, hole_rs, spacing)
    filepath = os.path.join(STEP_OUTPUT_DIR, f"occ_punched_w{w}h{h}t{thickness}_{timestamp()}.step")
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(filepath)
    print(f"OCC_OUTPUT: {filepath}")
    return filepath

def cmd_bearing(inner_r, outer_r, thickness, ball_count=8):
    shape = make_bearing(inner_r, outer_r, thickness, ball_count)
    filepath = os.path.join(STEP_OUTPUT_DIR, f"occ_bearing_ir{inner_r}or{outer_r}t{thickness}_{timestamp()}.step")
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(filepath)
    print(f"OCC_OUTPUT: {filepath}")
    return filepath

def cmd_hex_prism(r, h):
    shape = make_hex_prism(r, h)
    filepath = os.path.join(STEP_OUTPUT_DIR, f"occ_hex_r{r}h{h}_{timestamp()}.step")
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(filepath)
    print(f"OCC_OUTPUT: {filepath}")
    return filepath

def run_tests():
    """运行所有测试"""
    print("=== STEP Factory OCC Tests ===")
    
    def save(shape, name):
        filepath = os.path.join(STEP_OUTPUT_DIR, f"{name}_{timestamp()}.step")
        writer = STEPControl_Writer()
        # OCP 严格类型: Transfer 需要 STEPControl_StepModelType 枚举, 不可传整数
        writer.Transfer(shape, STEPControl_AsIs)
        writer.Write(filepath)
        print(f"OCC_CREATED: {filepath}")
    
    # Box
    save(make_box(30, 40, 50), "test_box_30x40x50")
    
    # Cylinder
    save(make_cylinder(15, 60), "test_cyl_r15h60")
    
    # Tube
    save(make_tube(25, 15, 80), "test_tube_or25ir15h80")
    
    # Flange
    save(make_flange(40, 20, 10, 8), "test_flange_or40hr10h8")
    
    # Bracket with hole
    save(make_bracket(60, 40, 5, 6), "test_bracket_60x40x5_hr6")
    
    # Shaft with steps
    save(make_shaft([(10, 30), (8, 20), (12, 40)]), "test_shaft_10x30-8x20-12x40")
    
    # Bearing
    save(make_bearing(10, 30, 8, 10), "test_bearing_ir10or30t8")
    
    # Hex prism
    save(make_hex_prism(20, 50), "test_hex_r20h50")
    
    print("=== All OCC tests completed ===")

# 为 Shape 添加 exportStep 方法（如果缺失）
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Shape

def export_shape(shape, filepath):
    """导出形状为 STEP"""
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(filepath)
    return filepath

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        try:
            if cmd == "box" and len(sys.argv) > 4:
                cmd_box(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
            elif cmd == "cyl" and len(sys.argv) > 3:
                cmd_cylinder(float(sys.argv[2]), float(sys.argv[3]))
            elif cmd == "tube" and len(sys.argv) > 4:
                cmd_tube(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
            elif cmd == "flange" and len(sys.argv) > 5:
                cmd_flange(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]))
            elif cmd == "bracket" and len(sys.argv) > 4:
                hr = float(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] != 'None' else None
                cmd_bracket(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), hr)
            elif cmd == "shaft" and len(sys.argv) > 2:
                cmd_shaft(sys.argv[2])
            elif cmd == "punched_plate" and len(sys.argv) > 5:
                cmd_punched_plate(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), sys.argv[5])
            elif cmd == "bearing" and len(sys.argv) > 4:
                bc = int(sys.argv[5]) if len(sys.argv) > 5 else 8
                cmd_bearing(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), bc)
            elif cmd == "hex" and len(sys.argv) > 3:
                cmd_hex_prism(float(sys.argv[2]), float(sys.argv[3]))
            elif cmd == "test" or cmd == "run_tests":
                run_tests()
            else:
                print("Usage: step_occ.py <command> [args]")
                print("Commands:")
                print("  box W H D")
                print("  cyl R H")
                print("  tube OUTER_R INNER_R H")
                print("  flange OR IR HR H")
                print("  bracket W H T [HR]")
                print("  shaft r1,h1-r2,h2-...")
                print("  punched_plate W H T HOLE_RS[,...] [SPACING]")
                print("  bearing IR OR T [BALL_COUNT]")
                print("  hex R H")
                print("  test - run all tests")
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
    else:
        run_tests()