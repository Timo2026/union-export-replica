"""matcher.py — v2.3.0 供应商匹配（标签打分 TopN）。

契约：输入 RFQ + 候选 supplier 列表 → TopN（默认 3）按 score desc。
评分维度（可配权重）：
  - material      材料命中（任一命中 +w，否则 0）
  - process       工艺命中（任一命中 +w，否则 0）
  - lead_time     交期 ≤ 承诺 +w，超额 -w/2
  - capacity      月产能 ≥ 数量 +w，否则 0
  - quality       AS9100/IATF16949 +w，ISO9001 0
  - rating        rating × w（线性）
  - region_match  目的地与供应商地区一致 +w

降级：真几何相似度（shape signature）未实现，标签打分足够 v2.3.0 演示；
后续可加 embedding 评分（roadmap）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# 默认权重（每维最大值）
DEFAULT_WEIGHTS: Dict[str, float] = {
    "material": 3.0,
    "process": 2.0,
    "lead_time": 2.0,
    "capacity": 1.0,
    "quality": 1.0,
    "rating": 0.5,
    "region_match": 1.0,
}

_QUALITY_BONUS = {
    "IATF16949": 1.0,
    "AS9100": 0.7,
    "ISO9001": 0.0,
}


def score_supplier(
    rfq: Dict[str, Any],
    supplier: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """计算单个供应商对 RFQ 的得分（连续值，越高越匹配）。"""
    w = weights or DEFAULT_WEIGHTS
    score = 0.0

    # 1. 材料命中
    rfq_mat = rfq.get("material")
    if rfq_mat and rfq_mat in (supplier.get("materials") or []):
        score += w["material"]

    # 2. 工艺命中
    rfq_procs = rfq.get("processes") or []
    sup_procs = supplier.get("processes") or []
    if rfq_procs and any(p in sup_procs for p in rfq_procs):
        score += w["process"]

    # 3. 交期
    promised = rfq.get("promised_lead_time_days")
    actual = supplier.get("lead_time_days")
    if promised is not None and actual is not None:
        if actual <= promised:
            score += w["lead_time"]
        else:
            score -= w["lead_time"] * 0.5

    # 4. 产能
    qty = rfq.get("quantity")
    cap = supplier.get("capacity_per_month")
    if qty is not None and cap is not None and cap >= qty:
        score += w["capacity"]

    # 5. 质量
    qg = supplier.get("quality_grade")
    score += _QUALITY_BONUS.get(qg, 0.0) * w["quality"]

    # 6. 评分线性
    rating = supplier.get("rating")
    if rating is not None:
        score += float(rating) * w["rating"]

    # 7. 地区一致
    if (rfq.get("destination_region") and supplier.get("region")
            and rfq["destination_region"] == supplier["region"]):
        score += w["region_match"]

    return round(score, 4)


def match_top_n(
    rfq: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    top_n: int = 3,
    weights: Optional[Dict[str, float]] = None,
) -> List[Tuple[float, Dict[str, Any]]]:
    """打分排序取 TopN；同分按 id 升序（确定性）。"""
    scored = [(score_supplier(rfq, s, weights), s) for s in candidates]
    scored.sort(key=lambda x: (-x[0], x[1].get("id", 0)))
    return scored[:top_n]