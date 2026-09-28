#!/usr/bin/env python3
"""
cnc_quote_pipeline_v2.py - CNC报价全链路 (v2集成版)
管线: 请求 → ModelRouter(三级降级) → HardGuard → DecisionLedger → ArtifactHash → 输出
"""
import os, sys, json, time, re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(SCRIPT_DIR)

from rule_guardian import RuleGuardian
from decision_ledger import DecisionLedger
from model_router import ModelRouter
from artifact_hash import ArtifactHasher

class CNCQuotePipelineV2:
    def __init__(self):
        self.guardian = RuleGuardian()
        self.ledger = DecisionLedger()
        self.router = ModelRouter()
        self.hasher = ArtifactHasher()
    
    def _parse_nl(self, user_input: str) -> dict:
        """ModelRouter: 三级降级NLP解析"""
        prompt = f"""从CNC报价需求中提取参数，只返回JSON。

用户: {user_input}

{{
    "material": "只写材料名称，如铝合金6061、304不锈钢、45号钢、工具钢（不要包含表面处理、公差、尺寸等）",
    "surface_treatment": "表面处理，如阳极氧化、镀锌、发黑、钝化、电解抛光（没有则留空）",
    "heat_treatment": "热处理，如淬火、调质、退火（没有则留空）",
    "quantity": 数量（整数）,
    "dimensions_mm": "外形尺寸，如100x50x20mm（没有则留空）",
    "tolerance_grade": "公差等级，如IT7、IT8（没有则留空）",
    "min_wall_thickness": 最小壁厚mm（没有则用1.0）
}}"""
        result = self.router.route(prompt)
        
        # 清理响应
        resp_text = result.get("response", "").strip()
        if resp_text.startswith("```"):
            resp_text = resp_text.split("\n", 1)[1] if "\n" in resp_text else resp_text[3:]
            resp_text = resp_text.rsplit("```", 1)[0].strip()
        
        try:
            parsed = json.loads(resp_text)
            # 清理材料字段: 去掉混入的表面处理/公差等
            mat = parsed.get("material", "")
            # 只保留纯材料名
            mat_clean = mat.split(" ")[0].split("，")[0]
            for suffix in ["阳极氧化", "镀锌", "发黑", "钝化", "IT", "硬质氧化", "电解抛光"]:
                if suffix in mat_clean:
                    mat_clean = mat_clean.split(suffix)[0].strip()
            parsed["material"] = mat_clean
        except:
            parsed = self._fallback_parse(user_input)
        
        parsed["_raw"] = user_input
        parsed["_tier"] = result.get("tier", 3)
        parsed["_model"] = result.get("model", "rule_engine")
        parsed["_nlp_time"] = result.get("elapsed", 0)
        return parsed
    
    def _fallback_parse(self, text: str) -> dict:
        """Tier3 fallback: 纯规则解析"""
        材料映射 = {"6061": "铝合金6061", "7075": "铝合金7075", "铝合金": "铝合金6061",
                   "304": "304不锈钢", "316": "316不锈钢", "不锈钢": "304不锈钢",
                   "45": "45号钢", "碳钢": "45号钢", "钢": "45号钢", "工具钢": "工具钢",
                   "铝合金6061": "铝合金6061"}
        material = "未知外协"
        for k, v in 材料映射.items():
            if k in text:
                material = v
                break
        
        nums = re.findall(r'(\d+)\s*件', text)
        quantity = int(nums[0]) if nums else 1
        
        表面词 = {"阳极氧化": "阳极氧化", "硬质氧化": "硬质氧化", "镀锌": "镀锌",
                   "发黑": "发黑", "电解抛光": "电解抛光", "钝化": "钝化",
                   "镀铬": "镀铬", "镀镍": "镀镍"}
        surface = ""
        for k, v in 表面词.items():
            if k in text:
                surface = v
                break
        
        dims = re.findall(r'([\d.]+)x([\d.]+)x([\d.]+)', text)
        dims_mm = f"{dims[0][0]}x{dims[0][1]}x{dims[0][2]}mm" if dims else ""
        
        热处理词 = {"淬火": "淬火", "调质": "调质", "退火": "退火", "回火": "回火"}
        heat = ""
        for k, v in 热处理词.items():
            if k in text:
                heat = v
                break
        
        return {
            "material": material, "surface_treatment": surface,
            "heat_treatment": heat, "quantity": quantity,
            "dimensions_mm": dims_mm, "tolerance_grade": "IT8",
            "min_wall_thickness": 1.0, "confidence": 0.8,
            "_raw": text, "_tier": 3, "_model": "rule_engine", "_nlp_time": 0.01,
        }
    
    def _estimate_price(self, request: dict) -> dict:
        """基于规则估算报价 (同v1)"""
        mat = request.get("material", "未知")
        qty = request.get("quantity", 1)
        
        base_prices = {
            "铝合金6061": 35, "铝合金7075": 65, "铝合金": 35,
            "304不锈钢": 55, "316不锈钢": 75, "不锈钢": 55,
            "45号钢": 30, "碳钢": 28, "钢": 30, "工具钢": 45,
            "黄铜": 50, "紫铜": 60, "铜": 50, "钛合金": 120, "PEEK": 200,
        }
        base = 35
        for k, v in base_prices.items():
            if k in mat or mat in k:
                base = v
                break
        
        if qty >= 1000: qty_factor = 0.5
        elif qty >= 500: qty_factor = 0.6
        elif qty >= 100: qty_factor = 0.7
        elif qty >= 50: qty_factor = 0.85
        else: qty_factor = 1.0
        
        surface_costs = {"阳极氧化": 8, "硬质氧化": 15, "镀锌": 6, "镀铬": 12,
                         "发黑": 3, "电解抛光": 5, "钝化": 4, "镀镍": 10}
        surface = request.get("surface_treatment", "")
        surface_cost = next((v for k, v in surface_costs.items() if k in surface), 0)
        
        unit_price = base * qty_factor + surface_cost
        total = round(unit_price * qty, 2)
        
        return {
            "base_price": base, "qty_factor": qty_factor,
            "surface_cost": surface_cost, "unit_price": round(unit_price, 2),
            "total_price": total, "qty": qty,
            "price_breakdown": {
                "material": round(base * qty_factor * qty, 2),
                "surface": round(surface_cost * qty, 2),
                "total": total,
            }
        }
    
    def run(self, user_input: str, chain: str = "chain_v2_quote") -> dict:
        """全链路执行 (v2)"""
        t0 = time.time()
        
        # Step 1: ModelRouter (三级降级)
        request = self._parse_nl(user_input)
        print(f"[Router] Tier{request.get('_tier',3)} ({request.get('_model','?')}) | {request.get('material','?')} x{request.get('quantity','?')}")
        print(f"         耗时: {request.get('_nlp_time',0):.2f}s")
        
        # Step 2: HardGuard
        quote_data = {
            "material": request.get("material", ""),
            "surface_treatment": request.get("surface_treatment", ""),
            "heat_treatment": request.get("heat_treatment", ""),
            "min_wall_thickness": request.get("min_wall_thickness", 1.0),
            "tolerance_grade": request.get("tolerance_grade", "IT7"),
        }
        # 类型安全转换
        try:
            quote_data["min_wall_thickness"] = float(quote_data.get("min_wall_thickness", 1.0) or 1.0)
        except:
            quote_data["min_wall_thickness"] = 1.0
        rule_check = self.guardian.guard(quote_data)
        status = rule_check["status"]
        status_icon = {"passed": "🟢", "blocked": "🔴", "warned": "🟡"}
        print(f"[Guard] {status_icon.get(status,'?')} {status}")
        
        # Step 3: 报价估算
        estimate = self._estimate_price(request)
        
        # Step 4: ArtifactHash
        model_output = {"request": request, "rule_check": rule_check, "estimate": estimate}
        chain_hash = self.hasher.hash_chain([user_input, model_output])
        data_hash = self.hasher.hash_data(model_output)
        self.hasher.log(chain_hash, {"chain": chain, "request": user_input[:50]})
        
        # Step 5: DecisionLedger
        decision_id = self.ledger.log(
            chain=chain,
            request=request,
            model_output=model_output,
            rule_check=rule_check,
            final_quote=estimate,
            status=status,
            notes=f"Tier{request.get('_tier',3)}/{request.get('_model','?')}, SHA256:{data_hash[:8]}.."
        )
        
        total_time = time.time() - t0
        
        print(f"[Hash] 决策链: {chain_hash[:12]}... | 数据: {data_hash[:12]}...")
        print(f"[Total] 总耗时: {total_time:.1f}s | 审计ID: #{decision_id}")
        
        return {
            "status": status,
            "request": request,
            "rule_check": rule_check,
            "estimate": estimate,
            "artifacts": {
                "chain_hash": chain_hash,
                "data_hash": data_hash,
            },
            "decision_id": decision_id,
            "total_time": total_time,
        }


# === 批量测试 ===
if __name__ == "__main__":
    pipeline = CNCQuotePipelineV2()
    print("=" * 70)
    print("CNC Quote Pipeline v2 - 三级降级 + SHA-256溯源")
    print("=" * 70)
    
    # 真实测试用例
    test_cases = [
        ("底座", "底座 30.3x21.7x27.6mm 铝合金6061 阳极氧化 IT8 100件"),
        ("法兰座", "法兰座 45.6x19.0x33.1mm 304不锈钢 电解抛光 IT7 50件"),
        ("不锈钢管", "不锈钢管配件 30x15x20mm 316不锈钢 钝化 200件"),
        ("多孔板", "多孔板 500x10x465mm 铝合金6061 硬质氧化 IT9 20件"),
        ("31.5度刀", "31.5度刀 73.4x91.2x32.8mm 工具钢 发黑 IT6 10件"),
        ("上切刀模", "上切刀模 373.6x359.7x722.5mm 45号钢 调质 IT7 5件"),
        ("底座滑轨", "底座滑轨端 80.0x125.5x242.0mm 45号钢 镀锌 IT8 50件"),
    ]
    
    for name, tc in test_cases:
        print(f"\n--- {name} ---")
        result = pipeline.run(tc, f"chain_real_{name}")
        
        status_icon = {"passed": "🟢通过", "blocked": "🔴拦截", "warned": "🟡警告"}
        print(f"  {status_icon.get(result['status'],'?')} ¥{result['estimate']['total_price']:.2f}")
        print(f"  材料: {result['request'].get('material','?')} | 表面: {result['request'].get('surface_treatment','?')}")
        if result['rule_check']['risk_notes']:
            print(f"  ⚠️ {result['rule_check']['risk_notes'][0]}")
    
    # 测试ModelRouter三级降级
    print(f"\n{'='*70}")
    print(f"ModelRouter统计: {pipeline.router.get_stats()}")
    print(f"ArtifactHash账本: {pipeline.hasher.get_stats()}")
    
    stats = pipeline.ledger.stats()
    print(f"决策账本: {stats['total']}条, 状态: {stats['by_status']}")
