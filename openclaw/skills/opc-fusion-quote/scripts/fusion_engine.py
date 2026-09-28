#!/home/Developer/miniconda3/envs/lk-skills/bin/python
"""
OPC Fusion Quote Engine v2.0
体积法(物理) + 工序表法(精度) 三层融合

L1: 体积法自动估算 (包围盒→体积→重量→材料费)
L2: 形状推测工艺链 (包围盒比例→板/轴/异形→建议工序)
L3: 工序法精算 (用户工序×材料系数×尺寸×公差)
L4: 校准层 (按品类存储校准因子，喂真实报价就准)

Usage:
  python3 fusion_engine.py --material AL6061 --length 100 --width 50 --height 20 --quantity 10
  python3 fusion_engine.py --material 45钢 -l 200 -w 50 --height 50 -p 车削,铣削,钻孔 --json
  python3 fusion_engine.py -m 45钢 -l 200 -w 50 --height 50 --calibrate 5800 --category 轴类_45钢
  python3 fusion_engine.py --step part.step --material AL6061 --quantity 1
"""

import argparse, json, math, os, sqlite3, sys, time, re
from pathlib import Path

# === L1: 体积法 材料数据库 ===
MATERIAL_DB = {
    "AL6061":{"price_kg":30,"density":2.80,"machinability":0.80,"hardness_coef":1.0,"category":"铝","name":"6061铝合金"},
    "AL7075":{"price_kg":40,"density":2.81,"machinability":0.70,"hardness_coef":1.0,"category":"铝","name":"7075铝合金"},
    "AL2024":{"price_kg":50,"density":2.78,"machinability":0.70,"hardness_coef":1.0,"category":"铝","name":"2024铝合金"},
    "AL5052":{"price_kg":35,"density":2.68,"machinability":0.85,"hardness_coef":1.0,"category":"铝","name":"5052铝合金"},
    "SS304":{"price_kg":30,"density":7.85,"machinability":0.45,"hardness_coef":1.3,"category":"不锈钢","name":"304不锈钢"},
    "SS316":{"price_kg":40,"density":7.98,"machinability":0.40,"hardness_coef":1.3,"category":"不锈钢","name":"316不锈钢"},
    "SS440C":{"price_kg":60,"density":7.75,"machinability":0.25,"hardness_coef":1.8,"category":"不锈钢","name":"440C不锈钢"},
    "S45C":{"price_kg":12,"density":7.85,"machinability":0.65,"hardness_coef":1.0,"category":"碳钢","name":"45号钢"},
    "Q235":{"price_kg":10,"density":7.85,"machinability":0.70,"hardness_coef":1.0,"category":"碳钢","name":"Q235钢"},
    "40Cr":{"price_kg":15,"density":7.85,"machinability":0.55,"hardness_coef":1.2,"category":"合金钢","name":"40Cr钢"},
    "DC53":{"price_kg":80,"density":7.85,"machinability":0.20,"hardness_coef":1.8,"category":"模具钢","name":"DC53模具钢"},
    "SKD11":{"price_kg":55,"density":7.85,"machinability":0.25,"hardness_coef":1.8,"category":"模具钢","name":"SKD11模具钢"},
    "Cr12MoV":{"price_kg":35,"density":7.85,"machinability":0.30,"hardness_coef":1.8,"category":"模具钢","name":"Cr12MoV模具钢"},
    "D2":{"price_kg":55,"density":7.85,"machinability":0.25,"hardness_coef":1.8,"category":"模具钢","name":"D2模具钢"},
    "M2":{"price_kg":120,"density":8.16,"machinability":0.15,"hardness_coef":2.0,"category":"高速钢","name":"M2高速钢"},
    "TC4":{"price_kg":350,"density":4.43,"machinability":0.20,"hardness_coef":1.8,"category":"钛合金","name":"钛合金TC4"},
    "INCONEL":{"price_kg":600,"density":8.44,"machinability":0.10,"hardness_coef":2.5,"category":"高温合金","name":"因科镍合金"},
    "Brass-C360":{"price_kg":55,"density":8.50,"machinability":1.00,"hardness_coef":0.8,"category":"铜","name":"黄铜H65"},
    "C110":{"price_kg":70,"density":8.96,"machinability":0.90,"hardness_coef":0.8,"category":"铜","name":"紫铜C110"},
    "ABS":{"price_kg":25,"density":1.07,"machinability":1.50,"hardness_coef":0.5,"category":"塑料","name":"ABS塑料"},
    "PC":{"price_kg":45,"density":1.20,"machinability":1.20,"hardness_coef":0.5,"category":"塑料","name":"聚碳酸酯PC"},
    "PEEK":{"price_kg":600,"density":1.32,"machinability":0.80,"hardness_coef":0.6,"category":"塑料","name":"PEEK"},
    "POM":{"price_kg":30,"density":1.41,"machinability":1.30,"hardness_coef":0.5,"category":"塑料","name":"聚甲醛POM"},
    "PTFE":{"price_kg":150,"density":2.15,"machinability":1.10,"hardness_coef":0.5,"category":"塑料","name":"聚四氟乙烯"},
}
ALIASES = {
    "6061":"AL6061","7075":"AL7075","2024":"AL2024","5052":"AL5052",
    "304":"SS304","SUS304":"SS304","sus304":"SS304","316":"SS316",
    "SUS316":"SS316","316L":"SS316","440C":"SS440C",
    "TC4":"TC4","tc4":"TC4","Ti-6Al-4V":"TC4","钛合金":"TC4",
    "45":"S45C","S45C":"S45C","45钢":"S45C","45号钢":"S45C",
    "Q235":"Q235","40Cr":"40Cr",
    "DC53":"DC53","SKD11":"SKD11","Cr12MoV":"Cr12MoV","D2":"D2","M2":"M2",
    "黄铜":"Brass-C360","紫铜":"C110","H65":"Brass-C360",
    "ABS":"ABS","PC":"PC","PEEK":"PEEK","POM":"POM","PTFE":"PTFE",
    "INCONEL":"INCONEL","718":"INCONEL","哈氏合金":"INCONEL",
}
SURFACE_DB = {
    "":{"per_piece":0,"per_kg":0,"name":"无"},
    "无":{"per_piece":0,"per_kg":0,"name":"无"},
    "sandblasting":{"per_piece":5,"per_kg":15,"name":"喷砂"},
    "喷砂":{"per_piece":5,"per_kg":15,"name":"喷砂"},
    "anodizing":{"per_piece":4,"per_kg":25,"name":"阳极氧化"},
    "阳极氧化":{"per_piece":4,"per_kg":25,"name":"阳极氧化"},
    "plating":{"per_piece":50,"per_kg":100,"name":"电镀"},
    "电镀":{"per_piece":50,"per_kg":100,"name":"电镀"},
    "blackening":{"per_piece":0,"per_kg":12,"name":"发黑"},
    "发黑":{"per_piece":0,"per_kg":12,"name":"发黑"},
    "hard_anodize":{"per_piece":6,"per_kg":35,"name":"硬质阳极氧化"},
    "硬氧":{"per_piece":6,"per_kg":35,"name":"硬质阳极氧化"},
    "passivation":{"per_piece":2,"per_kg":8,"name":"钝化"},
    "钝化":{"per_piece":2,"per_kg":8,"name":"钝化"},
    "powder_coating":{"per_piece":10,"per_kg":20,"name":"喷塑"},
    "喷塑":{"per_piece":10,"per_kg":20,"name":"喷塑"},
}

# === L2: 工序法 ===
PROCESS_DB = {
    "车削":{"rate":80,"unit":"h","setup_min":15,"desc":"车床加工"},
    "铣削":{"rate":80,"unit":"h","setup_min":20,"desc":"铣床加工"},
    "钻孔":{"rate":60,"unit":"h","setup_min":10,"desc":"钻床加工"},
    "磨削":{"rate":120,"unit":"h","setup_min":30,"desc":"磨床加工"},
    "线切割":{"rate":50,"unit":"h","setup_min":25,"desc":"线切割"},
    "电火花":{"rate":90,"unit":"h","setup_min":30,"desc":"EDM电火花"},
    "折弯":{"rate":40,"unit":"h","setup_min":10,"desc":"折弯加工"},
    "激光切割":{"rate":45,"unit":"h","setup_min":10,"desc":"激光切割"},
    "五轴":{"rate":150,"unit":"h","setup_min":40,"desc":"五轴加工中心"},
    "四轴":{"rate":100,"unit":"h","setup_min":30,"desc":"四轴加工中心"},
}
SIZE_TIERS = [("XS",30,0.7),("S",80,1.0),("M",200,1.5),("L",500,2.5),("XL",1000,4.0),("XXL",99999,4.5)]
TOLERANCE_COEF = {"自由公差":0.8,"IT12":0.8,"IT11":0.9,"IT10":1.0,"IT9":1.0,"IT8":1.0,"IT7":1.3,"IT6":1.5,"IT5":1.8,"IT4":2.5,"±0.01":2.0,"±0.005":4.0}

# === L4: 校准数据库 ===
CALIBRATION_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "calibration.db"

def get_cal_db():
    CALIBRATION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CALIBRATION_DB_PATH))
    conn.execute("CREATE TABLE IF NOT EXISTS calibration_factors (category TEXT PRIMARY KEY, factor REAL NOT NULL, sample_count INTEGER DEFAULT 1, last_updated TEXT, notes TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS quote_history (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, material TEXT, dimensions TEXT, quantity INTEGER, estimated_price REAL, actual_price REAL, deviation REAL, created_at TEXT)")
    return conn

def get_cal_factor(category):
    conn = get_cal_db(); cur = conn.execute("SELECT factor FROM calibration_factors WHERE category=?",(category,)); row = cur.fetchone(); conn.close()
    return row[0] if row else 1.0

def save_cal(category, actual, estimated):
    factor = actual / estimated if estimated > 0 else 1.0
    conn = get_cal_db()
    cur = conn.execute("SELECT factor, sample_count FROM calibration_factors WHERE category=?",(category,))
    row = cur.fetchone()
    if row:
        old_f, cnt = row; new_f = (old_f*cnt + factor)/(cnt+1)
        conn.execute("UPDATE calibration_factors SET factor=?, sample_count=sample_count+1, last_updated=? WHERE category=?",(new_f,cnt+1,time.strftime("%Y-%m-%d %H:%M:%S"),category))
    else:
        conn.execute("INSERT INTO calibration_factors (category,factor,sample_count,last_updated) VALUES (?,?,1,?)",(category,factor,time.strftime("%Y-%m-%d %H:%M:%S")))
    conn.execute("INSERT INTO quote_history (category,estimated_price,actual_price,deviation,created_at) VALUES (?,?,?,?,?)",(category,estimated,actual,abs(factor-1.0),time.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close()
    return factor

# === 辅助函数 ===
def resolve_material(name):
    if name in MATERIAL_DB: return {**MATERIAL_DB[name],"code":name}
    if name in ALIASES: return {**MATERIAL_DB[ALIASES[name]],"code":ALIASES[name]}
    for k,v in MATERIAL_DB.items():
        if k.lower() in name.lower() or name.lower() in k.lower(): return {**v,"code":k}
    return {"price_kg":20,"density":7.0,"machinability":0.5,"hardness_coef":1.0,"category":"未知","code":name,"name":name}

def resolve_surface(name):
    if name in SURFACE_DB: return SURFACE_DB[name]
    for k,v in SURFACE_DB.items():
        if k and k in name: return v
    return {"per_piece":0,"per_kg":0,"name":name or "无"}

def estimate_solid_ratio(l,w,h):
    dims = sorted([l,w,h]); min_d,mid_d,max_d = dims; r = max_d/min_d if min_d>0 else 1
    if min_d<8: return 0.18
    if min_d<15 and r>5: return 0.20
    if r>5: return 0.70
    return 0.44

def get_size_coef(max_dim):
    for _,mx,c in SIZE_TIERS:
        if max_dim<=mx: return c
    return 4.5

def guess_shape(l,w,h):
    dims = sorted([l,w,h]); min_d,mid_d,max_d = dims; r = max_d/min_d if min_d>0 else 1
    if r>4 and min_d<30: return "轴类",["车削","铣削"]
    if min_d<15 and r<2: return "板类",["铣削","钻孔"]
    if r<1.5 and abs(l-w)<l*0.1: return "方块类",["铣削","钻孔"]
    if max_d>200 and min_d>50: return "箱体类",["铣削","钻孔"]
    return "异形件",["铣削","五轴"]

# === L1: 体积法 ===
def volume_estimate(material,l,w,h,quantity=1,surface=""):
    mat = resolve_material(material); surf = resolve_surface(surface)
    bb_vol = l*w*h; bb_vol_cm3 = bb_vol/1000
    raw_l,raw_w,raw_h = l+10,w+10,h+10
    raw_wt = (raw_l*raw_w*raw_h)/1000*mat["density"]/1000
    net_wt = bb_vol_cm3*mat["density"]/1000*0.44
    mat_cost = raw_wt*mat["price_kg"]
    hcoef = mat.get("hardness_coef",1.0)
    cnc_h = max(0.5,round(bb_vol_cm3/500*hcoef,2))
    mach_cost = 120*cnc_h
    # 表面处理费: surf_piece=单件, surf_batch=整批 (仅总额参考)
    # 2026-09-25 修 (zipq 112件实测): 原代码把整批 surface_cost 计入单价公式
    #   (mat_cost/mach_cost 均为单件值, 唯独 surface 乘了 quantity) → unit_price ∝ qty,
    #   total ∝ qty^2; 50套/1套实测 930 倍爆炸。单价摊销必须用单件值。
    if surf["per_kg"]>0 and raw_wt>0.5: surf_piece = raw_wt*surf["per_kg"]
    else: surf_piece = surf["per_piece"]
    surf_batch = surf_piece*quantity
    disc = 0.5 if quantity>=2000 else 0.65 if quantity>=500 else 0.75 if quantity>=200 else 0.85 if quantity>=50 else 0.92 if quantity>=10 else 1.0
    sub = mat_cost+mach_cost+surf_piece+1.0; pr = 0.30
    up = round(sub/(1-pr)*disc,2); tp = round(up*quantity,2)
    return {"layer":"L1_volume","material_code":mat["code"],"material_name":mat["name"],"material_cost":round(mat_cost,2),"machining_cost":round(mach_cost,2),"surface_cost":round(surf_piece,2),"batch_surface_cost":round(surf_batch,2),"cnc_hours":cnc_h,"hardness_coef":hcoef,"net_weight_kg":round(net_wt,4),"raw_weight_kg":round(raw_wt,4),"unit_price":up,"total_price":tp,"discount":disc,"profit_rate":pr,"lead_time_days":max(2,int(cnc_h*quantity/8)+2),"engine":"fusion-v2.0-L1"}

# === L3: 工序法 ===
def process_estimate(material,l,w,h,processes,quantity=1,tolerance="IT8",surface=""):
    mat = resolve_material(material); surf = resolve_surface(surface)
    max_dim = max(l,w,h); sc = get_size_coef(max_dim)
    tc = TOLERANCE_COEF.get(tolerance,1.0); mc = 1.0/mat.get("machinability",0.5)
    raw_l,raw_w,raw_h = l+10,w+10,h+10
    raw_wt = (raw_l*raw_w*raw_h)/1000*mat["density"]/1000
    mat_cost = raw_wt*mat["price_kg"]
    details = []; total_mach = 0
    for pn in processes:
        pn = pn.strip()
        if pn not in PROCESS_DB:
            for k in PROCESS_DB:
                if k in pn or pn in k: pn = k; break
            else: continue
        p = PROCESS_DB[pn]
        bh = sc*mc*tc*0.5; sh = (p["setup_min"]/60)/max(1,quantity**0.3)
        th = bh+sh; cost = th*p["rate"]; total_mach += cost
        details.append({"process":pn,"rate":p["rate"],"base_hours":round(bh,2),"setup_hours":round(sh,2),"total_hours":round(th,2),"cost":round(cost,2)})
    # 表面处理费: 同 volume_estimate, 单件值进单价, 整批值单列
    # 2026-09-25 修: 原 'surf_cost *= quantity' 后直接进单价 → unit∝qty / total∝qty^2
    if surf["per_kg"]>0 and raw_wt>0.5: surf_piece = raw_wt*surf["per_kg"]
    else: surf_piece = surf["per_piece"]
    surf_batch = surf_piece*quantity
    disc = 0.5 if quantity>=2000 else 0.65 if quantity>=500 else 0.75 if quantity>=200 else 0.85 if quantity>=50 else 0.92 if quantity>=10 else 1.0
    sub = mat_cost+total_mach+surf_piece+1.0; pr = 0.30
    up = round(sub/(1-pr)*disc,2); tp = round(up*quantity,2)
    lt = max(2,int(sum(d["total_hours"] for d in details)*quantity/8)+2)
    return {"layer":"L3_process","material_code":mat["code"],"material_name":mat["name"],"material_cost":round(mat_cost,2),"machining_cost":round(total_mach,2),"surface_cost":round(surf_piece,2),"batch_surface_cost":round(surf_batch,2),"processes":details,"size_coef":sc,"tol_coef":tc,"mach_coef":round(mc,2),"net_weight_kg":round(raw_wt*0.55,4),"raw_weight_kg":round(raw_wt,4),"unit_price":up,"total_price":tp,"discount":disc,"profit_rate":pr,"lead_time_days":lt,"engine":"fusion-v2.0-L3"}

# === STEP解析 ===
def parse_step_bbox(step_file):
    """包围盒解析 — 优先 OCP 真几何, 正则仅作兜底.

    2026-09-25 修 (zipq 112件实测): 原实现正则扫**全部** CARTESIAN_POINT,
    把构造/辅助几何点也算进包围盒 — 1010005-底座主体 真包络 1000×1200×75.5mm
    却算出 1089mm 高, 单价虚高 10 倍 (¥79.9 万)。正则版保留为 OCP 缺失时的兜底。
    OCP 路径: 逐个 Solid 取 AddOptimal 紧密包围盒后取并集, 自动跳过虚体。
    """
    p = Path(step_file)
    if p.exists() and p.stat().st_size > 0:
        try:
            from OCP.STEPControl import STEPControl_Reader
            from OCP.IFSelect import IFSelect_RetDone
            from OCP.TopExp import TopExp_Explorer
            from OCP.TopAbs import TopAbs_SOLID
            from OCP.Bnd import Bnd_Box
            from OCP.BRepBndLib import BRepBndLib
            rdr = STEPControl_Reader()
            if rdr.ReadFile(str(p)) == IFSelect_RetDone:
                rdr.TransferRoots()
                shape = rdr.OneShape()
                if not shape.IsNull():
                    u = Bnd_Box()
                    exp = TopExp_Explorer(shape, TopAbs_SOLID)
                    n_solid = 0
                    while exp.More():
                        b = Bnd_Box()
                        BRepBndLib.AddOptimal_s(exp.Current(), b, True, False)
                        if not b.IsVoid():
                            u.Add(b); n_solid += 1
                        exp.Next()
                    if n_solid:
                        x0, y0, z0, x1, y1, z1 = u.Get()
                        l, w, h = round(x1-x0, 2), round(y1-y0, 2), round(z1-z0, 2)
                        if l > 0 and w > 0 and h > 0:
                            return (l, w, h)
        except Exception:
            pass  # OCP 不可用/文件损坏 → 落回正则兜底
    try:
        with open(step_file, 'r', errors='ignore') as f: content = f.read()
        # STEP格式: #12 = CARTESIAN_POINT('',(0.,0.,0.));
        points = re.findall(r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(([^)]+)\)\s*\)", content)
        if not points: return None
        coords = []
        for p in points:
            nums = re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', p)
            if len(nums)>=3: coords.append([float(nums[0]),float(nums[1]),float(nums[2])])
        if not coords: return None
        xs,ys,zs = zip(*[(c[0],c[1],c[2]) for c in coords])
        l = round(max(xs)-min(xs),2); w = round(max(ys)-min(ys),2); h = round(max(zs)-min(zs),2)
        return (l,w,h) if l>0 and w>0 and h>0 else None
    except Exception: return None

# === 融合主入口 ===
def fusion_quote(material,length,width,height,quantity=1,processes=None,tolerance="IT8",surface="",category=None,calibrate=None,step_file=None):
    t0 = time.time()
    if step_file:
        bb = parse_step_bbox(step_file)
        if bb: length,width,height = bb
    mat = resolve_material(material)
    shape, suggested_procs = guess_shape(length,width,height)
    if not category: category = f"{shape}_{mat['code']}"
    l1 = volume_estimate(material,length,width,height,quantity,surface)
    used_procs = processes if processes else suggested_procs
    l3 = process_estimate(material,length,width,height,used_procs,quantity,tolerance,surface)
    if processes:
        primary, reference, mode = l3, l1, "process_primary"
    else:
        primary, reference, mode = l1, l3, "volume_primary"
    cf = get_cal_factor(category)
    cp = round(primary["unit_price"]*cf,2)
    if calibrate and calibrate>0:
        raw_est = primary["unit_price"]
        cf = save_cal(category,calibrate,raw_est)
        cp = round(raw_est*cf,2)
    elapsed = round((time.time()-t0)*1000,1)
    result = {
        "fusion_mode":mode,"category":category,"shape":shape,
        "suggested_processes":used_procs,"calibration_factor":round(cf,4),
        "primary_engine":primary["engine"],"material":mat["code"],"material_name":mat["name"],
        "dimensions":f"{length}×{width}×{height}","quantity":quantity,
        "tolerance":tolerance,"surface":surface or "无",
        "unit_price":cp,"total_price":round(cp*quantity,2),
        "lead_time_days":primary["lead_time_days"],
        "material_cost":primary["material_cost"],"machining_cost":primary["machining_cost"],
        "surface_cost":primary["surface_cost"],"profit_rate":primary["profit_rate"],
        "discount":primary["discount"],
        "reference_engine":reference["engine"],"reference_unit_price":reference["unit_price"],
        "deviation_pct":round(abs(cp-reference["unit_price"])/max(cp,1)*100,1),
        "net_weight_kg":primary.get("net_weight_kg",0),"raw_weight_kg":primary.get("raw_weight_kg",0),
        "elapsed_ms":elapsed,"engine":"opc-fusion-v2.0",
    }
    if "processes" in primary: result["process_breakdown"] = primary["processes"]
    if "cnc_hours" in primary: result["cnc_hours"] = primary["cnc_hours"]
    if "hardness_coef" in primary: result["hardness_coef"] = primary["hardness_coef"]
    return result

def main():
    parser = argparse.ArgumentParser(description="OPC Fusion Quote Engine v2.0")
    parser.add_argument("--material","-m",default="AL6061")
    parser.add_argument("--length","-l",type=float,default=100)
    parser.add_argument("--width","-w",type=float,default=50)
    parser.add_argument("--height",type=float,default=20)
    parser.add_argument("--quantity","-q",type=int,default=1)
    parser.add_argument("--surface","-s",default="")
    parser.add_argument("--tolerance","-t",default="IT8")
    parser.add_argument("--processes","-p",help="工序链,逗号分隔")
    parser.add_argument("--step",help="STEP文件路径")
    parser.add_argument("--category",help="品类(用于校准)")
    parser.add_argument("--calibrate",type=float,help="用真实报价校准")
    parser.add_argument("--json","-j",action="store_true")
    parser.add_argument("--compare","-c",action="store_true")
    args = parser.parse_args()

    procs = args.processes.split(",") if args.processes else None
    r = fusion_quote(args.material,args.length,args.width,args.height,args.quantity,
                     procs,args.tolerance,args.surface,args.category,args.calibrate,args.step)

    if args.compare:
        print(f"{'='*60}")
        print(f"  🔬 融合对比 — {r['material']} {r['dimensions']} ×{r['quantity']}")
        print(f"{'='*60}")
        print(f"  模式: {r['fusion_mode']} | 品类: {r['category']}")
        print(f"  校准因子: {r['calibration_factor']} (历史数据校准)")
        print(f"  ---")
        print(f"  🎯 融合报价: ¥{r['unit_price']} (总价¥{r['total_price']})")
        print(f"  材料: ¥{r['material_cost']} | 加工: ¥{r['machining_cost']} | 表面: ¥{r['surface_cost']}")
        print(f"  参考: ¥{r['reference_unit_price']} ({r['reference_engine']})")
        print(f"  偏差: {r['deviation_pct']}% | 交期: {r['lead_time_days']}天")
        if "process_breakdown" in r:
            print(f"  --- 工序分解 ---")
            for p in r["process_breakdown"]:
                print(f"  {p['process']}: {p['total_hours']}h × ¥{p['rate']}/h = ¥{p['cost']}")
        print(f"{'='*60}")
        return

    if args.json:
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return

    print(f"⚡ OPC Fusion v2.0 | {r['material_name']} {r['dimensions']} ×{r['quantity']}")
    print(f"  模式: {r['fusion_mode']} | 形状: {r['shape']} | 校准: {r['calibration_factor']}")
    print(f"  🎯 单价: ¥{r['unit_price']} | 总价: ¥{r['total_price']}")
    print(f"  材料¥{r['material_cost']} + 加工¥{r['machining_cost']} + 表面¥{r['surface_cost']}")
    print(f"  交期{r['lead_time_days']}天 | 引擎{r['engine']} ({r['elapsed_ms']}ms)")

if __name__ == "__main__":
    main()
