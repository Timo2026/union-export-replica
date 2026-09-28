"""tests/test_flywheel.py — v6.2 商业飞轮核心测试.

覆盖:
  - 双层沙箱隔离 (single + group)
  - 相似召回 + 冷启动
  - 分级价格修正 (±5/10/15%)
  - 反应打标 (silent/won/lost/reacting + vacation 豁免)
  - 飞轮闭环 (索引 → 召回 → 修正)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 services 包可导入
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.flywheel.tenant import resolve_tenant, TenantScope
from services.flywheel.vector_store import VectorStore, reset_global as reset_vs
from services.flywheel.reaction_labeler import ReactionLabeler, Reaction
from services.flywheel.price_corrector import PriceCorrector, classify_tier, tier_cap, CorrectionTier
from services.flywheel.quote_indexer import QuoteIndexer
from services.flywheel.similar_recall import SimilarRecall
from services.flywheel.feedback_loop import FeedbackLoop, reset_global as reset_loop


@pytest.fixture
def flywheel():
    """每个测试用独立的内存飞轮."""
    reset_vs()
    reset_loop()
    store = VectorStore(backend="memory")
    loop = FeedbackLoop(store=store)
    yield loop
    reset_vs()
    reset_loop()


# ========== 沙箱隔离 ==========

class TestSandboxIsolation:
    def test_single_tenant_default(self):
        ctx = {"customer": {"customer_id": "CUST-A", "name": "Acme"}}
        scope = resolve_tenant(ctx)
        assert scope.tenant_id == "CUST-A"
        assert not scope.is_group
        assert scope.collection_for("quotes") == "tenant_CUST-A_quotes"

    def test_group_tenant_mode(self):
        ctx = {"customer": {"customer_id": "CUST-A", "group_id": "GROUP-X"}}
        scope = resolve_tenant(ctx)
        assert scope.tenant_id == "GROUP-X"
        assert scope.is_group
        assert scope.collection_for("quotes") == "tenant_GROUP-X_quotes"

    def test_anonymous_tenant_hash(self):
        ctx = {"customer": {"name": "Unknown Co"}}
        scope = resolve_tenant(ctx)
        assert scope.tenant_id.startswith("ANON-")
        # 确定性: 同样输入 → 同样 tenant
        scope2 = resolve_tenant({"customer": {"name": "Unknown Co"}})
        assert scope.tenant_id == scope2.tenant_id

    def test_two_tenants_isolated_search(self, flywheel):
        """核心: A 的索引绝不能被 B 召回."""
        ctx_a = {"context_id": "RFQ-A1", "customer": {"customer_id": "CUST-A"},
                 "rfq": {"material": "6061", "surface": "anodize", "quantity": 100,
                         "tolerance_grade": "IT7", "process": "CNC"},
                 "commercial": {"quote": {"final_price": 5000, "margin_pct": 20}}}
        ctx_b = {"context_id": "RFQ-B1", "customer": {"customer_id": "CUST-B"},
                 "rfq": {"material": "6061", "surface": "anodize", "quantity": 100,
                         "tolerance_grade": "IT7", "process": "CNC"},
                 "commercial": {"quote": {"final_price": 8000, "margin_pct": 30}}}

        # A 和 B 索引同工艺但不同价
        flywheel.post_quote(ctx_a, reaction="won")
        flywheel.post_quote(ctx_b, reaction="won")

        # A 召回 → 只命中 A 的
        scope_a = resolve_tenant(ctx_a)
        result_a = flywheel.recall.before_quote(scope_a, ctx_a)
        prices_a = [h["payload"]["final_price"] for h in result_a["similar_won"]]
        assert 5000 in prices_a
        assert 8000 not in prices_a, "沙箱泄漏: B 的数据被 A 召回!"

        # B 召回 → 只命中 B 的
        scope_b = resolve_tenant(ctx_b)
        result_b = flywheel.recall.before_quote(scope_b, ctx_b)
        prices_b = [h["payload"]["final_price"] for h in result_b["similar_won"]]
        assert 8000 in prices_b
        assert 5000 not in prices_b


# ========== 冷启动 ==========

class TestColdStart:
    def test_new_tenant_cold_start(self, flywheel):
        ctx = {"context_id": "RFQ-NEW", "customer": {"customer_id": "NEWCO"},
               "rfq": {"material": "7075", "surface": "polish", "quantity": 50}}
        scope = resolve_tenant(ctx)
        result = flywheel.recall.before_quote(scope, ctx)
        assert result["_cold_start"] is True
        assert result["sample_count"] == 0
        assert result["collection"] == "kb_market"


# ========== 分级价格修正 ==========

class TestPriceCorrection:
    def test_tier_classification(self):
        assert classify_tier(0) == CorrectionTier.COLD
        assert classify_tier(9) == CorrectionTier.COLD
        assert classify_tier(10) == CorrectionTier.WARM
        assert classify_tier(49) == CorrectionTier.WARM
        assert classify_tier(50) == CorrectionTier.HOT
        assert classify_tier(100) == CorrectionTier.HOT

    def test_tier_caps(self):
        assert tier_cap(CorrectionTier.COLD) == 0.05
        assert tier_cap(CorrectionTier.WARM) == 0.10
        assert tier_cap(CorrectionTier.HOT) == 0.15

    def test_correction_never_exceeds_cap(self):
        """铁律: 修正幅度永远受 tier_cap 硬约束."""
        corrector = PriceCorrector()
        # 构造一个极强的上调信号 (recall confidence=1, 100 samples)
        recall = {
            "similar_won": [{"payload": {"margin_pct": 35}} for _ in range(10)],
            "similar_lost": [],
            "price_band": {"p50": 99999},  # 远高于 base, 强拉
            "sample_count": 100,
            "confidence": 1.0,
        }
        engine_quote = {"final_price": 1000, "margin_pct": 10}
        result = corrector.correct(engine_quote, recall, tenant_id="T")
        cap = tier_cap(CorrectionTier.HOT)  # 100 samples → HOT
        assert abs(result.correction_pct) <= cap + 1e-6
        if result.capped:
            assert abs(result.correction_pct) == pytest.approx(cap)

    def test_correction_audit_chain_present(self):
        """修正结果必须有审计链 (铁律①可追溯)."""
        corrector = PriceCorrector()
        recall = {"similar_won": [], "similar_lost": [], "price_band": {},
                  "sample_count": 0, "confidence": 0.0}
        result = corrector.correct({"final_price": 100}, recall, "T", "abc123")
        assert len(result.audit_chain) == 16
        assert result.base_price == 100
        assert result.tier == "cold"

    def test_zero_recall_no_correction(self):
        """无历史数据时 → 修正为 0 (不乱调价)."""
        corrector = PriceCorrector()
        recall = {"similar_won": [], "similar_lost": [], "price_band": {},
                  "sample_count": 0, "confidence": 0.0}
        result = corrector.correct({"final_price": 100}, recall, "T")
        assert result.correction_pct == 0.0
        assert result.corrected_price == 100


# ========== 反应打标 ==========

class TestReactionLabeling:
    def test_pending_immediate(self):
        import time as _t
        labeler = ReactionLabeler()
        now = _t.time()
        result = labeler.label({}, quote_sent_at=now, now=now)
        assert result.reaction == Reaction.PENDING.value

    def test_won_on_payment(self):
        import time as _t
        labeler = ReactionLabeler()
        now = _t.time()
        result = labeler.label({}, quote_sent_at=now - 100,
                               payment_at=now, now=now)
        assert result.reaction == Reaction.WON.value
        assert result.confidence == 1.0

    def test_lost_on_reject(self):
        labeler = ReactionLabeler()
        result = labeler.label({}, explicit_reject=True)
        assert result.reaction == Reaction.LOST.value

    def test_silent_after_threshold(self):
        import time as _t
        labeler = ReactionLabeler(silent_days=5)
        now = _t.time()
        result = labeler.label({}, quote_sent_at=now - 10 * 86400, now=now)
        assert result.reaction == Reaction.SILENT.value

    def test_vacation_exempt(self):
        """休假豁免: 不判 silent."""
        import time as _t
        labeler = ReactionLabeler(silent_days=5)
        now = _t.time()
        result = labeler.label({},
                               quote_sent_at=now - 10 * 86400,
                               vacation_until=now + 30 * 86400,
                               now=now)
        assert result.vacation_exempt is True
        assert result.reaction == Reaction.PENDING.value

    def test_reacting_on_reply(self):
        import time as _t
        labeler = ReactionLabeler()
        now = _t.time()
        result = labeler.label({}, quote_sent_at=now - 86400,
                               customer_reply_at=now - 3600, now=now)
        assert result.reaction == Reaction.REACTING.value


# ========== 飞轮闭环 ==========

class TestFeedbackLoop:
    def test_full_loop_index_then_recall(self, flywheel):
        """索引 → 召回 → 修正 全闭环."""
        # 先索引 3 笔同租户成交
        base_ctx = {
            "customer": {"customer_id": "LOOPCO"},
            "rfq": {"material": "304", "surface": "passivate", "quantity": 200,
                    "tolerance_grade": "IT8", "process": "CNC"},
        }
        for i, price in enumerate([4000, 4500, 4200], start=1):
            ctx = {
                **base_ctx,
                "context_id": f"RFQ-LOOP-{i}",
                "commercial": {"quote": {"final_price": price, "margin_pct": 22}},
            }
            flywheel.post_quote(ctx, reaction="won")

        # 同租户新询盘 → 召回 + 修正
        new_ctx = {
            "customer": {"customer_id": "LOOPCO"},
            "rfq": {"material": "304", "surface": "passivate", "quantity": 200,
                    "tolerance_grade": "IT8", "process": "CNC"},
            "commercial": {"quote": {"final_price": 3000, "margin_pct": 15}},
        }
        advice = flywheel.before_quote(new_ctx)

        assert advice["recall"]["sample_count"] == 3
        assert not advice["recall"]["_cold_start"]
        assert advice["correction"]["base_price"] == 3000
        # 3 样本 → COLD tier → cap 5%
        assert advice["correction"]["tier"] == "cold"
        assert advice["correction"]["cap_pct"] == 0.05

    def test_cross_tenant_never_leak(self, flywheel):
        """沙箱回归: A 的 context 只能被 A 召回, B 同理."""
        for tenant in ["AAA", "BBB"]:
            for i in range(3):
                ctx = {
                    "context_id": f"RFQ-{tenant}-{i}",
                    "customer": {"customer_id": tenant},
                    "rfq": {"material": "6061", "surface": "anodize", "quantity": 100},
                    "commercial": {"quote": {"final_price": 5000 + i * 100}},
                }
                flywheel.post_quote(ctx, reaction="won")

        scope_a = TenantScope(tenant_id="AAA")
        scope_b = TenantScope(tenant_id="BBB")
        probe = {"rfq": {"material": "6061", "surface": "anodize", "quantity": 100}}

        ra = flywheel.recall.before_quote(scope_a, probe)
        rb = flywheel.recall.before_quote(scope_b, probe)

        # 检查 context_id 归属 (而非价格, 因为两租户可能报价相近)
        a_ctxs = {h["payload"]["context_id"] for h in ra["similar_won"]}
        b_ctxs = {h["payload"]["context_id"] for h in rb["similar_won"]}
        assert all("AAA" in c for c in a_ctxs), f"A 召回了非 AAA: {a_ctxs}"
        assert all("BBB" in c for c in b_ctxs), f"B 召回了非 BBB: {b_ctxs}"
        assert not (a_ctxs & b_ctxs), "租户隔离失败: context_id 交叉"

    def test_stats(self, flywheel):
        ctx = {"context_id": "RFQ-S1", "customer": {"customer_id": "STATCO"},
               "rfq": {"material": "7075"}, "commercial": {"quote": {"final_price": 100}}}
        flywheel.post_quote(ctx, reaction="won")
        s = flywheel.stats()
        assert s["backend"] == "memory"
        assert s["total_collections"] >= 1
        assert s["tenant_collections"] >= 1
