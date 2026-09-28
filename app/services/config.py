"""config.py — 配置加载 (禁止硬编码, 全部从 YAML 读取)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "需要 PyYAML: 请 `python -m pip install pyyaml`") from e


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """overlay 覆盖 base; 两侧同为 dict 的键递归合并, 其余直接替换.

    profile 文件只需写增量, 不必复制整份 settings.yaml。
    """
    out = dict(base)
    for k, v in (overlay or {}).items():
        cur = out.get(k)
        if isinstance(cur, dict) and isinstance(v, dict):
            out[k] = _deep_merge(cur, v)
        else:
            out[k] = v
    return out


def active_profile(root: Path | str | None = None) -> str:
    """当前 profile: UEA_PROFILE 环境变量 > settings.yaml 的 profile 键 > "demo".

    profile 决定是否叠加 config/settings.<profile>.yaml (如 dgx-spark-p0)。
    """
    env = (os.environ.get("UEA_PROFILE") or "").strip()
    if env:
        return env
    try:
        return str(load_settings(root).get("profile") or "demo")
    except Exception:
        return "demo"


def load_settings(root: Path | str | None = None) -> Dict[str, Any]:
    """读 config/settings.yaml, 再按 active_profile 叠加 config/settings.<profile>.yaml。

    profile 文件不存在 → 原样返回 base (demo profile 不改变既有行为)。
    """
    root = Path(root) if root else _ROOT
    base = _load_yaml(root / "config" / "settings.yaml")
    profile = (os.environ.get("UEA_PROFILE") or "").strip() or str(base.get("profile") or "").strip()
    if not profile or profile == "demo":
        return base
    overlay_path = root / "config" / f"settings.{profile}.yaml"
    if not overlay_path.exists():
        return base
    merged = _deep_merge(base, _load_yaml(overlay_path))
    merged["profile"] = profile
    merged["_profile_file"] = str(overlay_path.relative_to(root))
    return merged


def load_policy(root: Path | str | None = None) -> Dict[str, Any]:
    root = Path(root) if root else _ROOT
    return _load_yaml(root / "config" / "policy.yaml")


def load_commercial(root: Path | str | None = None) -> Dict[str, Any]:
    root = Path(root) if root else _ROOT
    return _load_yaml(root / "config" / "commercial.yaml")


def target_margin_pct(fallback: float = 25.0) -> float:
    """基础目标毛利单源 (E1-d): settings.yaml pricing.target_margin_pct。

    配置缺失/损坏时显式回退 fallback, 不抛断报价链路。
    """
    try:
        s = load_settings()
        return float((s.get("pricing") or {}).get("target_margin_pct", fallback))
    except Exception:
        return fallback
