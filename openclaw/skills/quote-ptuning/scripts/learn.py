#!/home/Developer/miniconda3/envs/lk-skills/bin/python
# -*- coding: utf-8 -*-
"""
Quote P-Tuning 学习脚本
从 RAG 知识库学习报价知识
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from collections import defaultdict

HOME = Path.home()
CAD_RAG_DIR = HOME / ".openclaw" / "cad_rag"
SKILL_DIR = HOME / ".openclaw" / "skills" / "quote-ptuning"
SKILL_DIR.mkdir(parents=True, exist_ok=True)

def learn_from_rag():
    """从 RAG 知识库学习"""
    print("=" * 60)
    print("Quote P-Tuning 学习")
    print("=" * 60)
    
    db_path = CAD_RAG_DIR / "metadata.db"
    
    if not db_path.exists():
        print("❌ RAG 知识库不存在")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. 学习报价记录
    print("\n【1】学习报价记录...")
    cursor.execute("""
        SELECT part_name, material, quantity, unit_price 
        FROM quotes 
        WHERE unit_price > 0
        ORDER BY created_at DESC 
        LIMIT 200
    """)
    
    quotes = cursor.fetchall()
    print(f"   有效报价: {len(quotes)} 条")
    
    # 2. 统计材料价格
    print("\n【2】统计材料价格...")
    material_stats = defaultdict(list)
    for row in quotes:
        part_name, material, quantity, unit_price = row
        if material and unit_price > 0:
            material_stats[material].append({
                "price": unit_price,
                "quantity": quantity or 1
            })
    
    material_prices = {}
    for material, data in material_stats.items():
        prices = [d["price"] for d in data]
        quantities = [d["quantity"] for d in data]
        avg_price = sum(prices) / len(prices)
        avg_qty = sum(quantities) / len(quantities)
        material_prices[material] = {
            "count": len(data),
            "avg_price": round(avg_price, 2),
            "min_price": min(prices),
            "max_price": max(prices),
            "avg_quantity": round(avg_qty, 1)
        }
    
    print(f"   学习材料: {len(material_prices)} 种")
    for m, data in sorted(material_prices.items(), key=lambda x: -x[1]['count'])[:10]:
        print(f"     - {m}: ¥{data['avg_price']:.2f} (范围 ¥{data['min_price']:.0f}-{data['max_price']:.0f})")
    
    # 3. 统计数量梯度
    print("\n【3】统计数量梯度...")
    qty_groups = defaultdict(list)
    for row in quotes:
        part_name, material, quantity, unit_price = row
        if quantity and unit_price > 0:
            # 按数量级分组
            if quantity <= 5:
                qty_groups["1-5件"].append(unit_price)
            elif quantity <= 10:
                qty_groups["6-10件"].append(unit_price)
            elif quantity <= 20:
                qty_groups["11-20件"].append(unit_price)
            elif quantity <= 50:
                qty_groups["21-50件"].append(unit_price)
            else:
                qty_groups["50+件"].append(unit_price)
    
    print("   数量梯度 (平均单价):")
    for qty, prices in sorted(qty_groups.items()):
        if prices:
            avg = sum(prices) / len(prices)
            print(f"     - {qty}: ¥{avg:.2f}")
    
    # 4. 计算材料成本系数
    print("\n【4】材料成本系数...")
    base_material = "304不锈钢"
    base_prices = [d["price"] for d in material_stats.get(base_material, [])]
    base_avg = sum(base_prices) / len(base_prices) if base_prices else 100
    
    material_coefficients = {}
    for material, data in material_stats.items():
        if data and base_avg > 0:
            material_avg = sum(d["price"] for d in data) / len(data)
            coef = material_avg / base_avg
            material_coefficients[material] = round(coef, 3)
    
    conn.close()
    
    # 生成学习报告
    report = {
        "timestamp": datetime.now().isoformat(),
        "quotes_count": len(quotes),
        "material_prices": material_prices,
        "quantity_gradient": {k: round(sum(v)/len(v), 2) for k, v in qty_groups.items() if v},
        "material_coefficients": material_coefficients,
        "base_material": base_material,
        "base_avg_price": round(base_avg, 2)
    }
    
    # 保存学习结果
    learn_dir = SKILL_DIR / "learned"
    learn_dir.mkdir(exist_ok=True)
    
    report_path = learn_dir / "quote_knowledge.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    # 生成报价规范
    spec_path = learn_dir / "quote_spec.md"
    with open(spec_path, 'w', encoding='utf-8') as f:
        f.write("# 报价规范 (P-Tuning 学习结果)\n\n")
        f.write(f"**学习时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## 材料价格表\n\n")
        f.write("| 材料 | 平均单价 | 范围 | 样本数 |\n")
        f.write("|------|----------|------|--------|\n")
        for m, data in sorted(material_prices.items(), key=lambda x: -x[1]['count'])[:15]:
            f.write(f"| {m} | ¥{data['avg_price']:.2f} | ¥{data['min_price']:.0f}-{data['max_price']:.0f} | {data['count']} |\n")
        f.write("\n## 数量梯度\n\n")
        for qty, avg_price in sorted(report["quantity_gradient"].items()):
            f.write(f"- {qty}: ¥{avg_price:.2f} (均价)\n")
    
    print(f"\n✅ 学习完成!")
    print(f"   知识库: {report_path}")
    print(f"   规范: {spec_path}")
    
    return report

if __name__ == "__main__":
    learn_from_rag()