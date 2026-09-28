"""tests/test_config_reload.py — D-P0.3 配置热载 (mtime 缓存 + 校验 rollback).

覆盖:
  - 缓存命中: 文件未变 → loader 只调一次
  - mtime 变更 → 热载新内容 (无需重启)
  - 坏配置 → 保留上一份有效配置 (safe rollback) + 记录 last_error, 不崩
  - validator 接入 (skill_config.validate 风格)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest


def _bump_mtime(path: Path, offset: float = 10.0) -> None:
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + offset))


def test_cache_hit_no_reread(tmp_path: Path):
    from services.config_reload import HotConfig
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"a": 1}), encoding="utf-8")
    calls = []

    def loader(path):
        calls.append(str(path))
        return json.loads(Path(path).read_text(encoding="utf-8"))

    hc = HotConfig(p, loader=loader)
    v1 = hc.get()
    v2 = hc.get()
    assert v1 == {"a": 1}
    assert v2 == {"a": 1}
    assert len(calls) == 1, "未变文件不应重复 parse"
    assert hc.reload_count == 1


def test_mtime_change_triggers_reload(tmp_path: Path):
    from services.config_reload import HotConfig
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"a": 1}), encoding="utf-8")
    hc = HotConfig(p, loader=lambda path: json.loads(Path(path).read_text(encoding="utf-8")))
    assert hc.get() == {"a": 1}
    p.write_text(json.dumps({"a": 2, "b": 3}), encoding="utf-8")
    _bump_mtime(p)
    v = hc.get()
    assert v == {"a": 2, "b": 3}
    assert hc.reload_count == 2


def test_invalid_config_rollback(tmp_path: Path):
    """坏配置 → 保留上一份有效, 记录 last_error, 不抛。"""
    from services.config_reload import HotConfig
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"a": 1}), encoding="utf-8")

    def validator(cfg):
        errs = []
        if "a" not in cfg:
            errs.append("missing key 'a'")
        return errs

    hc = HotConfig(p, loader=lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
                   validator=validator)
    assert hc.get() == {"a": 1}
    # 改成缺 'a' 的坏配置
    p.write_text(json.dumps({"zzz": 9}), encoding="utf-8")
    _bump_mtime(p)
    v = hc.get()
    assert v == {"a": 1}, "坏配置应回滚到上一份有效"
    assert hc.last_error, "应记录校验错误"
    assert "missing key" in " ".join(hc.last_error)


def test_parse_error_rollback(tmp_path: Path):
    """解析异常 (非法 JSON) → 保留上一份有效, 不崩。"""
    from services.config_reload import HotConfig
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"a": 1}), encoding="utf-8")
    hc = HotConfig(p, loader=lambda path: json.loads(Path(path).read_text(encoding="utf-8")))
    assert hc.get() == {"a": 1}
    p.write_text("{ this is not json", encoding="utf-8")
    _bump_mtime(p)
    assert hc.get() == {"a": 1}
    assert hc.last_error


def test_skill_validator_integration(tmp_path: Path):
    """接 skill_config.validate: iron-rule-1 被禁 → 拒绝热载, 保留上一份。"""
    from services.config_reload import HotConfig
    from services.skill_config import default_config, validate
    good = default_config()
    p = tmp_path / "skills.json"
    p.write_text(json.dumps(good), encoding="utf-8")
    hc = HotConfig(p, loader=lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
                   validator=validate)
    assert hc.get()["openshell"]["iron-rule-1"]["locked"] is True
    # 坏配置: 关掉 iron-rule-1
    bad = json.loads(json.dumps(good))
    bad["openshell"]["iron-rule-1"]["enabled"] = False
    p.write_text(json.dumps(bad), encoding="utf-8")
    _bump_mtime(p)
    v = hc.get()
    assert v["openshell"]["iron-rule-1"]["enabled"] is True, "铁律①不可被热载关闭"
    assert hc.last_error
