"""services/config_reload.py — D-P0.3 配置热载 (mtime 缓存 + 校验 rollback).

HotConfig: 基于文件 mtime 的缓存配置。文件未变 → 不重复 parse; 文件变更 →
下次 get() 自动热载 (无需重启)。热载时跑 validator: 校验失败或解析异常 →
保留上一份有效配置 (safe rollback) + 记录 last_error, 绝不静默采用坏配置。

铁律①: skills.yaml 热载经 skill_config.validate, iron-rule-1 不可被热载关闭。

集成为 opt-in: 既有 config.load_settings()/skill_config.load() 默认行为不变
(每次读盘), 调用方可改用 hot_settings()/hot_skills() 单例获得热载 + 缓存。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent


def _default_loader(path: Path | str) -> Dict[str, Any]:
    p = Path(path)
    txt = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        import yaml  # type: ignore
        return yaml.safe_load(txt) or {}
    return json.loads(txt)


class HotConfig:
    """mtime 缓存 + 校验 rollback 的热载配置。"""

    def __init__(self, path: Path | str,
                 loader: Optional[Callable[[Any], Dict[str, Any]]] = None,
                 validator: Optional[Callable[[Dict[str, Any]], List[str]]] = None):
        self.path = Path(path)
        self._loader = loader or _default_loader
        self._validator = validator
        self._mtime: Optional[float] = None
        self._value: Optional[Dict[str, Any]] = None
        self._last_error: List[str] = []
        self.reload_count = 0

    @property
    def last_error(self) -> List[str]:
        return list(self._last_error)

    @property
    def last_valid(self) -> Optional[Dict[str, Any]]:
        return self._value

    def get(self) -> Optional[Dict[str, Any]]:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            # 文件消失 → 保留上一份有效, 不崩
            if self._value is None:
                self._last_error = [f"config not found: {self.path}"]
            return self._value

        if self._value is not None and mtime == self._mtime:
            return self._value  # 缓存命中

        # 需要 (重)载
        self.reload_count += 1
        try:
            parsed = self._loader(self.path)
        except Exception as e:
            self._last_error = [f"parse error: {e!r}"]
            self._mtime = mtime
            log.warning("[hot-config] parse failed %s → rollback: %r", self.path.name, e)
            return self._value

        if self._validator is not None:
            try:
                errs = list(self._validator(parsed) or [])
            except Exception as e:
                errs = [f"validator error: {e!r}"]
            if errs:
                self._last_error = errs
                self._mtime = mtime
                log.warning("[hot-config] invalid %s → rollback: %s", self.path.name, errs)
                return self._value

        self._value = parsed
        self._last_error = []
        self._mtime = mtime
        return self._value


# ---- opt-in 单例 ----
_singletons: Dict[str, HotConfig] = {}


def hot_settings(root: Optional[Path | str] = None) -> HotConfig:
    r = Path(root) if root else _ROOT
    key = f"settings:{r}"
    if key not in _singletons:
        _singletons[key] = HotConfig(r / "config" / "settings.yaml")
    return _singletons[key]


def hot_skills(root: Optional[Path | str] = None) -> HotConfig:
    r = Path(root) if root else _ROOT
    key = f"skills:{r}"
    if key not in _singletons:
        from services.skill_config import validate
        _singletons[key] = HotConfig(r / "config" / "skills.yaml", validator=validate)
    return _singletons[key]


def reload_all() -> Dict[str, Any]:
    """强制重读所有单例 (返回各自当前值/错误), 用于 /reload 类触发。"""
    out: Dict[str, Any] = {}
    for key, hc in _singletons.items():
        val = hc.get()
        out[key] = {"ok": not hc.last_error, "last_error": hc.last_error,
                    "reload_count": hc.reload_count}
    return out


def reset_singletons() -> None:
    _singletons.clear()
