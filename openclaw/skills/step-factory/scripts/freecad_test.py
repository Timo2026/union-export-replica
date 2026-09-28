#!/home/Developer/miniconda3/envs/lk-skills/bin/python
# -*- coding: utf-8 -*-
"""Test STEP generation via FreeCAD"""
import sys
import os
from datetime import datetime

# Add script directory to path
sys.path.insert(0, '/home/Developer/.openclaw/skills/step-factory/scripts')

import FreeCAD
import Part

STEP_OUTPUT_DIR = "/home/Developer/STEP"
os.makedirs(STEP_OUTPUT_DIR, exist_ok=True)

def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def gen_box(w, h, d):
    box = Part.makeBox(w, h, d)
    ts = timestamp()
    filename = f"box_{w}x{h}x{d}_{ts}.step"
    filepath = os.path.join(STEP_OUTPUT_DIR, filename)
    box.exportStep(filepath)
    print(f"Generated: {filepath}")
    return filepath

def gen_cylinder(r, h):
    cyl = Part.makeCylinder(r, h)
    ts = timestamp()
    filename = f"cyl_r{r}h{h}_{ts}.step"
    filepath = os.path.join(STEP_OUTPUT_DIR, filename)
    cyl.exportStep(filepath)
    print(f"Generated: {filepath}")
    return filepath

def gen_tube(outer_r, inner_r, h):
    outer = Part.makeCylinder(outer_r, h)
    inner = Part.makeCylinder(inner_r, h)
    tube = outer.cut(inner)
    ts = timestamp()
    filename = f"tube_or{outer_r}ir{inner_r}h{h}_{ts}.step"
    filepath = os.path.join(STEP_OUTPUT_DIR, filename)
    tube.exportStep(filepath)
    print(f"Generated: {filepath}")
    return filepath

# Run test
if __name__ == "__main__":
    gen_box(30, 40, 50)
    gen_cylinder(15, 60)
    gen_tube(25, 15, 80)
    print("All test parts generated!")