# -*- coding: utf-8 -*-
import os, json
from pathlib import Path


def _read_text(p):
    """统一读取文本文件（兼容 str 与 pathlib.Path），UTF-8 编码。

    修复缺陷：原代码调用未定义的 _read_text 导致 NameError 被 except 静默吞掉，
    ModelRegistry._data 永远为空，AI 模型注册完全失效（系统只能降级到规则引擎）。
    """
    return Path(p).read_text(encoding="utf-8")


class ModelRegistry:
    def __init__(self, config_path):
        self.config_path = config_path
        self._data = {}
        if config_path is not None:
            p = config_path
            if hasattr(config_path, "exists") and config_path.exists():
                p = config_path
            elif isinstance(config_path, str) and os.path.exists(config_path):
                p = config_path
            else:
                p = None
            if p is not None:
                try:
                    self._data = json.loads(_read_text(p))
                except Exception:
                    self._data = {}

    def load_cloud_models(self):
        return list(self._data.get("cloud", []))

    def get_all_ranked(self):
        seen = set()
        out = []
        def _add(m, default_source=None):
            if not isinstance(m, dict):
                return
            name = m.get("name") or m.get("model_id") or ""
            if not name or name in seen:
                return
            seen.add(name)
            m2 = dict(m)
            m2.setdefault("name", name)
            if default_source and not m2.get("source"):
                m2["source"] = default_source
            out.append(m2)
        # cloud + local lists first, then the flat "models" array
        for m in self._data.get("cloud", []):
            _add(m, "cloud")
        for m in self._data.get("local", []):
            _add(m, "local")
        for m in self._data.get("models", []):
            _add(m)
        out.sort(key=lambda m: m.get("quality_score", 0), reverse=True)
        return out

    def select_with_fallback(self):
        ranked = self.get_all_ranked()
        pref = self._data.get("preference", "local")
        # order by preference source, then quality score
        def _rank(m):
            src = m.get("source", "")
            if pref == "cloud":
                return (0 if src == "cloud" else 1, -m.get("quality_score", 0))
            return (0 if src == "local" else 1, -m.get("quality_score", 0))
        ranked.sort(key=_rank)
        return ranked
