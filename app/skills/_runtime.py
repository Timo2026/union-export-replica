"""skill_runtime.py — Skill 执行运行时 (NemoClaw 兼容最小实现).

每个 Skill 目录可含:
  SKILL.md   — YAML frontmatter (name/description/iron_rule/openshell_policy)
  tool.py    — def run(ctx, **kwargs) -> dict

本模块负责:
  - 发现 skills/*/tool.py 并注册
  - SkillContext (controller/planner/timo 注入)
  - 统一调用入口 execute(skill_id, args, ctx)
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SKILLS_DIR = _ROOT / "skills"


@dataclass
class SkillContext:
    """跨 Skill 共享上下文 (非业务 RFQ context)."""
    ctrl: Any = None
    planner: Any = None
    timo: Any = None
    funasr: Any = None
    policy: Dict[str, Any] = field(default_factory=dict)
    settings: Dict[str, Any] = field(default_factory=dict)
    dispatch_id: str = ""
    # 黄金链中间产物在 dispatch 过程中累积
    scratch: Dict[str, Any] = field(default_factory=dict)
    # skills.yaml 配置
    skill_cfg: Dict[str, Any] = field(default_factory=dict)

    def get_ctrl(self):
        if self.ctrl is None:
            from bootstrap import build_controller
            self.ctrl = build_controller()
            self.timo = getattr(self.ctrl, "timo", None)
            self.planner = getattr(self.ctrl, "planner", None)
            self.policy = getattr(self.ctrl, "policy", {}) or {}
            self.settings = getattr(self.ctrl, "settings", {}) or {}
        return self.ctrl


# skill_id → run 函数
_REGISTRY: Dict[str, Callable[..., Dict[str, Any]]] = {}
# folder name → skill_id
_FOLDER_TO_ID: Dict[str, str] = {}
# 装饰器元数据 (skill_id → {iron_rule, openshell_policy, registered_at})
_REGISTER_META: Dict[str, Dict[str, Any]] = {}


def register_function(skill_id: str, iron_rule: str = "llm_proposal",
                     openshell_policy: Optional[List[str]] = None):
    """装饰器: 标记 tool.py:run 为已注册 skill (对齐 NeMo Agent Toolkit @register_function).

    用法 (可选, 自动发现已足够):
        from skills._runtime import register_function

        @register_function("calc-quote", iron_rule="deterministic",
                          openshell_policy=["iron-rule-1", "hitl-required"])
        def run(ctx, material="6061", quantity=1, **kw):
            ...
    """
    def decorator(func: Callable[..., Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
        _REGISTRY[skill_id] = func
        _REGISTER_META[skill_id] = {
            "iron_rule": iron_rule,
            "openshell_policy": list(openshell_policy or []),
            "registered_at": time.time(),
            "via": "decorator",
        }
        log.debug("[_runtime] @register_function sid=%s iron=%s", skill_id, iron_rule)
        return func
    return decorator


def get_register_meta(skill_id: str) -> Optional[Dict[str, Any]]:
    """返 skill 的装饰器元数据 (无则 None — 走自动发现, meta 字段空).

    v6.1.0 BUG-4 修复: hyphen/underscore 双轨归一 (装饰器可能用任一形式注册)。
    """
    for k in (skill_id, skill_id.replace("-", "_"), skill_id.replace("_", "-")):
        m = _REGISTER_META.get(k)
        if m:
            return m
    return None


def list_register_metas() -> Dict[str, Dict[str, Any]]:
    """所有装饰器注册的 skill 元数据."""
    return dict(_REGISTER_META)


def _load_tool(folder: Path) -> Optional[Callable[..., Dict[str, Any]]]:
    tool_py = folder / "tool.py"
    if not tool_py.exists():
        return None
    mod_name = f"skills_runtime_{folder.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(mod_name, tool_py)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    run = getattr(mod, "run", None)
    if not callable(run):
        return None
    sid = _folder_to_skill_id(folder.name)
    # v6.1.0 BUG-4 修复: 装饰器可能以 hyphen id 注册同一函数 — 把 meta 归并到 canonical underscore id
    for key, fn0 in list(_REGISTRY.items()):
        if fn0 is run and key != sid:
            meta = _REGISTER_META.get(key)
            if meta and sid not in _REGISTER_META:
                _REGISTER_META[sid] = {**meta, "alias_of": key}
            break
    # 装饰器已注册 (via register_function): 直接返
    if sid in _REGISTRY and _REGISTRY[sid] is run:
        return run
    # 否则: 自动注册 (无装饰器)
    _REGISTRY[sid] = run
    return run


def _folder_to_skill_id(folder_name: str) -> str:
    return folder_name.replace("-", "_")


def discover(force: bool = False) -> Dict[str, Callable[..., Dict[str, Any]]]:
    global _REGISTRY, _FOLDER_TO_ID
    if _REGISTRY and not force:
        return _REGISTRY
    _REGISTRY = {}
    _FOLDER_TO_ID = {}
    if not _SKILLS_DIR.exists():
        return _REGISTRY
    for folder in sorted(_SKILLS_DIR.iterdir()):
        if not folder.is_dir() or folder.name.startswith("_") or folder.name.startswith("."):
            continue
        run = _load_tool(folder)
        if run is None:
            continue
        sid = _folder_to_skill_id(folder.name)
        _REGISTRY[sid] = run
        _FOLDER_TO_ID[folder.name] = sid
        # 兼容: 也按 SKILL.md name 注册
        skill_md = folder / "SKILL.md"
        if skill_md.exists():
            try:
                import re
                import yaml  # type: ignore
                m = re.match(r"^---\s*\n(.*?)\n---", skill_md.read_text(encoding="utf-8"), re.S)
                if m:
                    fm = yaml.safe_load(m.group(1)) or {}
                    name = fm.get("name")
                    if name:
                        _FOLDER_TO_ID[name] = sid
                        if name not in _REGISTRY:
                            _REGISTRY[name] = run
            except Exception:
                pass
    return _REGISTRY


def resolve_id(name: str) -> Optional[str]:
    discover()
    if name in _REGISTRY:
        # prefer canonical underscore id
        if name in _FOLDER_TO_ID:
            return _FOLDER_TO_ID[name]
        return name.replace("-", "_") if name.replace("-", "_") in _REGISTRY else name
    alt = name.replace("-", "_")
    if alt in _REGISTRY:
        return alt
    alt2 = name.replace("_", "-")
    return _FOLDER_TO_ID.get(alt2)


def execute(skill_id: str, args: Optional[Dict[str, Any]] = None,
            ctx: Optional[SkillContext] = None, use_cache: bool = True) -> Dict[str, Any]:
    """执行单个 Skill, 返回统一 envelope.

    use_cache=True (默认): 先查 AgentCache, 命中直接返 (省 LLM token).
    use_cache=False: 强制重跑 (跳过缓存).
    """
    reg = discover()
    sid = resolve_id(skill_id) or skill_id
    fn = reg.get(sid) or reg.get(skill_id)
    if fn is None:
        return {"ok": False, "skill": skill_id, "error": f"unknown skill: {skill_id}",
                "_source": "skill_runtime"}
    ctx = ctx or SkillContext()
    args = dict(args or {})
    t0 = time.time()

    # v5.1.0 AgentCache: 命中跳 skill run
    cached = None
    if use_cache:
        try:
            from services.agent_cache import get_cache
            cache = get_cache()
            cached = cache.get(sid, args)
        except Exception:
            cached = None
        if cached is not None:
            cached["_latency_ms"] = round((time.time() - t0) * 1000, 1)
            cached["_source"] = "agent_cache"
            cached["_cache"] = "hit"  # 直接覆盖 (不要 setdefault, 上次 miss 会写入 "miss")
            log.debug("[_runtime] cache HIT sid=%s", sid)
            return cached

    try:
        out = fn(ctx, **args)
        if not isinstance(out, dict):
            out = {"result": out}
        out.setdefault("ok", True)
        out.setdefault("skill", sid)
        out["_latency_ms"] = round((time.time() - t0) * 1000, 1)
        out.setdefault("_source", "skill_runtime")
        # 写入缓存 (仅成功结果, iron-rule=deterministic 可缓存)
        if use_cache and out.get("ok"):
            try:
                from services.agent_cache import get_cache
                cache = get_cache()
                cache.set(sid, args, out)
                out["_cache"] = "miss"
            except Exception:
                pass
        return out
    except TypeError as e:
        # 参数不匹配时给出清晰错误
        return {"ok": False, "skill": sid, "error": f"bad args: {e!r}",
                "_source": "skill_runtime", "_latency_ms": round((time.time() - t0) * 1000, 1)}
    except Exception as e:  # noqa
        return {"ok": False, "skill": sid, "error": repr(e),
                "_source": "skill_runtime", "_latency_ms": round((time.time() - t0) * 1000, 1)}


def list_skills() -> List[Dict[str, Any]]:
    reg = discover()
    from services import skill_config as sc
    cfg = sc.load()
    items = []
    seen = set()
    for sid in sorted(set(list(reg.keys()) + list((cfg.get("skills") or {}).keys()))):
        canon = sid.replace("-", "_")
        if canon in seen and sid != canon:
            continue
        seen.add(canon if sid == canon else sid)
        meta = (cfg.get("skills") or {}).get(canon) or (cfg.get("skills") or {}).get(sid) or {}
        items.append({
            "id": canon,
            "callable": canon in reg or sid in reg,
            "label": meta.get("label", canon),
            "description": meta.get("description", ""),
            "enabled": bool(meta.get("enabled", True)),
            "iron_rule": meta.get("iron_rule", ""),
            "openshell": meta.get("openshell") or [],
        })
    return items


if __name__ == "__main__":
    import json
    print(json.dumps({"skills": list_skills(), "registry": list(discover().keys())},
                     ensure_ascii=False, indent=2))
