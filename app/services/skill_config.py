"""skill_config.py — v3.0.0 Skill/Dispatcher/OpenShell 配置读写.

读写 config/skills.yaml。铁律①: openshell.iron-rule-1.locked 强制 true,
skills 中 iron_rule=deterministic 的项不可在保存时被改成 enabled=false 且无审计说明
(允许禁用非关键 skill, 但 iron-rule 策略本身不可关)。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_YAML = _ROOT / "config" / "skills.yaml"

_LOCKED_POLICY = "iron-rule-1"
_KNOWN_STRATEGIES = ("auto", "rules_only", "llm")


def _load_yaml(path: Path) -> Dict[str, Any]:
    import yaml  # type: ignore
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    p = Path(path) if path else _SKILLS_YAML
    if not p.exists():
        return default_config()
    return _load_yaml(p)


def default_config() -> Dict[str, Any]:
    return {
        "version": 3,
        "dispatcher": {"strategy": "auto", "llm_role": "llm",
                       "fallback_rules": True, "max_skills_per_task": 8, "audit_max": 50},
        "skills": {},
        "openshell": {
            _LOCKED_POLICY: {"enabled": True, "locked": True},
            "hitl-required": {"enabled": True, "locked": False},
            "local-only": {"enabled": True, "locked": False},
            "skill-allowlist": {"enabled": True, "locked": False},
        },
        "model_router": {"source": "models_yaml"},
    }


def validate(cfg: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    disp = cfg.get("dispatcher") or {}
    strat = disp.get("strategy", "auto")
    if strat not in _KNOWN_STRATEGIES:
        errs.append(f"dispatcher.strategy 必须是 {_KNOWN_STRATEGIES}")
    skills = cfg.get("skills")
    if skills is not None and not isinstance(skills, dict):
        errs.append("skills 必须是对象")
    os_cfg = cfg.get("openshell") or {}
    if not isinstance(os_cfg, dict):
        errs.append("openshell 必须是对象")
    else:
        locked = os_cfg.get(_LOCKED_POLICY) or {}
        if not locked.get("enabled", True):
            errs.append("openshell.iron-rule-1 不可禁用 (铁律①)")
        if locked.get("locked") is False:
            errs.append("openshell.iron-rule-1.locked 必须为 true")
    return errs


def save(cfg: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    import yaml  # type: ignore
    p = Path(path) if path else _SKILLS_YAML
    errs = validate(cfg)
    if errs:
        raise ValueError(f"invalid skills config: {errs}")
    cfg = dict(cfg)
    cfg["version"] = 3
    cfg["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # 强制铁律①
    os_cfg = dict(cfg.get("openshell") or {})
    iron = dict(os_cfg.get(_LOCKED_POLICY) or {})
    iron["enabled"] = True
    iron["locked"] = True
    os_cfg[_LOCKED_POLICY] = iron
    cfg["openshell"] = os_cfg
    p.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8")
    return cfg


def skill_enabled(cfg: Optional[Dict[str, Any]], skill_id: str) -> bool:
    cfg = cfg or load()
    s = (cfg.get("skills") or {}).get(skill_id)
    if s is None:
        return True
    return bool(s.get("enabled", True))


def policy_enabled(cfg: Optional[Dict[str, Any]], policy_id: str) -> bool:
    cfg = cfg or load()
    p = (cfg.get("openshell") or {}).get(policy_id)
    if p is None:
        return policy_id != _LOCKED_POLICY  # iron 默认开; 其它默认开
    return bool(p.get("enabled", True))


def dispatcher_strategy(cfg: Optional[Dict[str,Any]] = None) -> str:
    cfg = cfg or load()
    return str((cfg.get("dispatcher") or {}).get("strategy", "auto"))


def summary(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """供 UI 设置面板: skills + openshell + dispatcher + iron lock 状态."""
    cfg = cfg or load()
    skills = []
    for sid, meta in (cfg.get("skills") or {}).items():
        skills.append({
            "id": sid,
            "label": meta.get("label", sid),
            "description": meta.get("description", ""),
            "enabled": bool(meta.get("enabled", True)),
            "iron_rule": meta.get("iron_rule", ""),
            "openshell": meta.get("openshell") or [],
        })
    policies = []
    for pid, meta in (cfg.get("openshell") or {}).items():
        policies.append({
            "id": pid,
            "enabled": bool(meta.get("enabled", True)),
            "locked": bool(meta.get("locked", False)),
        })
    return {
        "version": cfg.get("version", 3),
        "updated_at": cfg.get("updated_at"),
        "dispatcher": cfg.get("dispatcher") or {},
        "model_router": cfg.get("model_router") or {},
        "skills": skills,
        "openshell": policies,
        "iron_rule_1_locked": True,
    }
