# -*- coding: utf-8 -*-
"""模型后端路由 — 根据硬件 vendor 自动选择匹配的推理后端（禁止硬编码）。

职责：
- 读取 config/models.json（cloud / local / models 三处）合并、去重。
- 解析 ${VAR} / ${VAR:-default} 环境变量占位符（端口/地址配置驱动）。
- 根据探测到的 vendor 路由：vendor 精确匹配 > 硬件无关(any) > 其它 vendor 模型。
- 保持原有"多级降级链"语义：同组内按 preference(local/cloud) + quality_score 排序。

用法：
    from src.core.environment_detector import EnvironmentDetector
    from src.core.model_auto_loader import ModelAutoLoader

    profile = EnvironmentDetector(proj_root).detect()["hardware_profile"]
    loader = ModelAutoLoader(proj_root / "config" / "models.json", hardware_profile=profile)
    chain = loader.route()          # 路由后的模型列表（降级链）
    models = loader.load()          # 兼容旧占位 API，等价 route()
"""
import os, json, re
from pathlib import Path

from src.core.environment_detector import normalize_vendor

__all__ = ["ModelAutoLoader", "resolve_env_placeholders"]

# ${VAR} 与 ${VAR:-default} 占位符
_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def resolve_env_placeholders(value):
    """递归解析结构中的 ${VAR} 与 ${VAR:-default} 占位符（禁止硬编码：配置 + 环境变量驱动）。

    - ${VAR}         → 环境变量值；不存在则保留原文（交由上层缺省处理）。
    - ${VAR:-default} → 环境变量值；不存在则使用 default。
    支持 str / dict / list 递归。
    """
    if isinstance(value, str):
        def _sub(match):
            key, default = match.group(1), match.group(2)
            if key in os.environ:
                return os.environ[key]
            return default if default is not None else match.group(0)
        return _PLACEHOLDER_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: resolve_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_env_placeholders(v) for v in value]
    return value


class ModelAutoLoader:
    def __init__(self, config_path=None, hardware_profile=None):
        """config_path: config/models.json 路径；hardware_profile: detector 输出的 hardware_profile。"""
        self.config_path = config_path
        self.hardware_profile = dict(hardware_profile or {})
        self._data = {}
        self._loaded = False
        if config_path is not None:
            self._load(config_path)

    # ── 配置加载 ──
    def _load(self, config_path):
        p = None
        if isinstance(config_path, (str, Path)):
            path = Path(config_path)
            if path.exists():
                p = path
        if p is None:
            return
        try:
            self._data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            self._data = {}
        if not isinstance(self._data, dict):
            self._data = {}
        self._loaded = True

    @property
    def vendor(self):
        """当前硬件 vendor（nvidia/amd/musa/cpu/unknown）。"""
        return normalize_vendor(self.hardware_profile.get("vendor")) if self.hardware_profile else "unknown"

    def _iter_models(self):
        """合并 config 的 cloud / local / models 三处模型，去重，解析占位符，补齐 source/vendor。"""
        seen, out = set(), []

        def _add(m, default_source=None):
            if not isinstance(m, dict):
                return
            name = m.get("name") or m.get("model_id") or ""
            if not name or name in seen:
                return
            seen.add(name)
            m2 = resolve_env_placeholders(dict(m))
            m2.setdefault("name", name)
            if not m2.get("source") and default_source:
                m2["source"] = default_source
            if not m2.get("vendor"):
                m2["vendor"] = "any"  # 未标注 vendor 的模型视为硬件无关
            out.append(m2)

        for m in self._data.get("cloud", []):
            _add(m, default_source="cloud")
        for m in self._data.get("local", []):
            _add(m, default_source="local")
        for m in self._data.get("models", []):
            _add(m)  # 扁平 models 数组自带 source
        return out

    def route(self, vendor=None):
        """根据 vendor 返回排序后的模型降级链。

        排序键（升序，越小越优先）：
          1. vendor 匹配等级：精确匹配=0 / any(硬件无关)=1 / 其它 vendor=2
          2. preference 来源等级：cloud 偏好下 cloud=0，否则 local=0
          3. -quality_score（分数高者优先）
        因此 vendor 匹配优先于 cloud/local 偏好，最终仍按质量评分择优，保持多级降级语义。
        """
        v = normalize_vendor(vendor) if vendor is not None else self.vendor
        models = list(self._iter_models())
        pref = self._data.get("preference", "local")

        def _vendor_rank(m):
            mv = normalize_vendor(m.get("vendor"))
            if mv == v:
                return 0
            if mv in ("any", "unknown"):
                return 1
            return 2

        def _sort_key(m):
            src = m.get("source", "")
            if pref == "cloud":
                src_rank = 0 if src == "cloud" else 1
            else:
                src_rank = 0 if src == "local" else 1
            return (_vendor_rank(m), src_rank, -int(m.get("quality_score", 0) or 0))

        models.sort(key=_sort_key)
        return models

    def load(self):
        """兼容旧占位桩 API：原本恒返回 []，现改为返回路由后的模型列表。"""
        return self.route()