#!/usr/bin/env python3
"""
pipeline.py — DFM Router → Fusion Quote 完整管道
=================================================
输入: feature.json (或CLI参数模拟)
输出: 完整报价 + DFM检查报告

管道: feature → DFM router (形状→工艺→检查) → Fusion Quote (报价)
"""
import json, sys, os, argparse, subprocess

DIR = os.path.dirname(os.path.abspath(__file__))
ROUTER_PY = os.path.join(DIR, "router.py")
FUSION_PY = os.path.join(os.path.dirname(DIR), "opc-fusion-quote/scripts/fusion_engine.py")
# 如果 fusion_engine 不在相对路径, 尝试绝对路径
if not os.path.exists(FUSION_PY):
    FUSION_PY = os.path.expanduser("~/.openclaw/skills/opc-fusion-quote/scripts/fusion_engine.py")


def run_pipeline(feature_json: dict) -> dict:
    """
    完整管道。
    输入 feature_json:
    {
      "size": "100x100x30",
      "material": "45钢",
      "tolerance": "±0.02mm",
      "roughness": "Ra1.6",
      "qty": 50,
      "surface": "阳极氧化"
    }
    输出: 含 dfm + process_plan + quote 的完整报告
    """
    # Step 1: DFM Router
    router_args = [
        "python3", ROUTER_PY,
        "--size", feature_json.get("size", "100x100x30"),
        "--material", feature_json.get("material", "45钢"),
        "--tolerance", feature_json.get("tolerance", "±0.1mm"),
        "--roughness", feature_json.get("roughness", "Ra3.2"),
        "--qty", str(feature_json.get("qty", 100)),
    ]
    if feature_json.get("surface") and feature_json["surface"] != "无":
        router_args += ["--surface", feature_json["surface"]]
    if feature_json.get("step"):
        router_args += ["--step", feature_json["step"]]

    r1 = subprocess.run(router_args, capture_output=True, text=True, timeout=30)
    if r1.returncode != 0:
        return {"error": "Router failed", "stderr": r1.stderr[:500]}
    try:
        process_plan = json.loads(r1.stdout)
    except json.JSONDecodeError:
        return {"error": "Router invalid JSON", "stdout": r1.stdout[:500]}
    if "error" in process_plan:
        return {"error": f"Router: {process_plan['error']}"}

    # Step 2: Extract fusion params from process plan
    plan_summary = process_plan.get("summary", {})
    raw_chain = plan_summary.get("工艺链", feature_json.get("processes", "CNC:一般"))
    # Convert "CNC:一般 → 钻孔:简单 → 测量:标准" → "CNC:一般,钻孔:简单"
    # Strip measurement/post-process steps for fusion_quote
    steps = [s.strip() for s in raw_chain.replace("→", ",").split(",")]
    process_steps = [s for s in steps if s and not s.startswith("测量") and not s.startswith("检测")]
    process_chain = ",".join(process_steps) if process_steps else "CNC:一般"
    
    # Step 3: Fusion Quote
    fusion_args = [
        "python3", FUSION_PY,
        "--size", feature_json.get("size", "100x100x30"),
        "--material", feature_json.get("material", "45钢"),
        "--processes", process_chain,
        "--qty", str(feature_json.get("qty", 100)),
        "--tolerance", feature_json.get("tolerance", "±0.1mm"),
        "--roughness", feature_json.get("roughness", "Ra3.2"),
    ]
    if feature_json.get("surface") and feature_json["surface"] != "无":
        fusion_args += ["--surface", feature_json["surface"]]
    surface = feature_json.get("surface", "无")
    if surface and surface != "无":
        fusion_args += ["--surface", surface]
    if feature_json.get("jig"):
        fusion_args += ["--jig", str(feature_json["jig"])]
    if feature_json.get("tools"):
        fusion_args += ["--tools", str(feature_json["tools"])]
    if feature_json.get("other"):
        fusion_args += ["--other", str(feature_json["other"])]
    if feature_json.get("calibrate"):
        fusion_args += ["--calibrate", str(feature_json["calibrate"])]

    r2 = subprocess.run(fusion_args, capture_output=True, text=True, timeout=30)
    if r2.returncode != 0:
        return {"error": "Fusion quote failed", "stderr": r2.stderr[:500]}
    try:
        quote_result = json.loads(r2.stdout)
    except json.JSONDecodeError:
        return {"error": "Fusion quote invalid JSON", "stdout": r2.stdout[:500]}
    
    if "error" in quote_result:
        return {"error": quote_result["error"], "material": True}

    # Step 4: 合并
    return {
        "管道": "DFM Router → Fusion Quote v2.0",
        "dfm": process_plan.get("dfm", {}),
        "工艺规划": {
            "形状": process_plan.get("shape"),
            "工序": process_plan.get("plan", []),
            "交互效应": process_plan.get("interactions", []),
            "摘要": plan_summary,
        },
        "报价": {
            "总额": quote_result["成本汇总"]["报价总额"],
            "单价": quote_result["成本汇总"]["单价"],
            "材料费": quote_result["成本汇总"]["材料费"],
            "加工费": quote_result["成本汇总"]["加工费"],
            "表面处理费": quote_result["成本汇总"].get("表面处理费", 0),
            "工序明细": quote_result.get("工序明细", []),
            "引擎": quote_result.get("引擎", ""),
        },
        "交付": quote_result.get("交付", {}),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DFM Router → Fusion Quote 完整管道")
    parser.add_argument("--size", default="100x100x30", help="尺寸 宽x高x长mm")
    parser.add_argument("--material", "-m", default="45钢")
    parser.add_argument("--tolerance", "-t", default="±0.1mm")
    parser.add_argument("--roughness", default="Ra3.2")
    parser.add_argument("--qty", "-q", type=int, default=100)
    parser.add_argument("--surface", default="无")
    parser.add_argument("--jig", type=float)
    parser.add_argument("--tools", type=float)
    parser.add_argument("--other", type=float)
    parser.add_argument("--calibrate", type=float)
    parser.add_argument("--step")
    parser.add_argument("--json", help="直接从feature.json文件读取")
    args = parser.parse_args()

    if args.json:
        with open(args.json) as f:
            feature = json.load(f)
    else:
        feature = {
            "size": args.size,
            "material": args.material,
            "tolerance": args.tolerance,
            "roughness": args.roughness,
            "qty": args.qty,
            "surface": args.surface,
        }
        if args.jig: feature["jig"] = args.jig
        if args.tools: feature["tools"] = args.tools
        if args.other: feature["other"] = args.other
        if args.calibrate: feature["calibrate"] = args.calibrate
        if args.step: feature["step"] = args.step

    result = run_pipeline(feature)
    print(json.dumps(result, ensure_ascii=False, indent=2))
