#!/usr/bin/env python3
"""
invoke.py - CNC风控官统一调用入口
"""
import os
import sys
import json

# 添加入口路径
sys.path.insert(0, os.path.dirname(__file__))

from cnc_risk_guardian import RiskGuardian, run


def main():
    """CLI入口"""
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        print(f"=== CNC经营风控官 ===")
        print(f"分析文件: {file_path}")

        result = run({"file_path": file_path})

        print(f"\n分析结果:")
        print(f"  总记录: {result.get('total_records', 0)}")
        print(f"  正常: {result['summary'].get('normal', 0)}")
        print(f"  预警: {result['summary'].get('warning', 0)}")
        print(f"  危险: {result['summary'].get('danger', 0)}")
        print(f"  客户集中度: {result.get('customer_concentration_risk')}")
        print(f"  耗时: {result.get('elapsed_ms', 0)}ms")

        # 保存JSON
        output_file = "/tmp/risk_report.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n报告已保存: {output_file}")

    else:
        print("用法: python invoke.py <报价Excel/CSV文件路径>")


if __name__ == "__main__":
    main()