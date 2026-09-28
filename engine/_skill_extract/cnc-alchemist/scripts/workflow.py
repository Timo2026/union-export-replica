#!/usr/bin/env python3
"""
workflow.py - CNC非标制造炼金术师主流程
"""
import os
import yaml
import json
import zipfile
from pathlib import Path
from typing import Dict, Optional

from hardware_adaptive import AMDHardware
from llm_dispatch import LLMDispatcher
from geometry_engine import GeometryEngine
from quote_engine import QuoteEngine


def run_workflow(user_text: str, params: Dict, uploaded_files: Dict,
                 config_path: str, output_dir: str) -> Dict:
    """
    执行完整工作流

    Args:
        user_text: 用户自然语言输入
        params: 表单参数
        uploaded_files: 上传的文件
        config_path: 配置文件路径
        output_dir: 输出目录

    Returns:
        完整结果字典
    """
    # 加载配置
    config = {}
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        except Exception as e:
            print(f"[Config] Load error: {e}")

    # 硬件检测
    hw = AMDHardware()
    hw_profile = hw.get_profile()
    hw_level = hw.get_level()

    # 紧急保护
    if hw.should_restrict():
        print(f"[Hardware] Resource warning: {hw.guard}")

    # 初始化组件
    llm = LLMDispatcher(config)
    geom_eng = GeometryEngine(output_dir)
    quote_eng = QuoteEngine()

    # 1. 特征解析
    if params:
        # 填表模式
        feature = _from_ui_form(params)
    else:
        # 自然语言模式
        nlp_feature = llm.parse_features(user_text)
        feature = _from_nlp(nlp_feature)

    # 2. 几何建模
    print("[Geometry] Building model...")
    geo_result = geom_eng.build_and_measure(feature)
    step_path = geo_result.get("step_path")

    # 3. 报价计算
    print("[Quote] Calculating...")
    quote_result = quote_eng.calculate(feature, geo_result)

    # 4. 工艺建议
    print("[Process] Generating advice...")
    process_text = llm.generate_process(feature, geo_result)

    # 5. 打包输出
    print("[Export] Packing outputs...")
    zip_file = _pack_outputs(output_dir, step_path, quote_result, process_text, feature, geo_result)

    return {
        "status": "success" if step_path else "partial",
        "feature": feature,
        "geometry": geo_result,
        "quote": quote_result,
        "process": process_text,
        "step_file": step_path,
        "zip_file": zip_file,
        "hardware": hw_profile,
        "hardware_level": hw_level
    }


def _from_ui_form(params: Dict) -> Dict:
    """从UI表单转换特征"""
    return {
        "material": params.get("material", "6061铝合金"),
        "dimensions": {
            "W": float(params.get("length", params.get("W", 80))),
            "H": float(params.get("width", params.get("H", 80))),
            "D": float(params.get("height", params.get("D", 30)))
        },
        "tolerance": params.get("tolerance", "IT10"),
        "ra": float(params.get("ra", params.get("roughness", 3.2))),
        "surface_treatment": params.get("surface", params.get("surface_treatment", "无")),
        "quantity": max(int(params.get("quantity", 1)), 1),
        "features": params.get("features", [])
    }


def _from_nlp(nlp_feature: Dict) -> Dict:
    """从NLP解析结果转换"""
    if not nlp_feature.get("dimensions"):
        nlp_feature["dimensions"] = {"W": 80, "H": 80, "D": 30}
    if not nlp_feature.get("material"):
        nlp_feature["material"] = "6061铝合金"
    if "features" not in nlp_feature:
        nlp_feature["features"] = []
    return nlp_feature


def _pack_outputs(output_dir: str, step_path: Optional[str],
                  quote_result: Dict, process_text: str,
                  feature: Dict, geometry: Dict) -> str:
    """打包所有输出"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    zip_name = f"cnc_output_{Path(__file__).parent.parent.name}.zip"
    zip_path = output_path / zip_name

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # STEP文件
        if step_path and os.path.exists(step_path):
            zf.write(step_path, arcname="model.step")

        # 报价Excel
        excel_path = _save_excel(quote_result, output_path)
        if excel_path:
            zf.write(excel_path, arcname="quote.xlsx")

        # 工艺文件
        process_path = output_path / "process.txt"
        with open(process_path, 'w', encoding='utf-8') as f:
            f.write(process_text)
        zf.write(process_path, arcname="process.txt")

        # 摘要JSON
        summary = {
            "feature": feature,
            "geometry": geometry,
            "quote": quote_result
        }
        summary_path = output_path / "summary.json"
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        zf.write(summary_path, arcname="summary.json")

    return str(zip_path)


def _save_excel(quote_result: Dict, output_path: Path) -> Optional[str]:
    """保存Excel报价单"""
    try:
        excel_path = output_path / "quote.xlsx"
        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "报价单"

            ws.append(["项目", "金额(元)"])
            for k, v in quote_result.items():
                if k != "physical_basis":
                    ws.append([str(k), str(v)])

            wb.save(excel_path)
            return str(excel_path)
        except ImportError:
            # openpyxl不可用，保存CSV
            csv_path = output_path / "quote.csv"
            with open(csv_path, 'w', encoding='utf-8') as f:
                f.write("项目,金额(元)\n")
                for k, v in quote_result.items():
                    if k != "physical_basis":
                        f.write(f"{k},{v}\n")
            return str(csv_path)
    except Exception as e:
        print(f"[Excel] Save error: {e}")
        return None


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        user_input = sys.argv[1]
        result = run_workflow(user_input, {}, {}, None, str(Path.home() / '.openclaw/output'))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("用法: python3 workflow.py '<自然语言描述>'")
