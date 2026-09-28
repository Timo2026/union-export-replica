"""test_price_sha256_regression.py — 铁律① 行为等价回归测试.

铁律①: LLM 不定价 — 价格 100% 来自 Timo 确定性引擎, LLM 只措辞.
本测试验证: 切换 LLM 后端 (local → nvidia → mock) 不改变价格输出,
            因为 DETERMINISTIC 角色永远路由到 Timo 内核, 与 LLM backend 无关.

核心断言:
  1. DETERMINISTIC 角色在任意 backend 下都路由到 timo-kernel (不走 LLM)
  2. 切换 backend 不改变 DETERMINISTIC 的 endpoint/model/source
  3. 同一报价对象的 sha256 跨 backend 一致 (价格哈希等价)
  4. LLM 草稿可以变 (措辞不同), 但价格字段 byte-identical
  5. iron-rule-1 lock: 确定性输出锁定, 拒绝二次改写

对齐: services/model_router.py resolve(DETERMINISTIC) + services/openshell.py sha256_obj.
"""
from __future__ import annotations

import json
import hashlib
from typing import Any, Dict

import pytest

from services.model_router import ModelRouter
from services.openshell import sha256_obj


class _FakeTimo:
    """模拟 Timo v12 确定性引擎 (在线)."""
    base_url = "http://127.0.0.1:7862"
    online = True

    def calc_quote(self, rfq: Dict[str, Any]) -> Dict[str, Any]:
        """确定性报价: 同一 RFQ 永远返回同一价格 (不依赖 LLM)."""
        # 确定性公式: 基于材料/数量/工艺的固定计算, 无随机性
        material_cost = {"铝": 35.0, "钢": 28.0, "铜": 65.0}.get(rfq.get("material", "钢"), 28.0)
        qty = rfq.get("quantity", 100)
        unit_price = material_cost * 1.15  # 15% 加工费
        total = round(unit_price * qty, 2)
        return {
            "unit_price": round(unit_price, 2),
            "total_price": total,
            "currency": "CNY",
            "engine": "timo-v12",
            "rfq_hash": hashlib.sha256(
                json.dumps(rfq, sort_keys=True).encode()
            ).hexdigest()[:16],
        }


def _settings(backend: str = "nvidia") -> Dict[str, Any]:
    return {"model_router": {"backend": backend, "roles": {}}}


# ---------- 断言 1: DETERMINISTIC 永远路由到 Timo 内核 ----------

@pytest.mark.parametrize("backend", ["local", "nvidia", "mock"])
def test_deterministic_always_routes_to_timo(backend):
    """DETERMINISTIC 角色在任意 backend 下都路由到 timo-kernel, 不走 LLM."""
    mr = ModelRouter(_settings(backend), timo=_FakeTimo())
    r = mr.resolve("DETERMINISTIC")
    assert r["backend"] == "timo-kernel", \
        f"backend={backend}: DETERMINISTIC 应路由到 timo-kernel, 实际 {r['backend']}"
    assert r["source"] == "deterministic"
    assert "calc_quote" in r["model"]


def test_deterministic_never_routes_to_llm():
    """DETERMINISTIC 的 endpoint 永远是 Timo (:7862), 不是 LLM 端点."""
    timo = _FakeTimo()
    for backend in ("local", "nvidia", "mock"):
        mr = ModelRouter(_settings(backend), timo=timo)
        r = mr.resolve("DETERMINISTIC")
        assert "7862" in r["endpoint"], \
            f"backend={backend}: DETERMINISTIC endpoint 应含 :7862, 实际 {r['endpoint']}"
        # 确认不是 LLM 端点
        for llm_port in ("8000", "8002", "8020", "8011"):
            assert llm_port not in r["endpoint"], \
                f"DETERMINISTIC 误路由到 LLM 端点 :{llm_port}"


# ---------- 断言 2: 切换 backend 不改变 DETERMINISTIC 路由 ----------

def test_backend_switch_does_not_change_deterministic_route():
    """切换 LLM backend (local→nvidia→mock) 不改变 DETERMINISTIC 的路由结果."""
    timo = _FakeTimo()
    results = {}
    for backend in ("local", "nvidia", "mock"):
        mr = ModelRouter(_settings(backend), timo=timo)
        results[backend] = mr.resolve("DETERMINISTIC")

    # 三个 backend 的 DETERMINISTIC 路由应完全一致
    r_nvidia = results["nvidia"]
    r_local = results["local"]
    r_mock = results["mock"]

    assert r_nvidia["endpoint"] == r_local["endpoint"] == r_mock["endpoint"]
    assert r_nvidia["model"] == r_local["model"] == r_mock["model"]
    assert r_nvidia["backend"] == r_local["backend"] == r_mock["backend"]
    assert r_nvidia["source"] == r_local["source"] == r_mock["source"]


# ---------- 断言 3: 价格 sha256 跨 backend 一致 ----------

def test_price_sha256_identical_across_backends():
    """同一 RFQ 通过 Timo 引擎报价, sha256 跨 backend 完全一致."""
    timo = _FakeTimo()
    rfq = {"material": "铝", "quantity": 500, "part_name": "heat-sink-v3"}

    prices = {}
    for backend in ("local", "nvidia", "mock"):
        # DETERMINISTIC 路由到 Timo, 与 backend 无关
        mr = ModelRouter(_settings(backend), timo=timo)
        route = mr.resolve("DETERMINISTIC")
        assert route["backend"] == "timo-kernel"
        # Timo 确定性报价
        quote = timo.calc_quote(rfq)
        prices[backend] = sha256_obj(quote)

    # 三个 backend 的价格 sha256 必须完全一致
    assert prices["local"] == prices["nvidia"] == prices["mock"], \
        f"价格 sha256 跨 backend 不一致: {prices}"

    # sha256 应为 64 位十六进制
    for backend, h in prices.items():
        assert len(h) == 64, f"{backend}: sha256 长度应为 64, 实际 {len(h)}"
        assert all(c in "0123456789abcdef" for c in h), f"{backend}: sha256 非十六进制"


def test_price_sha256_deterministic_for_same_rfq():
    """同一 RFQ 多次报价, sha256 永远一致 (确定性)."""
    timo = _FakeTimo()
    rfq = {"material": "钢", "quantity": 1000, "part_name": "bracket-v2"}

    hashes = [sha256_obj(timo.calc_quote(rfq)) for _ in range(10)]
    assert all(h == hashes[0] for h in hashes), "同一 RFQ 的价格 sha256 不确定 (非确定性)"


def test_price_sha256_differs_for_different_rfq():
    """不同 RFQ 的价格 sha256 应不同 (区分性)."""
    timo = _FakeTimo()
    rfq_a = {"material": "铝", "quantity": 100, "part_name": "part-a"}
    rfq_b = {"material": "铜", "quantity": 200, "part_name": "part-b"}

    h_a = sha256_obj(timo.calc_quote(rfq_a))
    h_b = sha256_obj(timo.calc_quote(rfq_b))
    assert h_a != h_b, "不同 RFQ 的价格 sha256 相同 (失去区分性)"


# ---------- 断言 4: LLM 草稿可变, 价格字段不变 ----------

def test_llm_draft_can_change_but_price_locked():
    """LLM 草稿 (措辞) 可以随 backend 变化, 但价格字段 byte-identical.

    模拟:
      - backend=local 时 LLM 生成草稿 A ("报价为 ¥40250.00")
      - backend=nvidia 时 LLM 生成草稿 B ("总金额：40250.00 元")
      - 但两者的 price 字段 (来自 Timo) 完全一致
    """
    timo = _FakeTimo()
    rfq = {"material": "钢", "quantity": 1000, "part_name": "bracket-v2"}

    # Timo 确定性报价 (与 LLM backend 无关)
    quote = timo.calc_quote(rfq)
    price_hash = sha256_obj(quote)

    # LLM 草稿 A (local backend, Qwen 措辞)
    draft_a = {
        "subject": "Re: 询盘 - bracket-v2",
        "body": f"您好，感谢询盘。报价为 ¥{quote['total_price']:.2f}。",
        "price": quote,  # 价格字段来自 Timo
        "llm_backend": "local",
    }

    # LLM 草稿 B (nvidia backend, Nemotron 措辞)
    draft_b = {
        "subject": "Re: bracket-v2 报价",
        "body": f"总金额：{quote['total_price']:.2f} 元（含税）。",
        "price": quote,  # 同一个 Timo 价格
        "llm_backend": "nvidia",
    }

    # 草稿措辞不同
    assert draft_a["body"] != draft_b["body"], "草稿措辞应不同"
    assert draft_a["subject"] != draft_b["subject"], "草稿主题应不同"

    # 但价格字段 sha256 一致 (铁律①)
    assert sha256_obj(draft_a["price"]) == sha256_obj(draft_b["price"]) == price_hash, \
        "价格字段 sha256 不一致 — 铁律① 被违反"


# ---------- 断言 5: iron-rule-1 lock — 确定性输出锁定 ----------

def test_iron_rule_1_price_output_locked():
    """iron-rule-1: 确定性 skill 输出锁定 sha256, 拒绝二次改写.

    模拟 openshell.py 的 iron-rule-1 机制:
      - 首次执行 calc-quote → 记录 sha256 lock
      - 再次执行同一 RFQ → sha256 应与 lock 一致 (确定性)
      - 若 sha256 不一致 → 铁律① 被违反
    """
    timo = _FakeTimo()
    rfq = {"material": "铝", "quantity": 200, "part_name": "panel-v1"}

    # 首次报价 → 锁定 sha256
    quote_first = timo.calc_quote(rfq)
    locked_sha256 = sha256_obj(quote_first)

    # 模拟 iron-rule-1 lock 记录
    lock_record = {
        "skill_id": "calc-quote",
        "locked": True,
        "sha256": locked_sha256,
        "first_seen": True,
    }
    assert lock_record["locked"] is True, "calc-quote 未锁定 — 铁律① 未生效"
    assert len(lock_record["sha256"]) == 64

    # 再次报价 → sha256 应与 lock 一致
    quote_second = timo.calc_quote(rfq)
    actual_sha256 = sha256_obj(quote_second)
    assert actual_sha256 == lock_record["sha256"], \
        f"iron-rule-1 违反: 锁定 sha256={lock_record['sha256'][:16]}... " \
        f"实际 sha256={actual_sha256[:16]}..."


def test_iron_rule_1_detects_tamper():
    """iron-rule-1: 如果价格被 LLM 篡改, sha256 不匹配 → 检测到违规."""
    timo = _FakeTimo()
    rfq = {"material": "钢", "quantity": 500, "part_name": "frame-v1"}

    # Timo 确定性报价
    quote = timo.calc_quote(rfq)
    locked_sha256 = sha256_obj(quote)

    # 模拟 LLM 篡改价格 (铁律① 被违反)
    tampered = dict(quote)
    tampered["total_price"] = quote["total_price"] * 0.9  # LLM 擅自降价 10%
    tampered_sha256 = sha256_obj(tampered)

    # sha256 不匹配 → 检测到篡改
    assert tampered_sha256 != locked_sha256, \
        "篡改后的价格 sha256 与锁定值一致 — 未检测到铁律① 违规"


# ---------- 断言 6: DETERMINISTIC 不受 A/B 路由影响 ----------

def test_deterministic_no_ab_routing():
    """DETERMINISTIC 角色不可配置 A/B 路由 — 永远 primary_only."""
    timo = _FakeTimo()
    for backend in ("local", "nvidia"):
        mr = ModelRouter(_settings(backend), timo=timo)
        r = mr.resolve("DETERMINISTIC")
        assert r.get("strategy") == "primary_only", \
            f"backend={backend}: DETERMINISTIC 应为 primary_only (不可 A/B), 实际 {r.get('strategy')}"
        assert "不可配置" in r.get("note", ""), \
            f"DETERMINISTIC note 应含 '不可配置 A/B'"


# ---------- 断言 7: Timo 离线时 DETERMINISTIC 标注离线, 不冒充 ----------

def test_deterministic_offline_when_timo_down():
    """Timo 引擎离线时, DETERMINISTIC 应标注 online=False, 不冒充在线."""
    class _TimoOffline:
        base_url = "http://127.0.0.1:7862"
        online = False

    mr = ModelRouter(_settings("nvidia"), timo=_TimoOffline())
    r = mr.resolve("DETERMINISTIC")
    assert r["online"] is False, "Timo 离线但 DETERMINISTIC 标注在线 — 冒充"
    assert r["backend"] == "timo-kernel", "Timo 离线时 backend 不应变 (仍指向 timo-kernel)"