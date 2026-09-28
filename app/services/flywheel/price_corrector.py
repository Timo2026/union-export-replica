"""flywheel.price_corrector — 分级价格修正器.

决策锁定 (2026-09-19): 分级上限
  - 租户历史样本 <10:  ±5%
  - 10-50:             ±10%
  - 50+:               ±15%

铁律①红线: 只调修正系数, 不改 Timo 确定性数字.
输出含完整审计链: base_price (不动) + correction_pct + corrected_price + evidence + audit_chain.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class CorrectionTier(str, Enum):
    COLD = "cold"        # <10 样本, ±5%
    WARM = "warm"        # 10-50 样本, ±10%
    HOT = "hot"          # 50+ 样本, ±15%


def classify_tier(sample_count: int) -> CorrectionTier:
    if sample_count >= 50:
        return CorrectionTier.HOT
    if sample_count >= 10:
        return CorrectionTier.WARM
    return CorrectionTier.COLD


def tier_cap(tier: CorrectionTier) -> float:
    """该层级最大修正幅度 (小数)."""
    return {CorrectionTier.COLD: 0.05,
            CorrectionTier.WARM: 0.10,
            CorrectionTier.HOT: 0.15}[tier]


@dataclass
class CorrectionResult:
    base_price: float                       # Timo 引擎原价 (不动)
    corrected_price: float                  # 修正后
    correction_pct: float                   # 修正幅度 (正=上调, 负=下调)
    correction_abs: float
    tier: str
    sample_count: int
    cap_pct: float
    capped: bool                            # 是否触及上限
    evidence: List[Dict[str, Any]]          # 证据芯片 (可溯源)
    reasoning: str                          # 可解释说明
    audit_chain: str                        # sha 审计链
    confidence: float                       # 0..1


class PriceCorrector:
    """基于历史相似召回的报价修正器.

    修正逻辑 (可解释):
      1. 历史 won 平均毛利 vs 当前毛利 → 上调/下调倾向
      2. 历史 lost 主因 (价格/交期/质量) → 避免重蹈
      3. 价格带宽 (历史成交 p25-p75) → 拉向中位
      4. 最终修正 = 加权和, 受 tier_cap 硬约束
    """

    def __init__(self):
        pass

    def correct(self, engine_quote: Dict[str, Any],
                recall: Dict[str, Any],
                tenant_id: str,
                engine_sha: Optional[str] = None) -> CorrectionResult:
        """核心修正.

        Args:
            engine_quote: Timo 引擎报价 dict (含 final_price, margin_pct, unit_price)
            recall: SimilarRecall.before_quote() 返回值
                (含 similar_won, similar_lost, price_band, sample_count, confidence)
            tenant_id: 租户 ID (审计链用)
            engine_sha: Timo 引擎 sha16/sha256 锁 (审计链用)
        """
        base = float(engine_quote.get("final_price")
                     or engine_quote.get("unit_price") or 0.0)
        base_margin = float(engine_quote.get("margin_pct") or 0.0)

        similar_won = recall.get("similar_won", [])
        similar_lost = recall.get("similar_lost", [])
        price_band = recall.get("price_band", {})
        sample_count = int(recall.get("sample_count", 0))
        recall_conf = float(recall.get("confidence", 0.0))

        tier = classify_tier(sample_count)
        cap = tier_cap(tier)

        # 修正信号 (各为 -1..1 的方向倾向, 正=上调)
        signals: List[tuple] = []

        # 信号1: 历史 won 毛利均值 vs 当前
        if similar_won:
            won_margins = [float(w.get("payload", {}).get("margin_pct") or 0) for w in similar_won]
            avg_won_margin = sum(won_margins) / len(won_margins)
            if avg_won_margin > 0 and base_margin > 0:
                # 当前毛利低于历史均值 → 可以上调 (向历史靠拢)
                delta = (avg_won_margin - base_margin) / max(avg_won_margin, 1.0)
                delta = max(-1.0, min(1.0, delta * 0.5))  # 衰减
                signals.append(("won_margin_gap", delta, avg_won_margin))
        else:
            avg_won_margin = 0.0

        # 信号2: 历史 lost 价格信号
        lost_penalty = 0.0
        if similar_lost:
            lost_reasons = [l.get("payload", {}).get("lost_reason", "") for l in similar_lost]
            price_losses = sum(1 for r in lost_reasons if "price" in str(r).lower()
                               or "expensive" in str(r).lower()
                               or "贵" in str(r))
            if price_losses > 0:
                # 历史因价格失败 → 下调倾向
                lost_penalty = -0.3 * (price_losses / len(similar_lost))
                signals.append(("lost_price_signal", lost_penalty, price_losses))

        # 信号3: 拉向历史成交价带宽中位
        band_signal = 0.0
        p50 = price_band.get("p50")
        if p50 and base > 0:
            # 当前价 vs 历史中位偏差
            diff = (base - p50) / base
            band_signal = max(-1.0, min(1.0, -diff * 0.3))  # 拉向中位
            signals.append(("price_band_pull", band_signal, p50))

        # 加权合成
        raw_correction = 0.0
        weights_sum = 0.0
        for _name, val, _ev in signals:
            w = 1.0 if _name == "won_margin_gap" else (0.7 if _name == "lost_price_signal" else 0.5)
            raw_correction += val * w
            weights_sum += w
        raw_correction = (raw_correction / weights_sum) if weights_sum > 0 else 0.0

        # 乘以召回置信度 + tier 放大因子
        tier_factor = {CorrectionTier.COLD: 0.5, CorrectionTier.WARM: 0.8,
                       CorrectionTier.HOT: 1.0}[tier]
        adjusted = raw_correction * recall_conf * tier_factor

        # 硬上限约束
        capped = False
        if abs(adjusted) > cap:
            adjusted = cap if adjusted > 0 else -cap
            capped = True

        correction_pct = round(adjusted, 4)
        correction_abs = round(base * correction_pct, 2)
        corrected_price = round(base + correction_abs, 2)

        # 证据芯片 (top-3 won + top-2 lost)
        evidence = []
        for w in similar_won[:3]:
            p = w.get("payload", {})
            evidence.append({
                "type": "won", "context_id": p.get("context_id"),
                "material": p.get("material"), "price": p.get("final_price"),
                "margin_pct": p.get("margin_pct"), "score": w.get("score"),
            })
        for l in similar_lost[:2]:
            p = l.get("payload", {})
            evidence.append({
                "type": "lost", "context_id": p.get("context_id"),
                "lost_reason": p.get("lost_reason"), "score": l.get("score"),
            })

        # 可解释说明
        reasons = []
        if signals:
            for name, val, ev in signals:
                arrow = "↑" if val > 0.01 else ("↓" if val < -0.01 else "·")
                reasons.append(f"{name}{arrow}({ev})")
        reasoning = "; ".join(reasons) or "no_signal"

        # 审计链
        audit_input = f"{engine_sha or 'no-sha'}|{tenant_id}|{base}|{correction_pct}|{tier.value}"
        audit_chain = hashlib.sha256(audit_input.encode()).hexdigest()[:16]

        confidence = recall_conf * tier_factor

        return CorrectionResult(
            base_price=base,
            corrected_price=corrected_price,
            correction_pct=correction_pct,
            correction_abs=correction_abs,
            tier=tier.value,
            sample_count=sample_count,
            cap_pct=cap,
            capped=capped,
            evidence=evidence,
            reasoning=reasoning,
            audit_chain=audit_chain,
            confidence=round(confidence, 3),
        )

    def result_to_dict(self, r: CorrectionResult) -> Dict[str, Any]:
        """转可序列化 dict (注入 Context / 审计日志)."""
        return {
            "base_price": r.base_price,
            "corrected_price": r.corrected_price,
            "correction_pct": r.correction_pct,
            "correction_abs": r.correction_abs,
            "tier": r.tier,
            "sample_count": r.sample_count,
            "cap_pct": r.cap_pct,
            "capped": r.capped,
            "evidence": r.evidence,
            "reasoning": r.reasoning,
            "audit_chain": r.audit_chain,
            "confidence": r.confidence,
            "_flywheel": True,
        }
