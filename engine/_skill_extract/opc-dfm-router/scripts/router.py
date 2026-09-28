#!/usr/bin/env python3
"""
router.py — opc-dfm-router 主入口
================================
从 feature.json → 工艺规划 process_plan.json

管道: 形状分类 → 工艺判断 → 工序排序 → 交互修正
输出: 可直接喂给原子calc模块的工艺计划JSON
"""
import json, argparse, sys, os

sys.path.insert(0, os.path.dirname(__file__))
from shape_classifier import classify_shape, add_precision_processes
from sequence_optimizer import optimize_sequence, suggest_grouping
from interaction_matrix import (
    find_interaction, check_exclusive, is_final_only
)
from dfm_checker import check_dfm, TOLERANCE_CAPABILITY


def route(feature_json: dict) -> dict:
    """
    主路由函数。
    
    输入 feature_json:
    {
      "bbox": {"width": 100, "height": 100, "depth": 30},
      "material": "45钢",
      "tolerance": "±0.02mm",
      "roughness": "Ra1.6",
      "surface": "阳极氧化",
      "qty": 100,
      "features": ["通孔×4", "沉头孔×4"]
    }
    
    输出 process_plan:
    {
      "shape": "法兰",
      "confidence": 0.88,
      "plan": [
        {"seq": 1, "process": "CNC", "params": {...}},
        ...
      ],
      "interactions": [...]
    }
    """
    bbox = feature_json.get("bbox", {})
    features = feature_json.get("features", [])
    material = feature_json.get("material", "45钢")
    tolerance = feature_json.get("tolerance", "±0.1mm")
    roughness = feature_json.get("roughness", "Ra3.2")
    surface = feature_json.get("surface", "无")
    qty = feature_json.get("qty", 1)

    # ── 1. 形状分类 ──
    shape_result = classify_shape(
        bbox.get("width", 100),
        bbox.get("height", 80),
        bbox.get("depth", 30),
        features
    )

    # ── 2. 工艺判断：默认链 + 精度/Ra补充 ──
    default_plan = list(shape_result["default_plan"])
    full_plan = add_precision_processes(default_plan, tolerance, roughness)

    # 如果有表面处理需求且不等于"无"/"本色"
    if surface and surface not in ("无", "本色"):
        full_plan.append(f"{surface}:表面处理")

    # 添加测量工序
    full_plan.append("测量:标准")

    # ── 3. 工序排序 ──
    sorted_plan = optimize_sequence(full_plan, shape_result["shape"])

    # ── 4. 计算交互效应 ──
    interactions = []
    plan_with_params = []

    for i, proc in enumerate(sorted_plan):
        step = {
            "seq": i + 1,
            "process": proc,
            "params": _build_params(proc, material, tolerance, roughness, qty, bbox)
        }

        # 检查与前一步的交互
        if i > 0:
            prev_proc = sorted_plan[i - 1]
            interaction = find_interaction(prev_proc, proc)
            if interaction["time_factor"] != 1.0 or interaction["jig_factor"] != 1.0:
                interactions.append({
                    "from": i, "to": i + 1,
                    "from_process": prev_proc,
                    "to_process": proc,
                    **interaction
                })

        # 检查互斥
        if i > 0:
            exclusive = check_exclusive(sorted_plan[i - 1], proc)
            if exclusive:
                interactions.append({
                    "from": i, "to": i + 1,
                    "from_process": sorted_plan[i - 1],
                    "to_process": proc,
                    "effect": "mutually_exclusive",
                    "reason": f"保留'{exclusive}'，跳过'{sorted_plan[i-1]}'"
                })

        plan_with_params.append(step)

    # ── 5. DFM检查 ──
    main_process = "CNC" if "CNC" in str(default_plan) else (
        "车削" if "车削" in str(default_plan) else (
        "线切割" if "线切割" in str(default_plan) else "CNC"))
    
    dfm_params = {
        "process": main_process,
        "width": bbox.get("width", 100),
        "height": bbox.get("height", 80),
        "depth": bbox.get("depth", 30),
        "min_wall": bbox.get("min_wall", bbox.get("min_wall_thickness", 
            min(bbox.get("width",100), bbox.get("height",80), bbox.get("depth",30)))),
        "hole_ld": bbox.get("max_hole_depth", 0) / max(bbox.get("min_hole_dia", 1), 1),
        "inner_corner_r": bbox.get("min_inner_r", 0),
        "cavity_dw": bbox.get("max_cavity_depth", 0) / max(bbox.get("min_cavity_width", 1), 1),
        "slenderness": max(bbox.get("width",100), bbox.get("height",80), bbox.get("depth",30)) / 
                       max(min(bbox.get("width",100), bbox.get("height",80), bbox.get("depth",30)), 1),
        "max_dim": max(bbox.get("width",100), bbox.get("height",80), bbox.get("depth",30)),
        "material_hb": feature_json.get("material_hb", 200),
        "material_type": feature_json.get("material_type", "碳钢"),
        "tolerance": tolerance,
        "thickness": min(bbox.get("width",100), bbox.get("height",80), bbox.get("depth",30)),
        "processes": ",".join(full_plan),
        "bend_r": 0,
        "hole_edge": 0,
        "min_flange": 0,
        "escape_hole": 0,
        "has_closed_cavity": False,
        "overhang_angle": 0,
        "hole_d_min": 0,
        "min_thread": "M3",
    }
    dfm_result = check_dfm(dfm_params)

    # ── 6. 输出 ──
    return {
        "source": "opc-dfm-router v1.0",
        "timestamp": __import__('datetime').datetime.now().isoformat()[:19],
        "shape": shape_result["shape"],
        "confidence": shape_result["confidence"],
        "hint": shape_result["hint"],
        "plan": plan_with_params,
        "interactions": interactions,
        "dfm": dfm_result,
        "summary": {
            "材料": material,
            "公差": tolerance,
            "粗糙度": roughness,
            "表面处理": surface,
            "数量": qty,
            "工艺链": " → ".join(sorted_plan),
            "交互修正数": len([i for i in interactions if "mutually_exclusive" not in str(i)]),
            "互斥工艺": len([i for i in interactions if "mutually_exclusive" in str(i)])
        }
    }


def _build_params(proc: str, material: str, tolerance: str,
                  roughness: str, qty: int, bbox: dict) -> dict:
    """根据工艺类型构造参数字典"""
    pname = proc.split(":")[0] if ":" in proc else proc
    base = {
        "material": material,
        "qty": qty,
    }

    if "CNC" in proc or "铣" in proc:
        base.update({"volume_mm3": bbox.get("width", 100) * bbox.get("height", 80) * bbox.get("depth", 30),
                     "tolerance": tolerance, "roughness": roughness})
    elif "车削" in proc or "车" in proc:
        base.update({"diameter": max(bbox.get("width", 50), bbox.get("height", 50)),
                     "length": bbox.get("depth", 100)})
    elif "钻孔" in proc or "攻牙" in proc:
        base.update({"count": 4})  # 默认4孔
    elif "磨削" in proc or "磨" in proc:
        base.update({"area_mm2": max(bbox.get("width", 100), bbox.get("height", 80)) * bbox.get("depth", 30)})
    elif "线切割" in proc or "线割" in proc:
        base.update({"path_mm": bbox.get("depth", 100),
                     "thickness_mm": max(bbox.get("width", 50), bbox.get("height", 50))})

    return base


# ── CLI ──
def main():
    parser = argparse.ArgumentParser(description="DFM工艺路由器")
    parser.add_argument("input", nargs="?", help="feature.json 文件路径")
    parser.add_argument("--size", help="尺寸 宽x高x深mm")
    parser.add_argument("--material", "-m", default="45钢")
    parser.add_argument("--tolerance", "-t", default="±0.1mm")
    parser.add_argument("--roughness", "-ra", default="Ra3.2")
    parser.add_argument("--surface", "-s", default="无")
    parser.add_argument("--qty", "-q", type=int, default=1)
    parser.add_argument("--features", "-f", nargs="*", default=[])
    parser.add_argument("--output", "-o", help="输出JSON文件")
    args = parser.parse_args()

    if args.input and os.path.isfile(args.input):
        with open(args.input) as f:
            feature_json = json.load(f)
    elif args.size:
        parts = [float(x.strip()) for x in args.size.replace("x", "X").replace("×", "X").split("X")]
        feature_json = {
            "bbox": {"width": parts[0], "height": parts[1], "depth": parts[2]},
            "material": args.material,
            "tolerance": args.tolerance,
            "roughness": args.roughness,
            "surface": args.surface,
            "qty": args.qty,
            "features": args.features
        }
    else:
        print("❌ 需要 feature.json 文件或 --size 参数")
        return 1

    result = route(feature_json)
    json_out = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(json_out)
        print(f"✅ → {args.output}")
    else:
        print(json_out)

    return 0


if __name__ == "__main__":
    exit(main() or 0)
