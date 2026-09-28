"""test_llm_planner.py — LLM Planner (ReAct + 提示工程 + JSON-Schema 绑定) 测试.

用 MockLLM (monkeypatch online()+_post_chat) 做确定性测试, 不依赖 :1234 是否在线;
另含一条 online-conditional 真实测试 (离线自动 skip)。
核心断言: LLM 只"提议", 输出经 JSON 解析 + schema 校验; 离线显式 MOCK 降级; ReAct 受 allow-list 约束。
"""
from __future__ import annotations

import json

import pytest

from services.llm_planner import LLMPlanner, _extract_json, _validate


# ---------------- 纯函数 ----------------
def test_extract_json_variants():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('sure! {"material": "6061"} hope that helps') == {"material": "6061"}
    assert _extract_json('[1,2,3]') == [1, 2, 3]
    assert _extract_json("no json here") is None
    assert _extract_json("") is None


def test_validate_required_and_type():
    schema = {"type": "object", "required": ["material"], "properties": {"material": {"type": "string"}}}
    assert _validate({"material": "6061"}, schema) == []
    errs = _validate({"quantity": 5}, schema)
    assert errs and "material" in errs[0]


# ---------------- MockLLM ----------------
class MockPlanner(LLMPlanner):
    """把 _post_chat 替换为按队列返回的 canned 响应; online 恒 True。"""
    def __init__(self, responses):
        super().__init__(endpoint="http://mock/v1", model="mock-llm", backend="local")
        self._responses = list(responses)
        self._calls = 0

    def online(self):
        return True

    def _post_chat(self, payload):
        # 记录最后一次 payload 供断言 (提示模板/few-shot/response_format)
        self.last_payload = payload
        content = self._responses[min(self._calls, len(self._responses) - 1)]
        self._calls += 1
        return {"model": "mock-llm", "choices": [{"message": {"content": content}}]}


def test_chat_json_parses_and_validates():
    p = MockPlanner(['{"material":"6061","surface":"阳极氧化","quantity":50,"process":"CNC","missing_information":[]}'])
    r = p.extract_rfq("quote 50 pcs 6061 anodizing")
    assert r["ok"] is True and r["_mock"] is False
    assert r["data"]["material"] == "6061" and r["data"]["quantity"] == 50
    # 提示工程: response_format 约束 + 充足 token 预算(推理模型) + few-shot 注入
    assert p.last_payload["response_format"] == {"type": "text"}
    assert p.last_payload["max_tokens"] >= 2000
    roles = [m["role"] for m in p.last_payload["messages"]]
    assert roles.count("assistant") >= 1        # few-shot 示例已注入


def test_chat_json_schema_error_flagged():
    p = MockPlanner(['{"quantity": 5}'])         # 缺 required material
    r = p.extract_rfq("x")
    assert r["ok"] is False and r["schema_errors"]


def test_chat_json_unparseable_falls_back():
    p = MockPlanner(["sorry I cannot output json"])
    r = p.extract_rfq("x")
    assert r["ok"] is False and r["_source"] == "live:parse_failed"


def test_offline_degrades_to_explicit_mock():
    p = LLMPlanner(endpoint="http://127.0.0.1:59997/v1", backend="local")
    assert p.online() is False
    r = p.extract_rfq("quote 6061")
    assert r["_mock"] is True and r["_source"] == "MOCK:llm-offline"


def test_mock_backend_never_calls_network():
    p = LLMPlanner(backend="mock")
    assert p.online() is False and p.source_label() == "MOCK:llm-planner"


# ---------------- ReAct 工具选择 ----------------
def test_react_loop_selects_then_finishes():
    responses = [
        '{"thought":"先抽 RFQ","action":{"tool":"rfq-extraction","args":{}}}',
        '{"thought":"做 DFM","action":{"tool":"dfm-conflict","args":{"material":"6061"}}}',
        '{"thought":"信息足够","action":{"tool":"finish","args":{"status":"PASS"}}}',
    ]
    p = MockPlanner(responses)
    executed = []

    def execute(tool, args):
        executed.append(tool)
        return {"ok": True, "tool": tool}

    allowed = {"rfq-extraction", "dfm-conflict", "cnc-quote", "finish"}
    out = p.react_loop("STRUCTURING", lambda h: "summary", execute, allowed, max_steps=6)
    assert out["ok"] and out["_mock"] is False
    assert executed == ["rfq-extraction", "dfm-conflict"]      # finish 不执行工具
    assert out["finish"]["status"] == "PASS"
    assert len(out["trace"]) == 3


def test_react_loop_blocks_tool_outside_allowlist():
    responses = [
        '{"thought":"越权","action":{"tool":"rm-rf","args":{}}}',
        '{"thought":"结束","action":{"tool":"finish","args":{"status":"HITL"}}}',
    ]
    p = MockPlanner(responses)
    executed = []
    out = p.react_loop("DFM", lambda h: "s", lambda t, a: executed.append(t) or {},
                       {"dfm-conflict", "finish"}, max_steps=5)
    assert "rm-rf" not in executed                              # 越权工具未执行
    assert any("BLOCKED by allow-list" in str(s.get("observation", "")) for s in out["trace"])


def test_react_loop_offline_uses_fallback_sequence():
    p = LLMPlanner(endpoint="http://127.0.0.1:59997/v1")
    executed = []
    out = p.react_loop("NEW", lambda h: "s", lambda t, a: executed.append(t) or {},
                       {"rfq-extraction", "dfm-conflict"},
                       fallback_sequence=["rfq-extraction", "dfm-conflict"])
    assert out["_mock"] is True
    assert executed == ["rfq-extraction", "dfm-conflict"]       # 离线确定性回退


def test_summarize_and_translate_shapes():
    p = MockPlanner(['{"summary":"s","key_points":["a"],"open_questions":[],"risks":[]}'])
    r = p.summarize("need 50 pcs 6061")
    assert r["ok"] and r["data"]["summary"] == "s"
    p2 = MockPlanner(['{"translated":"Please quote 50 pcs","target_lang":"en"}'])
    r2 = p2.translate("请报50件", "en")
    assert r2["ok"] and r2["data"]["target_lang"] == "en"


# ---------------- 在线条件测试 (离线自动 skip) ----------------
def test_live_extract_rfq_if_online():
    p = LLMPlanner()
    if not p.online():
        pytest.skip("LLM :1234 离线, 跳过真实调用")
    r = p.extract_rfq("Please quote 50 pcs 6061 aluminum brackets, anodizing, IT7.")
    src = str(r.get("_source", ""))
    if "llm failed" in src:
        # :1234 活着但模型未驻留 (LM Studio 按需加载失败/进行中) = 环境态, 非代码回归
        pytest.skip(f"模型未就绪, 跳过真实调用: {src[:80]}")
    assert r["_mock"] is False
    assert r["data"].get("material") in ("6061", None)
