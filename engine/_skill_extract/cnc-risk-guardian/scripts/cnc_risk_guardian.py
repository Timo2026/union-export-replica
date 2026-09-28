#!/usr/bin/env python3
"""
cnc_risk_guardian.py - CNC经营风控官
基于本地Ollama模型进行批量报价风险分析
完全离线，数据不出本机
"""
import os
import sys
import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime

# 复用现有hexagram-llm-bridge
SKILLS_DIR = os.path.expanduser("~/.openclaw/skills")
sys.path.insert(0, os.path.join(SKILLS_DIR, "hexagram-llm-bridge", "scripts"))

try:
    from hexagram_llm_bridge import HexagramLLMBridge
    BRIDGE_OK = True
except ImportError:
    BRIDGE_OK = False


class RiskGuardian:
    """CNC经营风控官"""

    # 风险阈值
    DANGER_MARGIN = 0.05   # <5% 亏损
    WARNING_MARGIN = 0.20   # 5%-20% 低利润
    CUSTOMER_CONCENTRATION_WARNING = 0.60  # 单一客户>60%
    PRICE_DISPERSION_CV_WARNING = 2.0  # CV>200%

    # 材料成本库 (复用material-cost-per-kg)
    MATERIAL_COST = {
        "304不锈钢": 22.0,
        "316不锈钢": 28.0,
        "45号钢": 8.0,
        "铝合金6061": 18.0,
        "铝合金7075": 35.0,
        "黄铜": 40.0,
        "紫铜": 65.0,
        "45钢": 8.0,
    }

    # 加工系数 (材料难度系数)
    PROCESS_COEFFICIENT = {
        "304不锈钢": 1.2,
        "316不锈钢": 1.3,
        "45号钢": 1.0,
        "铝合金6061": 0.8,
        "铝合金7075": 0.9,
        "黄铜": 0.7,
        "紫铜": 0.85,
        "45钢": 1.0,
    }

    def __init__(self):
        self.bridge = HexagramLLMBridge() if BRIDGE_OK else None

    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        """
        分析报价文件
        输入: Excel/CSV文件路径
        输出: 风险分析报告
        """
        start_time = time.time()

        # Stage 1: 读取文件
        records = self._read_file(file_path)
        if not records:
            return {"error": "无法读取文件或文件为空"}

        # Stage 2: 规则预筛
        validated_records = self._precheck(records)

        # Stage 3: 模型推理
        risk_results = self._infer_risk(validated_records)

        # Stage 4: 聚合报告
        report = self._aggregate_report(risk_results, validated_records)

        report["elapsed_ms"] = int((time.time() - start_time) * 1000)
        report["total_records"] = len(records)
        report["analyzed_records"] = len(validated_records)

        return report

    def _read_file(self, file_path: str) -> List[Dict]:
        """读取Excel/CSV文件"""
        try:
            import pandas as pd
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
            return df.to_dict('records')
        except Exception as e:
            return []

    def _precheck(self, records: List[Dict]) -> List[Dict]:
        """规则预筛：数据校验+字段标准化"""
        validated = []
        for record in records:
            # 确保必要字段存在
            if not record.get('material') and not record.get('材料'):
                continue
            validated.append(record)
        return validated

    def _infer_risk(self, records: List[Dict]) -> List[Dict[str, Any]]:
        """本地模型推理风险"""
        results = []

        for record in records:
            material = record.get('material') or record.get('材料', '未知')
            price = float(record.get('price') or record.get('单价', 0))
            quantity = int(record.get('quantity') or record.get('数量', 1))
            cost_estimate = self._estimate_cost(material, price, quantity)

            margin = (price - cost_estimate) / price if price > 0 else 0

            # 规则判断 (快速路径)
            if margin < self.DANGER_MARGIN:
                risk_level = "danger"
                risk_reason = "毛利率过低"
            elif margin < self.WARNING_MARGIN:
                risk_level = "warning"
                risk_reason = "利润率偏低"
            else:
                risk_level = "normal"
                risk_reason = "正常"

            # 如果置信度不够，调用LLM增强
            if risk_level in ["danger", "warning"] and self.bridge:
                llm_result = self._llm_enhance(record, cost_estimate, margin)
                if llm_result:
                    risk_level = llm_result.get('risk_level', risk_level)
                    risk_reason = llm_result.get('risk_reason', risk_reason)

            results.append({
                "id": record.get('id', len(results)),
                "material": material,
                "price": price,
                "quantity": quantity,
                "cost_estimate": cost_estimate,
                "margin": margin,
                "risk_level": risk_level,
                "risk_reason": risk_reason
            })

        return results

    def _estimate_cost(self, material: str, price: float, quantity: int) -> float:
        """估算理论成本"""
        # 从材料成本库查找
        unit_cost = self.MATERIAL_COST.get(material, 15.0)  # 默认15元/kg
        process_coeff = self.PROCESS_COEFFICIENT.get(material, 1.0)

        # 简化成本估算：材料费 + 加工费
        # 假设平均每个零件材料成本占比60%
        material_cost = price * 0.6
        process_cost = material_cost * process_coeff

        return material_cost + process_cost

    def _llm_enhance(self, record: Dict, cost_estimate: float, margin: float) -> Optional[Dict]:
        """调用本地LLM增强分析"""
        try:
            prompt = f"""分析以下报价风险：

零件: {record.get('name', '未知')}
材料: {record.get('material', '未知')}
单价: {record.get('price', 0)}
数量: {record.get('quantity', 1)}

估算成本: {cost_estimate:.2f}
毛利率: {margin*100:.1f}%

输出JSON:
{{"risk_level": "danger/warning/normal", "risk_reason": "不超过15字原因"}}
"""
            result = self.bridge.invoke(prompt, {"skill": "risk-guardian"})
            if result.get('success'):
                import json
                response = result.get('response', '{}')
                return json.loads(response)
        except:
            pass
        return None

    def _aggregate_report(self, risk_results: List[Dict], records: List[Dict]) -> Dict[str, Any]:
        """聚合生成报告"""
        summary = {
            "total": len(risk_results),
            "normal": 0,
            "warning": 0,
            "danger": 0
        }

        danger_orders = []
        customer_amounts = {}

        for r in risk_results:
            summary[r['risk_level']] += 1

            if r['risk_level'] == 'danger':
                danger_orders.append(r)

            # 客户集中度统计
            customer = records[r['id']].get('customer', records[r['id']].get('客户', '未知'))
            customer_amounts[customer] = customer_amounts.get(customer, 0) + r['price'] * r['quantity']

        # 客户集中度计算
        total_amount = sum(customer_amounts.values())
        customer_concentration_risk = "low"
        if total_amount > 0:
            max_ratio = max(customer_amounts.values()) / total_amount
            if max_ratio > 0.6:
                customer_concentration_risk = "high"
            elif max_ratio > 0.4:
                customer_concentration_risk = "medium"

        return {
            "summary": summary,
            "danger_orders": danger_orders,
            "customer_concentration_risk": customer_concentration_risk,
            "recommendations": self._generate_recommendations(summary, customer_concentration_risk)
        }

    def _generate_recommendations(self, summary: Dict, customer_risk: str) -> List[str]:
        """生成建议"""
        recommendations = []

        if summary['danger'] > 0:
            recommendations.append(f"发现{summary['danger']}个亏损订单，建议重新定价")

        if summary['warning'] > 0:
            recommendations.append(f"存在{summary['warning']}个低利润订单，关注成本控制")

        if customer_risk == "high":
            recommendations.append("客户集中度过高，建议拓展客户群")

        if not recommendations:
            recommendations.append("订单整体健康，保持现状")

        return recommendations


def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """Skill入口"""
    file_path = params.get('file_path') or params.get('input')

    if not file_path:
        return {"error": "需要提供file_path参数"}

    guardian = RiskGuardian()
    return guardian.analyze_file(file_path)


if __name__ == "__main__":
    print("=== CNC经营风控官测试 ===\n")

    guardian = RiskGuardian()

    # 创建测试数据
    test_records = [
        {"name": "法兰", "material": "304不锈钢", "price": 50, "quantity": 100, "customer": "客户A"},
        {"name": "轴套", "material": "45号钢", "price": 30, "quantity": 200, "customer": "客户A"},
        {"name": "接头", "material": "铝合金6061", "price": 15, "quantity": 500, "customer": "客户B"},
    ]

    # 模拟分析
    print(f"测试记录数: {len(test_records)}")

    # 规则预筛
    validated = guardian._precheck(test_records)
    print(f"验证通过: {len(validated)}")

    # 风险推理
    results = guardian._infer_risk(validated)
    print(f"\n风险分布:")
    for r in results:
        print(f"  {r['material']}: {r['risk_level']} (毛利{r['margin']*100:.1f}%)")

    # 聚合报告
    report = guardian._aggregate_report(results, validated)
    print(f"\n汇总:")
    print(f"  总订单: {report['summary']['total']}")
    print(f"  正常: {report['summary']['normal']}")
    print(f"  预警: {report['summary']['warning']}")
    print(f"  危险: {report['summary']['danger']}")
    print(f"  客户集中度: {report['customer_concentration_risk']}")
    print(f"  建议: {report['recommendations']}")

    print("\n=== 测试完成 ===")