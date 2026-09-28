# -*- coding: utf-8 -*-
"""
二维工程图解析器（阶段1：对外接单通道）
与 Xometry tech-details 解析器并行，处理外部客户的原始工程图PDF。

解析能力：
  1. 标题栏：材料牌号 / 图号 / 比例 / 数量 / 设计者
  2. 技术要求：表面处理 / 热处理 / 未注公差
  3. 尺寸标注：公差（±0.02 / H7 / 0/-0.05）
  4. 粗糙度：Ra3.2 / Ra1.6 / ▽

设计原则：
  - 不依赖 Xometry 特定标签格式
  - 解析结果带置信度评分（每提取到一个字段+15分，满分100）
  - 低置信度 → 阶段0门禁自动转人工审核
  - 与 task2_parse_pdf.py（Xometry专用）完全并行

作者: timo.cao | 2026-09-07
"""
import re
import json
from pathlib import Path

try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False

# ══════════════════════════════════════════════════════════
# 正则模式库（覆盖常见工程图标注格式）
# ══════════════════════════════════════════════════════════

# 标题栏字段
RE_MATERIAL = [
    re.compile(r'材料[:：\s]*([^\s,，;；\n]{1,20})'),
    re.compile(r'材质[:：\s]*([^\s,，;；\n]{1,20})'),
    re.compile(r'MATERIAL[:：\s]*([^\s,，;；\n]{1,20})', re.I),
    re.compile(r'牌号[:：\s]*([^\s,，;；\n]{1,20})'),
]
RE_DWG_NO = [
    re.compile(r'图号[:：\s]*([A-Za-z0-9\-_/]{3,30})'),
    re.compile(r'DWG[\s\.]*NO[:：\s]*([A-Za-z0-9\-_/]{3,30})', re.I),
    re.compile(r'图样代号[:：\s]*([A-Za-z0-9\-_/]{3,30})'),
]
RE_QUANTITY = [
    re.compile(r'数量[:：\s]*(\d+)'),
    re.compile(r'件数[:：\s]*(\d+)'),
    re.compile(r'QTY[:：\s]*(\d+)', re.I),
    re.compile(r'数量[（(]\s*台\s*[)）][:：\s]*(\d+)'),
]
RE_SCALE = [
    re.compile(r'比例[:：\s]*([0-9/:：1]+)'),
    re.compile(r'SCALE[:：\s]*([0-9/:：1]+)', re.I),
]

# 技术要求
RE_SURFACE = re.compile(
    r'(阳极氧化|硬质阳极氧化|发黑|发蓝|镀锌|镀铬|镀镍|镀镉|磷化|喷砂|喷漆|'
    r'钝化|氮化|渗碳|淬火|调质|回火|时效|氧化|电泳|达克罗|热处理)'
)
RE_HEAT_TREAT = re.compile(r'(调质|淬火|回火|渗碳|氮化|碳氮共渗|时效|固溶|退火|正火)')
RE_ROUGHNESS = re.compile(r'Ra\s*([\d.]+|∞)')
RE_ROUGHNESS_SYMBOL = re.compile(r'[▽∇]\s*([\d.]+)?')

# 公差标注
RE_TOL_PLUS_MINUS = re.compile(r'±\s*([\d.]+)')
RE_TOL_ISO = re.compile(r'ISO\s*2768\s*[-–—]\s*([mfcehkMFCEHK])')
RE_TOL_FIT = re.compile(r'([HhGgMmKkJjNnPpTt])\s*(\d+)')
RE_TOL_UNILATERAL = re.compile(r'([0-9.]+)\s*[/-]\\?\s*([0-9.]+)')

# 公差等级映射（±值 → IT等级 → 系数）
TOL_PLUS_MINUS_MAP = {
    0.005: ("IT4", "精细", 1.30),
    0.01:  ("IT6", "精细", 1.30),
    0.02:  ("IT7", "中等", 1.0),
    0.05:  ("IT8", "中等", 1.0),
    0.1:   ("IT9", "粗糙", 0.85),
    0.2:   ("IT10", "粗糙", 0.85),
}

# 粗糙度Ra → 系数映射
RA_COEF_MAP = {
    0.2: 1.80, 0.4: 1.60, 0.8: 1.40, 1.6: 1.15, 3.2: 1.0, 6.3: 0.85, 12.5: 0.5,
}


def _extract_first(text, patterns, default=""):
    """用多个正则模式尝试提取第一个匹配"""
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return default


def _extract_all(text, pattern):
    """提取所有匹配"""
    return [m.group(0) for m in pattern.finditer(text)]


def parse_drawing_pdf(pdf_path):
    """
    解析二维工程图PDF，提取报价所需字段。

    与 Xometry 的 tech-details 解析器不同，本函数不依赖固定标签格式，
    而是用通用正则匹配工程图常见标注（标题栏/技术要求/尺寸标注）。

    Args:
        pdf_path: PDF文件路径

    Returns:
        dict: {
            "material": str,          # 材料牌号（原始）
            "dwg_no": str,            # 图号
            "quantity": int,          # 数量
            "scale": str,             # 比例
            "surface_treatments": [], # 表面处理列表
            "heat_treatments": [],    # 热处理列表
            "roughness_ra": float,    # 最小Ra值（最精密）
            "tolerance_grade": str,   # 公差等级（精细/中等/粗糙）
            "tolerance_coef": float,  # 公差系数
            "confidence": float,      # 置信度0-100
            "extracted_fields": [],   # 成功提取的字段名
            "raw_text_length": int,   # 原始文本长度
        }
    """
    result = {
        "material": "", "dwg_no": "", "quantity": 0, "scale": "",
        "surface_treatments": [], "heat_treatments": [],
        "roughness_ra": 0.0, "tolerance_grade": "未知", "tolerance_coef": 1.0,
        "confidence": 0.0, "extracted_fields": [], "raw_text_length": 0,
        "parser": "drawing_parser_v1",
    }

    if not _HAS_PDFPLUMBER:
        result["error"] = "pdfplumber未安装"
        return result

    # 提取全文
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"
    except Exception as e:
        result["error"] = f"PDF解析失败: {e}"
        return result

    result["raw_text_length"] = len(full_text)
    if len(full_text) < 10:
        result["error"] = "PDF文本内容过少，可能是扫描件（需OCR）"
        return result

    extracted = result["extracted_fields"]
    score = 0

    # 1. 标题栏字段
    material = _extract_first(full_text, RE_MATERIAL)
    if material:
        result["material"] = material
        extracted.append("material")
        score += 15

    dwg_no = _extract_first(full_text, RE_DWG_NO)
    if dwg_no:
        result["dwg_no"] = dwg_no
        extracted.append("dwg_no")
        score += 10

    qty_str = _extract_first(full_text, RE_QUANTITY)
    if qty_str:
        try:
            result["quantity"] = int(qty_str)
            extracted.append("quantity")
            score += 15
        except ValueError:
            pass

    scale = _extract_first(full_text, RE_SCALE)
    if scale:
        result["scale"] = scale
        extracted.append("scale")
        score += 5

    # 2. 表面处理
    surfaces = _extract_all(full_text, RE_SURFACE)
    if surfaces:
        result["surface_treatments"] = list(set(surfaces))
        extracted.append("surface_treatments")
        score += 15

    # 3. 热处理
    heat = _extract_all(full_text, RE_HEAT_TREAT)
    if heat:
        result["heat_treatments"] = list(set(heat))
        extracted.append("heat_treatments")
        score += 10

    # 4. 粗糙度
    ra_matches = re.findall(r'Ra\s*([\d.]+)', full_text)
    if ra_matches:
        ra_values = [float(ra) for ra in ra_matches if float(ra) > 0]
        if ra_values:
            result["roughness_ra"] = min(ra_values)  # 取最精密值
            extracted.append("roughness_ra")
            score += 15

    # 5. 公差
    # 优先匹配 ISO 2768
    iso_match = RE_TOL_ISO.search(full_text)
    if iso_match:
        grade = iso_match.group(1).upper()
        if grade in ('F', 'H'):
            result["tolerance_grade"] = "精细"
            result["tolerance_coef"] = 1.30
        elif grade in ('M', 'K'):
            result["tolerance_grade"] = "中等"
            result["tolerance_coef"] = 1.0
        elif grade in ('C', 'E'):
            result["tolerance_grade"] = "粗糙"
            result["tolerance_coef"] = 0.85
        extracted.append("tolerance_iso2768")
        score += 15
    else:
        # 匹配 ±公差
        pm_matches = re.findall(r'±\s*([\d.]+)', full_text)
        if pm_matches:
            pm_values = [float(pm) for pm in pm_matches]
            min_pm = min(pm_values)  # 最严公差决定等级
            for threshold, (it, grade, coef) in sorted(TOL_PLUS_MINUS_MAP.items()):
                if min_pm <= threshold:
                    result["tolerance_grade"] = grade
                    result["tolerance_coef"] = coef
                    break
            extracted.append("tolerance_plus_minus")
            score += 15

    # 6. 配合公差（H7/h6等）
    fit_matches = re.findall(r'[HhGgMmKkJjNnPpTt]\d+', full_text)
    if fit_matches and "tolerance_plus_minus" not in extracted and "tolerance_iso2768" not in extracted:
        result["tolerance_grade"] = "中等"
        result["tolerance_coef"] = 1.0
        extracted.append("tolerance_fit")
        score += 10

    # 置信度评分（基础分10 + 字段分，上限100）
    result["confidence"] = min(100.0, 10.0 + score)

    return result


def parse_drawing_with_confidence(pdf_path):
    """
    解析二维图纸并返回报价就绪的参数字典。

    解析结果根据置信度自动标记是否需要人工审核：
    - confidence >= 70: 可自动报价
    - confidence < 70: 需人工确认（阶段0门禁会拦截）

    Returns:
        dict: 解析结果 + quote_params（可直接传入calc_quote的参数）
    """
    parsed = parse_drawing_pdf(pdf_path)

    quote_params = {
        "material": parsed.get("material") or "UNKNOWN",
        "quantity": parsed.get("quantity") or 1,
        "tolerance": parsed.get("tolerance_grade", "未知"),
        "roughness_ra": parsed.get("roughness_ra", 0.0),
    }

    # 表面处理取第一个
    if parsed.get("surface_treatments"):
        quote_params["surface"] = parsed["surface_treatments"][0]
    else:
        quote_params["surface"] = "无"

    # 置信度门禁
    needs_review = parsed["confidence"] < 70 or quote_params["material"] == "UNKNOWN"

    return {
        "parsed": parsed,
        "quote_params": quote_params,
        "needs_review": needs_review,
        "review_reason": "图纸解析置信度不足或材料未识别" if needs_review else None,
    }


# ══════════════════════════════════════════════════════════
# 自测
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    # 模拟工程图文本测试
    sample_text = """
    技术要求
    1. 未注公差按ISO 2768-m
    2. 表面发黑处理
    3. 未注粗糙度Ra3.2
    4. 调质处理 28-32HRC

    标题栏
    材料：45钢
    图号：DWG-2026-001
    数量：20
    比例：1:1
    """

    # 写入临时PDF文本测试（直接测试正则）
    print("=== 二维图纸解析器自测 ===")
    print(f"pdfplumber可用: {_HAS_PDFPLUMBER}")

    # 测试正则提取
    material = _extract_first(sample_text, RE_MATERIAL)
    print(f"材料: {material}")

    qty = _extract_first(sample_text, RE_QUANTITY)
    print(f"数量: {qty}")

    surfaces = _extract_all(sample_text, RE_SURFACE)
    print(f"表面处理: {surfaces}")

    heat = _extract_all(sample_text, RE_HEAT_TREAT)
    print(f"热处理: {heat}")

    ra = re.findall(r'Ra\s*([\d.]+)', sample_text)
    print(f"粗糙度Ra: {ra}")

    iso = RE_TOL_ISO.search(sample_text)
    print(f"ISO公差: {iso.group(0) if iso else '无'}")

    print("\n=== 自测完成 ===")