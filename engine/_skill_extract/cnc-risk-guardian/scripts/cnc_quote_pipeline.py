#!/usr/bin/env python3
"""
cnc_quote_pipeline.py - CNC报价全链路集成
管线: 用户请求 -> Ollama NLP -> HardGuard约束检查 -> DecisionLedger审计 -> 报价输出
"""
import os, sys, json, time, hashlib, urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from rule_guardian import RuleGuardian
from decision_ledger import DecisionLedger

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:1.5b"

class CNCQuotePipeline:
    def __init__(self):
        self.guardian = RuleGuardian()
        self.ledger = DecisionLedger()
    
    def _ollama(self, prompt: str) -> dict:
        """调用Ollama本地模型"""
        data = {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 300, "temperature": 0.1}
        }
        t0 = time.time()
        req = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        elapsed = time.time() - t0
        return {"response": result.get("response", ""), "elapsed": elapsed}
    
    def _parse_nl(self, user_input: str) -> dict:
        """自然语言解析: 用户输入 -> 结构化报价请求"""
        prompt = f"""你是一个CNC报价解析器。从用户的自然语言描述中提取报价参数。
只返回JSON，不要多余内容。

用户: {user_input}

输出JSON格式:
{{
    "material": "材料名称，如铝合金6061、304不锈钢、45号钢",
    "surface_treatment": "表面处理，如阳极氧化、镀锌、发黑",
    "heat_treatment": "热处理，如淬火、退火、调质，无则留空",
    "quantity": 数量（整数）,
    "dimensions_mm": "外形尺寸，如100x50x20",
    "tolerance_grade": "公差等级，如IT7",
    "min_wall_thickness": 最小壁厚（mm，未知则用1.0）,
    "confidence": 置信度0-1
}}"""
        result = self._ollama(prompt)
        try:
            # 清理markdown代码块
            resp_text = result["response"].strip()
            if resp_text.startswith("```"):
                resp_text = resp_text.split("\n", 1)[1] if "\n" in resp_text else resp_text[3:]
                resp_text = resp_text.rsplit("```", 1)[0].strip()
            parsed = json.loads(resp_text)
            parsed["_raw"] = user_input
            parsed["_nlp_time"] = result["elapsed"]
            return parsed
        except:
            # 解析失败, 返回最低信息
            return {"material": "未知", "surface_treatment": "", "heat_treatment": "",
                    "quantity": 1, "dimensions_mm": "", "tolerance_grade": "IT8",
                    "min_wall_thickness": 1.0, "confidence": 0.3,
                    "_raw": user_input, "_nlp_time": result["elapsed"]}
    
    def _estimate_price(self, request: dict) -> dict:
        """基于规则估算报价 (替代模型报价, Tier3离线引擎)"""
        mat = request.get("material", "未知")
        qty = request.get("quantity", 1)
        
        # 材料基础单价 (¥/件, 100件基准)
        base_prices = {
            "铝合金6061": 35, "铝合金7075": 65, "铝合金": 35,
            "304不锈钢": 55, "316不锈钢": 75, "不锈钢": 55,
            "45号钢": 30, "碳钢": 28, "钢": 30,
            "黄铜": 50, "紫铜": 60, "铜": 50,
            "钛合金": 120, "PEEK": 200,
        }
        base = 35  # 默认
        for k, v in base_prices.items():
            if k in mat or mat in k:
                base = v
                break
        
        # 数量折扣
        if qty >= 1000: qty_factor = 0.5
        elif qty >= 500: qty_factor = 0.6
        elif qty >= 100: qty_factor = 0.7
        elif qty >= 50: qty_factor = 0.85
        else: qty_factor = 1.0
        
        # 表面处理附加
        surface = request.get("surface_treatment", "")
        surface_costs = {"阳极氧化": 8, "硬质氧化": 15, "镀锌": 6, "镀铬": 12, 
                         "发黑": 3, "电解抛光": 5, "钝化": 4}
        surface_cost = 0
        for k, v in surface_costs.items():
            if k in surface:
                surface_cost = v
                break
        
        unit_price = base * qty_factor + surface_cost
        total = round(unit_price * qty, 2)
        
        return {
            "base_price": base,
            "qty_factor": qty_factor,
            "surface_cost": surface_cost,
            "unit_price": round(unit_price, 2),
            "total_price": total,
            "qty": qty,
            "price_breakdown": {
                "material": round(base * qty_factor * qty, 2),
                "surface": round(surface_cost * qty, 2),
                "total": total,
            }
        }
    
    def run(self, user_input: str, chain: str = "chain_1_customer_quote") -> dict:
        """全链路执行"""
        t0 = time.time()
        
        # Step 1: NLP解析
        request = self._parse_nl(user_input)
        print(f"[NLP] 解析: {request.get('material','?')} x{request.get('quantity','?')}")
        print(f"      耗时: {request.get('_nlp_time',0):.1f}s")
        
        # Step 2: 硬规则检查
        quote_data = {
            "material": request.get("material", ""),
            "surface_treatment": request.get("surface_treatment", ""),
            "heat_treatment": request.get("heat_treatment", ""),
            "min_wall_thickness": request.get("min_wall_thickness", 1.0),
            "tolerance_grade": request.get("tolerance_grade", "IT7"),
        }
        rule_check = self.guardian.guard(quote_data)
        
        if rule_check["status"] == "blocked":
            print(f"[HardGuard] 🔴 FATAL拦截! 原因: {rule_check.get('risk_notes', ['?'])[0]}")
            # 仍然计算报价但标记拦截
            estimate = self._estimate_price(request)
            status = "blocked"
        elif rule_check["status"] == "warned":
            print(f"[HardGuard] 🟡 标记警告: {len(rule_check.get('risk_notes', []))}条")
            estimate = self._estimate_price(request)
            status = "warned"
        else:
            print(f"[HardGuard] 🟢 硬规则全部通过")
            estimate = self._estimate_price(request)
            status = "passed"
        
        # Step 3: 审计记录
        model_output = {
            "request": request,
            "rule_check": rule_check,
            "estimate": estimate,
        }
        decision_id = self.ledger.log(
            chain=chain,
            request=request,
            model_output=model_output,
            rule_check=rule_check,
            final_quote=estimate,
            status=status,
            notes=f"Pipeline: {chain}, NLP: {request.get('_nlp_time',0):.1f}s"
        )
        
        total_time = time.time() - t0
        print(f"[Ledger] 📝 决策ID: #{decision_id}")
        print(f"[Total] 总耗时: {total_time:.1f}s")
        
        return {
            "status": status,
            "request": request,
            "rule_check": rule_check,
            "estimate": estimate,
            "decision_id": decision_id,
            "total_time": total_time,
        }


# === CLI演示 ===
if __name__ == "__main__":
    pipeline = CNCQuotePipeline()
    
    test_cases = [
        "100x50x20mm 铝合金6061, 阳极氧化黑色, IT8公差, 100件, 报价多少?",
        "304不锈钢法兰, 外径120内径60厚20mm, 镀锌, 50件",
        "45号钢轴套, 外径50内径30长80mm, 发黑处理, IT7, 200件",
        "铝合金7075 T6, 淬火处理, 阳极氧化, 20件, 壁厚0.3mm",
    ]
    
    print("=" * 60)
    print("CNC Quote Pipeline - 全链路测试")
    print(f"模型: {MODEL} | 守卫: 6类规则 | 审计: SQLite")
    print("=" * 60)
    
    for i, tc in enumerate(test_cases):
        print(f"\n{'='*60}")
        print(f"测试 #{i+1}: {tc}")
        print(f"{'='*60}")
        result = pipeline.run(tc)
        
        status_icon = {"passed": "✅ 通过", "blocked": "🔴 拦截", "warned": "🟡 警告"}
        print(f"\n结果: {status_icon.get(result['status'], '?')}")
        print(f"材料: {result['request'].get('material','?')}")
        print(f"表面: {result['request'].get('surface_treatment','?')}")
        print(f"数量: {result['request'].get('quantity','?')}")
        print(f"估价: ¥{result['estimate'].get('total_price',0):.2f} ({result['estimate'].get('unit_price',0):.2f}/件)")
        if result['rule_check']['risk_notes']:
            print(f"风险: {result['rule_check']['risk_notes'][0]}")
        print(f"审计ID: #{result['decision_id']}")
    
    # 统计
    stats = pipeline.ledger.stats()
    print(f"\n{'='*60}")
    print(f"审计统计: {stats['total']}条记录, {stats['unique_parts']}个唯一零件")
    print(f"按状态: {stats['by_status']}")
    print(f"按链: {stats['by_chain']}")
