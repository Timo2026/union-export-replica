#!/home/Developer/miniconda3/envs/lk-skills/bin/python
# -*- coding: utf-8 -*-
"""
STEP Factory - FreeCAD CAD 模型生成器
用法: /usr/bin/freecadcmd step_generator.py [command] [args]
通过 stdin 执行脚本模式运行
"""
import sys
import os
from datetime import datetime

STEP_OUTPUT_DIR = "/home/Developer/STEP"
os.makedirs(STEP_OUTPUT_DIR, exist_ok=True)

def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def export_step(shape, prefix, params_str):
    """导出 STEP 文件"""
    ts = timestamp()
    filename = f"{prefix}_{params_str}_{ts}.step"
    filepath = os.path.join(STEP_OUTPUT_DIR, filename)
    shape.exportStep(filepath)
    print(f"STEP_FACTORY_OUTPUT: {filepath}")
    return filepath

# ========== 命令处理 ==========
if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "box" and len(sys.argv) > 4:
            w, h, d = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
            box = Part.makeBox(w, h, d)
            export_step(box, "box", f"{w}x{h}x{d}")
            
        elif cmd == "cyl" and len(sys.argv) > 3:
            r, h = float(sys.argv[2]), float(sys.argv[3])
            cyl = Part.makeCylinder(r, h)
            export_step(cyl, "cyl", f"r{r}h{h}")
            
        elif cmd == "tube" and len(sys.argv) > 4:
            outer_r, inner_r, h = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
            outer = Part.makeCylinder(outer_r, h)
            inner = Part.makeCylinder(inner_r, h)
            tube = outer.cut(inner)
            export_step(tube, "tube", f"or{outer_r}ir{inner_r}h{h}")
            
        elif cmd == "sphere" and len(sys.argv) > 2:
            r = float(sys.argv[2])
            sphere = Part.makeSphere(r)
            export_step(sphere, "sphere", f"r{r}")
            
        elif cmd == "cone" and len(sys.argv) > 4:
            bottom_r, top_r, h = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
            cone = Part.makeCone(bottom_r, top_r, h)
            export_step(cone, "cone", f"br{bottom_r}tr{top_r}h{h}")
            
        elif cmd == "flange" and len(sys.argv) > 5:
            outer_r, inner_r, hole_r, thickness = map(float, sys.argv[2:6])
            outer = Part.makeCylinder(outer_r, thickness)
            hole = Part.makeCylinder(hole_r, thickness + 2)
            flange = outer.cut(hole)
            export_step(flange, "flange", f"or{outer_r}hr{hole_r}h{thickness}")
            
        elif cmd == "bracket" and len(sys.argv) > 4:
            w, h, thickness = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
            hole_r = float(sys.argv[5]) if len(sys.argv) > 5 else None
            
            # L型支架
            v = Part.makeBox(thickness, h, thickness)
            h_box = Part.makeBox(w - thickness, thickness, thickness)
            h_box.translate(FreeCAD.Vector(thickness, 0, 0))
            bracket = v.fuse(h_box)
            
            if hole_r:
                hole = Part.makeCylinder(hole_r, thickness * 2)
                hole.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 1, 0), 90)
                hole.translate(FreeCAD.Vector(w/2, h/2, 0))
                bracket = bracket.cut(hole)
            
            export_step(bracket, "bracket", f"{w}x{h}x{thickness}")
            
        elif cmd == "shaft" and len(sys.argv) > 2:
            # segments = r1,h1-r2,h2-...
            segments_str = sys.argv[2]
            segments = []
            y = 0
            first = True
            result = None
            for seg in segments_str.split('-'):
                r, h = map(float, seg.split(','))
                cyl = Part.makeCylinder(r, h)
                cyl.translate(FreeCAD.Vector(0, y, 0))
                if first:
                    result = cyl
                    first = False
                else:
                    result = result.fuse(cyl)
                y += h
            export_step(result, "shaft", segments_str.replace(',', 'x').replace('-', '_'))
            
        elif cmd == "punched_plate" and len(sys.argv) > 5:
            w, h, thickness = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
            hole_rs = [float(r) for r in sys.argv[5].split(',')]
            spacing = float(sys.argv[6]) if len(sys.argv) > 6 else sum(hole_rs) / len(hole_rs)
            
            plate = Part.makeBox(w, h, thickness)
            dx = spacing
            dy = spacing
            rows = max(1, int(h / dy))
            cols = max(1, int(w / dx))
            
            for i in range(rows):
                for j in range(cols):
                    for r in hole_rs:
                        x = j * dx + dx/2 - w/2
                        y_pos = i * dy + dy/2 - h/2
                        hole = Part.makeCylinder(r, thickness + 2)
                        hole.translate(FreeCAD.Vector(x, y_pos, 0))
                        plate = plate.cut(hole)
            
            export_step(plate, "punched_plate", f"{w}x{h}x{thickness}_holes{len(hole_rs)}")
            
        elif cmd == "test":
            # 运行所有测试
            box = Part.makeBox(30, 40, 50)
            export_step(box, "box", "30x40x50")
            
            cyl = Part.makeCylinder(15, 60)
            export_step(cyl, "cyl", "r15h60")
            
            outer = Part.makeCylinder(25, 80)
            inner = Part.makeCylinder(15, 80)
            tube = outer.cut(inner)
            export_step(tube, "tube", "or25ir15h80")
            
            outer = Part.makeCylinder(40, 8)
            hole = Part.makeCylinder(10, 10)
            flange = outer.cut(hole)
            export_step(flange, "flange", "or40hr10h8")
            
            v = Part.makeBox(5, 40, 5)
            h_box = Part.makeBox(60, 5, 5)
            h_box.translate(FreeCAD.Vector(5, 0, 0))
            bracket = v.fuse(h_box)
            hole = Part.makeCylinder(6, 10)
            hole.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 1, 0), 90)
            hole.translate(FreeCAD.Vector(30, 20, 0))
            bracket = bracket.cut(hole)
            export_step(bracket, "bracket", "65x40x5_hr6")
            
            print("STEP_FACTORY_TEST_COMPLETE")
            
        else:
            print("STEP_FACTORY_ERROR: Unknown command or missing args")
            print("Commands: box W H D | cyl R H | tube OR IR H | sphere R | cone BR TR H | flange OR IR HR H | bracket W H T [HR] | shaft r1,h1-r2,h2 | punched_plate W H T RS1,RS2... | test")
    else:
        # 无参数则运行测试
        cmd = "test"