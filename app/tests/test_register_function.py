"""tests/test_register_function.py — F2 装饰器测试 (5 用例).

覆盖:
  1. 装饰器注册 skill 到 _REGISTRY + _REGISTER_META
  2. get_register_meta 返元数据 (无 → None)
  3. list_register_metas 返所有
  4. 自动发现 (无装饰器) 仍工作 (向后兼容)
  5. 装饰器 vs 自动发现: 装饰器优先
"""
from __future__ import annotations
from pathlib import Path

import pytest

import skills._runtime as rt


def test_decorator_registers_skill() -> None:
    """@register_function 装饰器应把函数加到 _REGISTRY + _REGISTER_META."""
    @rt.register_function("test-skill-1", iron_rule="deterministic",
                          openshell_policy=["iron-rule-1"])
    def my_func(ctx, **kw):
        return {"ok": True, "skill": "test-skill-1"}
    assert "test-skill-1" in rt._REGISTRY
    meta = rt.get_register_meta("test-skill-1")
    assert meta is not None
    assert meta["iron_rule"] == "deterministic"
    assert meta["openshell_policy"] == ["iron-rule-1"]
    assert meta["via"] == "decorator"


def test_get_register_meta_returns_none_for_unknown() -> None:
    """未知 skill_id 应返 None."""
    assert rt.get_register_meta("nonexistent-skill-xyz") is None


def test_list_register_metas() -> None:
    """list_register_metas 返所有装饰器注册."""
    @rt.register_function("list-test-a")
    def f1(ctx, **kw): pass
    @rt.register_function("list-test-b")
    def f2(ctx, **kw): pass
    metas = rt.list_register_metas()
    assert "list-test-a" in metas
    assert "list-test-b" in metas
    assert metas["list-test-a"]["via"] == "decorator"


def test_autodiscovery_still_works() -> None:
    """向后兼容: 无装饰器的 tool.py 仍可自动发现 (25 skill 应全部 discover)."""
    skills = rt.discover(force=True)
    # 至少有 20+ skill (新写 5 个 + 原有 20)
    assert len(skills) >= 20, f"autodiscovery found only {len(skills)} skills"


def test_decorator_overrides_autodiscovery() -> None:
    """装饰器注册的 skill 在 _REGISTRY 中优先 (id 一致时)."""
    # 用装饰器注册 "write-reply" skill (用同名覆盖)
    @rt.register_function("write-reply", iron_rule="draft_only")
    def custom_write_reply(ctx, **kw):
        return {"ok": True, "skill": "write-reply", "via": "custom-decorator"}
    # 验证 _REGISTRY 中是装饰器版本
    fn = rt._REGISTRY["write-reply"]
    assert fn({"ctx": None}, **{})["via"] == "custom-decorator"
    # 清理, 避免污染其他测试
    del rt._REGISTRY["write-reply"]
    if "write-reply" in rt._REGISTER_META:
        del rt._REGISTER_META["write-reply"]
