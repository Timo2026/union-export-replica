"""intake.py — L4 多模态摄入 + 结构化 RFQ 抽取.

关键设计 (实测教训): 真实 /api/cnc-quick 的模糊 message 解析会把 "阳极氧化" 丢成
surface="无", 导致 S3(304+阳极氧化) 漏判。因此 Union Agent 必须自己做**结构化字段抽取**
(material / surface / tolerance / quantity / dimensions 显式成字段), 再喂给确定性引擎。

多模态规则 (PRD 5.2): 语音只是证据源之一, 不能静默覆盖邮件/图纸 canonical 字段;
关键尺寸冲突 → VOICE_EMAIL_CONFLICT → HITL。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# ---- 材料归一 (对齐引擎 core.material_utils 常用别名) ----
_MATERIAL_ALIAS = {
    "6061": "6061", "al6061": "6061", "6061铝": "6061", "铝合金": "6061", "铝": "6061",
    "7075": "7075", "al7075": "7075",
    "304": "304", "sus304": "304", "304不锈钢": "304", "不锈钢304": "304",
    "316l": "316L", "316": "316L", "sus316l": "316L",
    "tc4": "TC4", "钛合金": "TC4", "tc4钛合金": "TC4", "grade5": "TC4",
    "45钢": "45钢", "45#": "45钢", "45号钢": "45钢",
    "q235": "Q235", "碳钢": "Q235", "a3钢": "Q235",
    "黄铜": "黄铜", "h59": "黄铜", "h62": "黄铜", "brass": "黄铜",
}
# ---- 表面处理归一 (中英) ----
_SURFACE_ALIAS = {
    "阳极氧化": "阳极氧化", "anodizing": "阳极氧化", "anodize": "阳极氧化", "anodized": "阳极氧化", "硬质氧化": "阳极氧化",
    "钝化": "钝化", "passivation": "钝化", "passivate": "钝化",
    "发黑": "发黑", "blackening": "发黑", "black oxide": "发黑", "氧化发黑": "发黑",
    "镀锌": "镀锌", "zinc": "镀锌", "galvaniz": "镀锌", "镀彩锌": "镀锌",
    "镀铬": "镀铬", "chrome": "镀铬", "镀硬铬": "镀铬",
    "镀镍": "镀镍", "nickel": "镀镍",
    "磷化": "磷化", "phosphat": "磷化",
    "喷漆": "喷漆", "paint": "喷漆", "喷涂": "喷漆",
    "喷砂": "喷砂", "sandblast": "喷砂", "喷砂氧化": "喷砂",
    "无": "无", "none": "无", "as-machined": "无", "mill finish": "无",
}
_TOL_GRADES = ["IT4", "IT5", "IT6", "IT7", "IT8", "IT9", "IT10"]


def _norm_material(text: str) -> Optional[str]:
    low = text.lower()
    # 先精确长别名优先
    for k in sorted(_MATERIAL_ALIAS, key=len, reverse=True):
        if k in low:
            return _MATERIAL_ALIAS[k]
    return None


def _norm_surface(text: str) -> Optional[str]:
    low = text.lower()
    for k in sorted(_SURFACE_ALIAS, key=len, reverse=True):
        if k in low:
            return _SURFACE_ALIAS[k]
    return None


def _extract_quantity(text: str) -> Optional[int]:
    m = re.search(r"(\d[\d,]*)\s*(?:个|件|pcs|pieces|units|qty|数量)", text, re.I)
    if m:
        return int(m.group(1).replace(",", ""))
    m = re.search(r"(?:quantity|qty|数量)\D{0,4}(\d+)", text, re.I)
    return int(m.group(1)) if m else None


def _extract_tolerance(text: str) -> Tuple[Optional[str], Optional[float]]:
    """返回 (IT 等级, ±mm 数值)."""
    g = None
    for t in _TOL_GRADES:
        if re.search(rf"\b{t}\b", text, re.I):
            g = t
            break
    mm = None
    # 优先匹配带 ±/+/- 的显式公差 (避免误吃 "100x50x10mm" 里的尺寸)
    m = re.search(r"(?:±|\+/-|\+-)\s*(\d+\.?\d*)\s*(?:mm|毫米)", text)
    if not m:
        m = re.search(r"tolerance[^\d±]{0,8}(\d+\.?\d*)\s*(?:mm|毫米)", text, re.I)
    if m:
        mm = float(m.group(1))
    if mm is not None and g is None:
        # 由 ±mm 粗映射 IT 等级 (仅用于缺失时提示, 不覆盖显式等级)
        g = "IT5" if mm <= 0.02 else ("IT6" if mm <= 0.05 else "IT7")
    return g, mm


def _extract_dimensions(text: str) -> Optional[List[float]]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?", text, re.I)
    if m:
        return [float(m.group(1)), float(m.group(2)), float(m.group(3))]
    return None


def extract_rfq(email_text: str, customer: Optional[Dict] = None) -> Dict[str, Any]:
    """从邮件正文抽取 canonical RFQ 结构化字段 + 缺失项 (UC-02)."""
    text = email_text or ""
    rfq: Dict[str, Any] = {
        "material": _norm_material(text),
        "surface": _norm_surface(text),
        "quantity": _extract_quantity(text),
        "dimensions_mm": _extract_dimensions(text),
        "process": "CNC",
        "raw_text": text,
    }
    g, mm = _extract_tolerance(text)
    rfq["tolerance_grade"] = g
    rfq["tolerance_mm"] = mm

    missing = []
    if not rfq["material"]:
        missing.append("material")
    if rfq["quantity"] is None:
        missing.append("quantity")
    if not rfq["surface"]:
        missing.append("surface_finish")
    if not rfq["tolerance_grade"]:
        missing.append("tolerance")
    rfq["missing_information"] = missing
    if customer:
        rfq["customer"] = customer
    return rfq


def extract_voice_claims(transcript: str) -> List[Dict[str, Any]]:
    """从语音转写抽取客户约束 claim (关键尺寸/公差/交期变更)."""
    claims: List[Dict[str, Any]] = []
    t = transcript or ""
    g, mm = _extract_tolerance(t)
    if mm is not None:
        claims.append({"field": "tolerance_mm", "value": mm, "grade": g,
                       "phrase": t.strip()[:120]})
    mat = _norm_material(t)
    if mat:
        claims.append({"field": "material", "value": mat, "phrase": t.strip()[:120]})
    surf = _norm_surface(t)
    if surf:
        claims.append({"field": "surface", "value": surf, "phrase": t.strip()[:120]})
    qty = _extract_quantity(t)
    if qty:
        claims.append({"field": "quantity", "value": qty, "phrase": t.strip()[:120]})
    return claims


def detect_multimodal_conflict(rfq: Dict[str, Any], voice_claims: List[Dict[str, Any]],
                               tol_delta_mm: float = 0.005) -> List[Dict[str, Any]]:
    """比对 canonical(邮件/图纸) vs 语音 claim; 关键尺寸不一致 → 冲突 (不静默覆盖)."""
    conflicts: List[Dict[str, Any]] = []
    for c in voice_claims:
        f = c.get("field")
        if f == "tolerance_mm" and rfq.get("tolerance_mm") is not None:
            if abs(float(c["value"]) - float(rfq["tolerance_mm"])) > tol_delta_mm:
                conflicts.append({
                    "type": "VOICE_EMAIL_CONFLICT", "field": "tolerance_mm",
                    "email_value": rfq["tolerance_mm"], "voice_value": c["value"],
                    "resolution": "HITL", "reason": "语音放宽关键公差, 与邮件不一致, 禁止静默覆盖",
                })
        elif f in ("material", "surface"):
            cv, rv = c.get("value"), rfq.get(f if f != "surface" else "surface")
            if rv and cv and str(cv) != str(rv):
                conflicts.append({"type": "VOICE_EMAIL_CONFLICT", "field": f,
                                  "email_value": rv, "voice_value": cv,
                                  "resolution": "HITL", "reason": f"语音{f}与邮件不一致"})
    return conflicts
