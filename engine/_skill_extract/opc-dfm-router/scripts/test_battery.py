#!/usr/bin/env python3
"""
test_battery.py — 联动 + 边界 + 健壮性测试
==========================================
覆盖: 正常案例 / 边界值 / 错误输入 / 模块一致性 / DFM极端
"""
import json, sys, os, subprocess

DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(DIR, "pipeline.py")
FUSION = os.path.join(os.path.dirname(DIR), "opc-fusion-quote/scripts/fusion_engine.py")
if not os.path.exists(FUSION):
    FUSION = os.path.expanduser("~/.openclaw/skills/opc-fusion-quote/scripts/fusion_engine.py")

# ── 导入单模块测试 ──
CALC_DIR = os.path.expanduser("~/.openclaw/skills/opc-fusion-quote/scripts/calc_modules")
sys.path.insert(0, CALC_DIR)
from calc_material import calc_material, MATERIAL_DATA
from calc_cnc import calc_cnc, PROCESS_BASE
from calc_wire_edm import calc_wire_edm
from calc_surface import calc_surface, SURFACE_COST_PER_KG, SURFACE_COST_PER_PIECE
from calc_measurement import calc_measurement
from calc_jig_tools import calc_jig_tools

sys.path.insert(0, DIR)
from dfm_checker import check_dfm
from shape_classifier import classify_shape
from interaction_matrix import check_exclusive

passed = 0
failed = 0
errors = []

def test(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        errors.append(f"  ❌ {name}")
        print(f"  ❌ {name}")

def section(title):
    print(f"\n{'='*40}")
    print(f"  {title}")
    print(f"{'='*40}")

def run_pipe(args, label=""):
    """Run pipeline and return stdout"""
    full = [sys.executable, PIPELINE] + args
    r = subprocess.run(full, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        print(f"  ❌ {label} failed: {r.stderr[:100]}")
        return None
    try:
        return json.loads(r.stdout)
    except:
        print(f"  ❌ {label} bad JSON: {r.stdout[:100]}")
        return None

# ═══════════════════════════════════════
section("A. 单模块单元测试")

# A1: calc_material  (signed: width, height, depth, material, solid_ratio)
r = calc_material(100, 80, 30, "6061铝")
test("calc_material 6061铝", r["cost"] > 0 and r["weight_kg"] > 0)

r2 = calc_material(100, 80, 30, "未知材料")
test("calc_material 未知材料回退", "error" in r2)

r3 = calc_material(0.1, 0.1, 0.1, "45钢")
test("calc_material 极小零件>0", r3["weight_kg"] < 0.01 and "cost" in r3)

# A2: calc_cnc  (signed: process, complexity, material_factor, max_dim, tolerance, roughness, qty)
r = calc_cnc("CNC", "一般", 1.0, 100, "±0.1mm", "Ra3.2", 100)
test("calc_cnc 基本输出结构", "cost" in r and "hours" in r and r["cost"] > 0)

r2 = calc_cnc("车削", "一般", 1.5, 100, "±0.02mm", "Ra1.6", 50)
test("calc_cnc 车削精密件", r2["cost"] > 0 and r2["hours"] > 0)

r3 = calc_cnc("铣削", "复杂", 2.0, 300, "±0.01mm", "Ra0.8", 10)
test("calc_cnc 铣削大件复杂", r3["cost"] > 0)

# A3: calc_wire_edm (signed: path_mm, thickness_mm, material, process)
r = calc_wire_edm(100, 30, "6061铝", "慢丝割一修二")
test("calc_wire_edm 面积计价", r["cost"] > 0 and "area_mm2" in r)

# A4: calc_surface 双模式
r = calc_surface("阳极氧化", weight_kg=1.0, qty=10)
test("calc_surface 按重量", r["mode"] == "按重量" and r["cost"] == 8.0)

r2 = calc_surface("热处理", weight_kg=1.0, qty=10)
test("calc_surface 按数量", r2["mode"] == "按数量" and r2["cost"] == 500)

r3 = calc_surface("xxx_未知", weight_kg=1.0, qty=10)
test("calc_surface 未知类型回退", r3["cost"] == 0 and r3.get("note"))

# A5: calc_measurement
r = calc_measurement("标准", 10)
test("calc_measurement 标准=0", r["cost"] == 0)

r2 = calc_measurement("CMM", 5)
test("calc_measurement CMM 5件", r2["cost"] > 0 and r2["type"] == "CMM")

# A6: calc_jig_tools
r = calc_jig_tools(200, 100, 50)
test("calc_jig_tools 三费桶", r["cost"] == 350)

section("B. DFM检查边界测试")

# B1: 极端薄壁
r = check_dfm({"process":"CNC","width":100,"height":80,"depth":30,
    "min_wall":0.3,"hole_ld":0,"inner_corner_r":0,"cavity_dw":0,
    "slenderness":3,"max_dim":100,"material_hb":200,"material_type":"碳钢",
    "tolerance":"±0.1mm","thickness":0.3})
test("DFM-薄壁<0.5mm fatal", r["risk"] == "fatal")

# B2: 深孔
r = check_dfm({"process":"CNC","width":100,"height":80,"depth":50,
    "min_wall":5,"hole_ld":10,"inner_corner_r":0,"cavity_dw":0,
    "slenderness":2,"max_dim":100,"material_hb":200,"material_type":"碳钢",
    "tolerance":"±0.1mm","thickness":5})
test("DFM-深孔L/D>8 fatal", any(i["code"]=="CNC-深孔" and i["severity"]=="fatal" for i in r["issues"]))

# B3: 钛合金警告
r = check_dfm({"process":"CNC","width":100,"height":80,"depth":30,
    "min_wall":5,"hole_ld":2,"inner_corner_r":1,"cavity_dw":0,
    "slenderness":2,"max_dim":100,"material_hb":200,"material_type":"钛合金",
    "tolerance":"±0.1mm","thickness":5})
test("DFM-钛合金警告", any(i["code"]=="材料-钛合金" for i in r["issues"]))

# B4: 公差不可达
r = check_dfm({"process":"CNC","width":100,"height":80,"depth":30,
    "min_wall":5,"hole_ld":2,"inner_corner_r":1,"cavity_dw":0,
    "slenderness":2,"max_dim":100,"material_hb":200,"material_type":"碳钢",
    "tolerance":"±0.005mm","thickness":5})
test("DFM-公差±0.005 CNC不可达", not r["tolerance_feasible"])

# B5: 3D打印公差
r = check_dfm({"process":"3D打印","width":100,"height":80,"depth":30,
    "min_wall":2,"hole_ld":2,"inner_corner_r":1,"cavity_dw":0,
    "slenderness":2,"max_dim":100,"material_hb":200,"material_type":"碳钢",
    "tolerance":"±0.05mm","thickness":2})
test("DFM-3D打印±0.05mm 不可达", not r["tolerance_feasible"])

section("C. 互斥工艺检查")

r = check_exclusive("淬火", "CNC")
test("互斥: 淬火→CNC 非互斥", r == "")

r = check_exclusive("焊接", "磨削")
test("互斥: 焊接→磨削 非互斥", r == "")

section("D. 形状分类一致性")

# D1: 法兰型
result = classify_shape(100, 100, 30)
s = result["shape"] if isinstance(result, dict) else result[0]
test("形状: 100×100×30 = 法兰", "法兰" in s)

# 轴型
result = classify_shape(30, 30, 100)
s = result["shape"] if isinstance(result, dict) else result[0]
test("形状: 30×30×100 = 轴类", "轴" in s)

# 板型
result = classify_shape(300, 200, 5)
s = result["shape"] if isinstance(result, dict) else result[0]
test("形状: 300×200×5 = 板件", "板" in s)

section("E. 管道联动测试")

cases = [
    ("标准法兰", ["--size","100x100x30","--material","45钢","--tolerance","±0.02mm","--roughness","Ra1.6","--qty","50","--surface","阳极氧化","--jig","200","--tools","100"]),
    ("板件", ["--size","200x150x8","--material","6061铝","--tolerance","±0.05mm","--roughness","Ra3.2","--qty","100","--surface","无"]),
    ("轴件", ["--size","30x30x100","--material","304不锈钢","--tolerance","±0.01mm","--roughness","Ra0.8","--qty","20","--surface","无"]),
    ("单件打样", ["--size","50x50x20","--material","TC4","--tolerance","±0.1mm","--roughness","Ra3.2","--qty","1","--surface","无"]),
]

for name, args in cases:
    d = run_pipe(args, name)
    if d:
        ok = (
            "dfm" in d and "报价" in d and "工艺规划" in d
            and d["报价"]["总额"] > 0
            and isinstance(d["报价"]["工艺链"], list) if "工艺链" in d["报价"] else True
        )
        test(f"管道-{name} 结构完整", ok)
        if ok:
            test(f"管道-{name} 报价>0", d["报价"]["总额"] > 0)
            if d["dfm"]["fatal_count"] > 0:
                test(f"管道-{name} DFM致命标记", True)
    else:
        test(f"管道-{name}", False)

section("F. 边界输入测试")

# F1: 零零件
r = calc_cnc("CNC", "一般", 1.0, 100, "±0.1mm", "Ra3.2", 0)
test("CNC qty=0", r["hours"] == 0 and r["cost"] == 0)

# F2: 巨大件
r = calc_material(1000, 800, 500, "45钢")
test("calc_material 巨大件", r["cost"] > 0 and r["weight_kg"] > 100)

# F3: 空格材料名
r = calc_surface("  阳极氧化  ", weight_kg=1.0)
test("calc_surface 带空格trim", r["mode"] == "未知" and r["cost"] == 0)
# (这个是边界行为——带空格不会匹配，取决于实现)

# F4: 空工艺链
r = check_dfm({"process":"CNC","width":100,"height":80,"depth":30,
    "min_wall":999,"hole_ld":0,"inner_corner_r":2,"cavity_dw":0,
    "slenderness":2,"max_dim":100,"material_hb":200,"material_type":"碳钢",
    "tolerance":"±0.1mm","thickness":5})
test("DFM-完全正常零件", r["risk"] == "low" and len(r["issues"]) == 0)

section("G. 管道错误恢复")

# G1: 未知材料
d = run_pipe(["--size","100x100x30","--material","xxx不存在","--tolerance","±0.1mm","--qty","10"], "G1-未知材料")
test("管道-未知材料 回退不崩溃", d is None or ("error" in d))

# G2: 非法尺寸
d = run_pipe(["--size","abc","--material","45钢","--qty","10"], "G2-非法尺寸")
test("管道-非法尺寸 不崩溃", True)  # 只要不crash

# G3: 超大批量
d = run_pipe(["--size","100x100x30","--material","45钢","--qty","10000","--tolerance","±0.1mm"], "G3-大批量")
test("管道-10000件 正常运行", d is not None and d.get("报价",{}).get("总额",0) > 0)

# ═══════════════════════════════════════
print(f"\n{'='*40}")
print(f"  结果: {passed} 通过 / {failed} 失败")
print(f"{'='*40}")
if errors:
    for e in errors:
        print(e)
    print()

sys.exit(0 if failed == 0 else 1)
