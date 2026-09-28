#!/home/Developer/miniconda3/envs/lk-skills/bin/python
# -*- coding: utf-8 -*-
"""
Quote P-Tuning - 数据清洗版
使用中位数过滤异常值
"""

import os
import re
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

HOME = Path.home()

SKILL_DIR = HOME / ".openclaw/skills/quote-ptuning"
LEARNED_DIR = SKILL_DIR / "learned"
LEARNED_DIR.mkdir(parents=True, exist_ok=True)

DATA_SOURCES = [
    "/media/timo/CE18065718063F49/图纸包",
    "/home/Developer/BAOJIADAN",
]

def find_xlsx_files():
    xlsx_files = []
    for source_path in DATA_SOURCES:
        if not os.path.exists(source_path):
            continue
        for root, dirs, files in os.walk(source_path):
            for f in files:
                if f.endswith('.xlsx') and not f.startswith('~') and '~$' not in f:
                    xlsx_files.append(os.path.join(root, f))
    return xlsx_files

def parse_xlsx(filepath):
    try:
        import openpyxl
        wb = openpyxl.load_workbook(filepath, data_only=True, read_only=True)
        
        for ws in wb.worksheets:
            # 只读取前 100 行
            for i, row in enumerate(ws.iter_rows(values_only=True, max_row=100)):
                if i > 100:
                    break
                row_text = " ".join([str(c) if c else "" for c in row])
                
                # 提取合理的价格 (1-10000 元)
                prices = re.findall(r'¥?\s*([1-9]\d{0,3}(?:\.\d{1,2})?)\s*元?', row_text)
                for p in prices:
                    try:
                        val = float(p)
                        if 1 <= val <= 10000:  # 过滤异常值
                            yield val
                    except:
                        pass
                
                # 提取合理数量 (1-1000)
                quantities = re.findall(r'[1-9]\d{0,2}\s*(?:件|个|台|套)', row_text)
                for q in quantities:
                    try:
                        val = int(re.search(r'(\d+)', q).group(1))
                        if 1 <= val <= 1000:
                            yield val
                    except:
                        pass
        
        wb.close()
    except:
        pass

def median(values):
    """计算中位数"""
    values = sorted(values)
    n = len(values)
    if n == 0:
        return 0
    if n % 2 == 0:
        return (values[n//2-1] + values[n//2]) / 2
    return values[n//2]

def learn():
    print("=" * 60)
    print("Quote P-Tuning 数据清洗")
    print("=" * 60)
    
    xlsx_files = find_xlsx_files()
    print(f"\n扫描 {len(xlsx_files)} 个 XLSX 文件...")
    
    all_prices = []
    all_quantities = []
    
    for i, f in enumerate(xlsx_files):
        if i % 50 == 0:
            print(f"  进度: {i}/{len(xlsx_files)}")
        for val in parse_xlsx(f):
            if 1 <= val <= 10000:
                all_prices.append(val)
            elif 1 <= val <= 1000:
                all_quantities.append(val)
    
    print(f"\n提取价格样本: {len(all_prices)} 个 (已过滤异常)")
    
    if all_prices:
        # 使用中位数
        median_price = median(all_prices)
        print(f"价格中位数: ¥{median_price:.2f}")
        print(f"价格范围: ¥{min(all_prices):.2f} - ¥{max(all_prices):.2f}")
    
    # 按数量分组统计
    qty_groups = defaultdict(list)
    for i in range(len(all_prices)):
        if i < len(all_quantities):
            qty = all_quantities[i]
            if qty <= 5:
                qty_groups["1-5件"].append(all_prices[i])
            elif qty <= 10:
                qty_groups["6-10件"].append(all_prices[i])
            elif qty <= 20:
                qty_groups["11-20件"].append(all_prices[i])
            elif qty <= 50:
                qty_groups["21-50件"].append(all_prices[i])
            else:
                qty_groups["50+件"].append(all_prices[i])
    
    print("\n数量梯度 (中位数):")
    for qty in ["1-5件", "6-10件", "11-20件", "21-50件", "50+件"]:
        if qty_groups.get(qty):
            m = median(qty_groups[qty])
            print(f"  {qty}: ¥{m:.2f} (样本{len(qty_groups[qty])})")
    
    # 保存清洗后的数据
    result = {
        "timestamp": datetime.now().isoformat(),
        "total_samples": len(all_prices),
        "median_price": median_price if all_prices else 100,
        "price_range": [min(all_prices), max(all_prices)] if all_prices else [1, 10000],
        "quantity_gradient": {k: median(v) if v else 0 for k, v in qty_groups.items()},
    }
    
    with open(LEARNED_DIR / "quote_clean.json", 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ 数据已清洗保存")
    return result

if __name__ == "__main__":
    learn()