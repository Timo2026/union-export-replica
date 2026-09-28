#!/home/<user>/.miniconda/bin/python3
# -*- coding: utf-8 -*-
"""Minimal deterministic DFM checker.
Rule-based, conservative; does not claim full manufacturability approval.
"""
import argparse, json, re, sys

MATERIAL_LIMITS = {
    "aluminum": {"names": ["铝", "6061", "7075", "铝合金"], "min_wall": 1.5},
    "steel": {"names": ["钢", "不锈钢", "304", "316", "Q235", "45#"], "min_wall": 3.0},
    "titanium": {"names": ["钛", "TC4"], "min_wall": 4.0},
}

def nums_after(pattern, text):
    m = re.search(pattern, text, re.I)
    return float(m.group(1)) if m else None

def extract_wall(text):
    # 支持：壁厚0.8mm / 薄壁0.8mm / 厚度 1.2 / 厚8
    return nums_after(r'(?:壁厚|薄壁|厚度|厚)\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?', text)

def extract_hole_pair(text):
    # 稳健抓孔径/深度。避免“深孔100”被“孔100”误当孔径。
    d = nums_after(r'(?:孔径|孔直径|直径)\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?', text)
    if d is None:
        d = nums_after(r'孔(?!深)\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?', text)
    depth = nums_after(r'(?:孔深|深孔|深度)\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?', text)
    if depth is None:
        # 仅在已经有孔径时，才把“深100”识别为孔深，避免普通长度误判。
        depth = nums_after(r'深\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?', text) if d else None
    return d, depth

def detect_material(text):
    for key, cfg in MATERIAL_LIMITS.items():
        if any(n.lower() in text.lower() for n in cfg["names"]):
            return key, cfg
    return "unknown", {"min_wall": 2.0}

def check(text):
    mat, cfg = detect_material(text)
    risks=[]; suggestions=[]
    wall = extract_wall(text)
    hole_d, hole_depth = extract_hole_pair(text)
    inner_r = nums_after(r'(?:内角R|内R|R角|圆角R)\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?', text)
    tol = nums_after(r'(?:公差|精度)\s*[:：=±+\- ]*0?\.?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?', text)

    if wall is not None:
        min_wall = cfg["min_wall"]
        if wall < min_wall:
            risks.append({"level":"high","code":"thin_wall","message":f"壁厚{wall}mm低于{mat}建议下限{min_wall}mm，易变形/断裂"})
            suggestions.append(f"壁厚建议提高到≥{min_wall}mm，或改工艺/增加支撑/放宽加工要求")
        elif wall < min_wall * 1.3:
            risks.append({"level":"medium","code":"near_thin_wall_limit","message":f"壁厚{wall}mm接近建议下限，加工刚性需复核"})
            suggestions.append("评估装夹、刀路和变形控制，必要时分粗精加工")
    if hole_d and hole_depth:
        ratio = hole_depth / hole_d if hole_d else 0
        if ratio > 8:
            risks.append({"level":"high","code":"very_deep_hole","message":f"孔深径比{ratio:.1f}>8，普通钻削风险高"})
            suggestions.append("考虑枪钻、分段加工、放宽孔深/孔径或增加工艺孔")
        elif ratio > 5:
            risks.append({"level":"medium","code":"deep_hole","message":f"孔深径比{ratio:.1f}>5，需要加长刀具/排屑冷却方案"})
            suggestions.append("确认刀具有效长度、冷却排屑、孔直线度要求")
    if inner_r is not None and inner_r < 1.0:
        risks.append({"level":"medium","code":"small_inner_radius","message":f"内角R{inner_r}mm偏小，小刀具加工效率低且易断刀"})
        suggestions.append("内角R尽量加大；若必须尖角，考虑电火花/插角/二次加工")
    if tol is not None and tol <= 0.02:
        risks.append({"level":"medium","code":"tight_tolerance","message":f"公差约±{tol}mm，需精加工和检测方案"})
        suggestions.append("明确关键尺寸、检测基准、热处理/表面处理后的变形补偿")
    if any(k in text for k in ["阳极", "氧化", "电镀", "发黑", "喷涂"]):
        suggestions.append("表面处理前需确认遮蔽、膜厚、尺寸补偿和外观验收标准")
    if not risks:
        risks.append({"level":"low","code":"no_basic_rule_hit","message":"未命中基础高风险规则；不代表完整DFM通过"})
        suggestions.append("复杂结构仍需结合图纸、STEP、材料牌号和批量做人工/高级DFM复核")
    high=sum(1 for r in risks if r["level"]=="high")
    medium=sum(1 for r in risks if r["level"]=="medium")
    verdict = "需修改/复核" if high else ("可尝试但需工艺复核" if medium else "基础规则未发现明显阻塞")
    return {"status":"success","input":text,"material_detected":mat,"verdict":verdict,"risks":risks,"suggestions":suggestions,"confidence":0.62 if high or medium else 0.45,"note":"规则型基础DFM，不替代图纸/STEP完整评审"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input','-i', required=True)
    ap.add_argument('--json', action='store_true')
    args=ap.parse_args()
    res=check(args.input)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"结论: {res['verdict']}")
        for r in res['risks']:
            print(f"- [{r['level']}] {r['code']}: {r['message']}")
        print("建议:")
        for s in res['suggestions']:
            print(f"- {s}")
if __name__=='__main__':
    main()
