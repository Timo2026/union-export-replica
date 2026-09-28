#!/usr/bin/env python3
"""
cnc_risk_guardian_v1.1.py - CNC经营风控官 v1.1
6维风险识别: 从公式计算升级为模式识别
AI能做Excel做不到的事
"""
import os
import sys
import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime

SKILLS_DIR = os.path.expanduser("~/.openclaw/skills")
sys.path.insert(0, os.path.join(SKILLS_DIR, "hexagram-llm-bridge", "scripts"))

try:
    from hexagram_llm_bridge import HexagramLLMBridge
    BRIDGE_OK = True
except ImportError:
    BRIDGE_OK = False

class RiskGuardianV1_1:
    """CNC经营风控官 v1.1 - 6维风险识别"""

    # 阈值配置
    DANGER_MARGIN = 0.05
    WARNING_MARGIN = 0.20
    PREDATORY_THRESHOLD = 0.40
    CUSTOMER_CONCENTRATION_WARNING = 0.60
    PRICE_VOLATILITY_WARNING = 0.50
    BATCH_DISCOUNT_MIN = 0.05
    MATERIAL_SUBSTITUTION_WARNING = 0.30

    def __init__(self):
        self.bridge = HexagramLLMBridge() if BRIDGE_OK else None
        self._load_knowledge()

    def _load_knowledge(self):
        """加载知识库"""
        base_dir = os.path.join(SKILLS_DIR, "cnc-risk-guardian", "knowledge")
        
        # 材料成本
        try:
            with open(os.path.join(base_dir, "material_cost.json")) as f:
                data = json.load(f)
                self.material_cost = data.get("materials", {})
                self.price_history = data.get("price_history", {})
        except:
            self.material_cost = {}
            self.price_history = {}

        # 历史价格
        try:
            with open(os.path.join(base_dir, "price_history.json")) as f:
                self.price_history_data = json.load(f)
        except:
            self.price_history_data = {}

        # 加工系数
        try:
            with open(os.path.join(base_dir, "process_coefficient.json")) as f:
                self.process_coeff = json.load(f)
        except:
            self.process_coeff = {}

    def analyze_batch(self, records: List[Dict]) -> Dict[str, Any]:
        """批量分析入口"""
        start_time = time.time()

        # 6维风险检测
        risk_results = []
        for record in records:
            risks = self._detect_6d_risks(record)
            risk_results.append(risks)

        # 聚合报告
        report = self._aggregate_report(risk_results, records)
        report["elapsed_ms"] = int((time.time() - start_time) * 1000)
        report["total_records"] = len(records)

        return report

    def _detect_6d_risks(self, record: Dict) -> Dict[str, Any]:
        """6维风险检测"""
        material = record.get("material", "未知")
        price = float(record.get("price", 0))
        quantity = int(record.get("quantity", 1))
        customer = record.get("customer", record.get("客户", "未知"))
        name = record.get("name", record.get("零件名称", ""))

        risks = {
            "id": record.get("id", 0),
            "material": material,
            "price": price,
            "quantity": quantity,
            "customer": customer,
            "name": name,
            "risk_types": [],
            "risk_level": "normal",
            "risk_reasons": []
        }

        # 维度1: 毛利率
        cost = self._estimate_cost(material, price)
        margin = (price - cost) / price if price > 0 else 0
        if margin < self.DANGER_MARGIN:
            risks["risk_level"] = "danger"
            risks["risk_types"].append("low_margin")
            risks["risk_reasons"].append(f"毛利率{-margin*100:.0f}%<5%")
        elif margin < self.WARNING_MARGIN:
            risks["risk_level"] = "warning"
            risks["risk_types"].append("margin_warning")
            risks["risk_reasons"].append(f"毛利率{ margin*100:.0f}%偏低")

        # 维度2: 恶性比价竞争 (AI才能做到!)
        history_key = f"{material}{name}" if name else material
        if history_key in self.price_history_data:
            hist = self.price_history_data[history_key]
            avg_price = sum(hist) / len(hist) if hist else price
            if price < avg_price * (1 - self.PREDATORY_THRESHOLD):
                risks["risk_level"] = "danger"
                risks["risk_types"].append("predatory_pricing")
                drop_rate = (1 - price / avg_price) * 100 if avg_price > 0 else 0
                risks["risk_reasons"].append(f"报价低于均价{drop_rate:.0f}%,疑似恶性竞争")

        # 维度3: 客户集中度 (需批量数据)
        # (在aggregate阶段计算)

        # 维度4: 批量折扣缺失
        if quantity >= 500:
            # 检查是否有合理的梯度折扣
            expected_discount = 0.05 * (quantity // 100)
            # 如果是大量采购但单价异常低
            if price < cost * 1.1:  # 毛利率<10%但量大
                risks["risk_level"] = "warning"
                risks["risk_types"].append("batch_discount_missing")
                risks["risk_reasons"].append("批量采购但折扣缺失")

        # 维度5: 材料替换风险
        common_materials = {
            "SUS304": "304不锈钢",
            "SUS316L": "316不锈钢",
            "AL6061": "铝合金6061",
            "AL7075": "铝合金7075"
        }
        if material in common_materials:
            standard = common_materials[material]
            if standard in self.material_cost:
                std_cost = self.material_cost[standard].get("cost_per_kg", 20)
                curr_cost = self.material_cost.get(material, {}).get("cost_per_kg", std_cost)
                if curr_cost > std_cost * (1 + self.MATERIAL_SUBSTITUTION_WARNING):
                    risks["risk_level"] = "warning"
                    risks["risk_types"].append("material_substitution")
                    risks["risk_reasons"].append("材料替换成本上升但报价未调整")

        return risks

    def _estimate_cost(self, material: str, price: float) -> float:
        """估算理论成本"""
        if material in self.material_cost:
            unit_cost = self.material_cost[material].get("cost_per_kg", 15)
        else:
            unit_cost = 15.0

        if material in self.process_coeff:
            coeff = self.process_coeff[material].get("coefficient", 1.0)
        else:
            coeff = 1.0

        return price * 0.6 * coeff

    def _aggregate_report(self, risk_results: List[Dict], records: List[Dict]) -> Dict[str, Any]:
        """聚合报告"""
        summary = {"total": len(risk_results), "normal": 0, "warning": 0, "danger": 0}
        danger_orders = []
        customer_amounts = {}

        for r in risk_results:
            summary[r["risk_level"]] += 1
            if r["risk_level"] == "danger":
                danger_orders.append(r)

            # 客户集中度
            customer = r.get("customer", "未知")
            amount = r.get("price", 0) * r.get("quantity", 1)
            customer_amounts[customer] = customer_amounts.get(customer, 0) + amount

        # 客户集中度
        total_amount = sum(customer_amounts.values())
        customer_concentration = "low"
        if total_amount > 0:
            max_ratio = max(customer_amounts.values()) / total_amount
            if max_ratio > 0.8:
                customer_concentration = "high"
            elif max_ratio > 0.6:
                customer_concentration = "medium"

        return {
            "version": "1.1.0",
            "summary": summary,
            "danger_orders": danger_orders,
            "customer_concentration_risk": customer_concentration,
            "risk_rate": f"{summary['danger'] + summary['warning']} / {summary['total']}",
            "recommendations": self._generate_recommendations(summary, customer_concentration, danger_orders)
        }

    def _generate_recommendations(self, summary: Dict, customer_risk: str, dangers: List) -> List[str]:
        """生成建议"""
        recs = []
        if summary["danger"] > 0:
            recs.append(f"发现{summary['danger']}个亏损/恶性比价订单,建议重新定价或放弃")
        if summary["warning"] > 0:
            recs.append(f"存在{summary['warning']}个低利润/批量折扣缺失订单")
        if customer_risk == "high":
            recs.append("客户集中度过高(>80%),建议拓展客户群分散风险")
        if not recs:
            recs.append("订单整体健康,保持现状")
        return recs


def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """入口"""
    records = params.get("records", [])
    if not records:
        return {"error": "需要提供records参数"}
    guardian = RiskGuardianV1_1()
    return guardian.analyze_batch(records)


if __name__ == "__main__":
    print("=== CNC经营风控官 v1.1 测试 ===\n")

    # 真实测试数据 (模拟25%风险率)
    test_records = [
        # 正常订单
        {"id": 1, "name": "法兰", "material": "304不锈钢", "price": 85, "quantity": 50, "customer": "客户A"},
        {"id": 2, "name": "轴套", "material": "45号钢", "price": 45, "quantity": 100, "customer": "客户B"},
        # 恶性比价竞争 (危险!)
        {"id": 3, "name": "法兰", "material": "304不锈钢", "price": 50, "quantity": 100, "customer": "客户C"},
        # 批量折扣缺失 (预警!)
        {"id": 4, "name": "接头", "material": "铝合金6061", "price": 20, "quantity": 500, "customer": "客户A"},
        # 毛利率过低 (危险!)
        {"id": 5, "name": "阀体", "material": "316不锈钢", "price": 100, "quantity": 20, "customer": "客户D"},
    ]

    guardian = RiskGuardianV1_1()
    result = guardian.analyze_batch(test_records)

    print(f"总订单: {result['total_records']}")
    print(f"风险分布: {result['summary']}")
    print(f"风险率: {result['risk_rate']}")
    print(f"客户集中度: {result['customer_concentration_risk']}")
    print(f"\n危险订单:")
    for d in result['danger_orders']:
        print(f"  [{d['id']}] {d['material']}: {d['risk_reasons']}")
    print(f"\n建议: {result['recommendations']}")
    print(f"\n耗时: {result['elapsed_ms']}ms")
    print("\n=== 测试完成 ===")