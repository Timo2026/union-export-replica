"""skill_registry.py — Agent Skills 注册表 (NVIDIA Agent Skills 风格).

解析 skills/*/SKILL.md 的 YAML frontmatter (name/description/version/backend/tool_contract)，
导出 OpenAI function-calling 工具描述，喂给 ReAct Planner 的工具选择，
并与 guardrails.TOOL_ALLOWLIST 交叉校验(注册的技能必须都在 allow-list 内)。

用途: 维度 1.2 标准化工具 / 2.1 Schema绑定 / 2.2 LLM驱动工具选择 / NVIDIA Agent Skills 对齐。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_SKILLS = _ROOT / "skills"

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


def _parse_frontmatter(md: str) -> Dict[str, Any]:
    m = _FM_RE.match(md)
    if not m:
        return {}
    try:
        import yaml  # type: ignore
        return yaml.safe_load(m.group(1)) or {}
    except Exception:
        return {}


def discover(skills_dir: Path = _SKILLS) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not skills_dir.exists():
        return out
    for f in sorted(skills_dir.glob("*/SKILL.md")):
        fm = _parse_frontmatter(f.read_text(encoding="utf-8"))
        if not fm.get("name"):
            fm["name"] = f.parent.name
        fm["_path"] = str(f)
        out.append(fm)
    return out


def as_openai_tools(skills: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """导出 OpenAI function-calling 工具定义列表。"""
    skills = skills if skills is not None else discover()
    tools: List[Dict[str, Any]] = []
    for s in skills:
        contract = (s.get("tool_contract") or {}).get("openai_function")
        if not contract:
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": contract.get("name", s.get("name")),
                "description": s.get("description", contract.get("description", "")),
                "parameters": contract.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return tools


def names(skills: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    skills = skills if skills is not None else discover()
    return [s.get("name") for s in skills if s.get("name")]


def get_skill(name: str, skills_dir: Path = _SKILLS) -> Optional[Dict[str, Any]]:
    """按 name 字段查单个 skill; 找不到返回 None。"""
    for s in discover(skills_dir):
        if s.get("name") == name:
            return s
    return None


def resolve_callable(backend_ref: str) -> Any:
    """解析 'path/to.py:func' 或 'module.path:Class.method' 引用并导入。

    返回:
      - 模块函数 → 直接返回 callable
      - 'Class.method' → 返回 (class, method_name) 元组, 由调用方实例化
    无法导入时抛 ImportError (fail-fast, 不静默回退)。
    """
    if not backend_ref or ":" not in backend_ref:
        raise ImportError(f"backend 引用格式应为 'module:func' 或 'path.py:func', 得到: {backend_ref!r}")
    mod_part, func_part = backend_ref.split(":", 1)
    mod_part = mod_part.strip()
    # func_part 可能带行内注释/补充说明, 如 'extract_rfq  (+ LLM 提议 via ...)'
    # 取第一个标识符 token (允许嵌套 'Class.method')
    func_part = re.split(r"[\s(]", func_part.strip(), 1)[0].strip()
    # path/to.py → 去掉 .py 后缀, / 转 .
    if mod_part.endswith(".py"):
        mod_part = mod_part[:-3].replace("/", ".").replace("\\", ".")
    import importlib
    try:
        mod = importlib.import_module(mod_part)
    except Exception as e:
        raise ImportError(f"无法导入 backend 模块 {mod_part!r}: {e}") from e
    # Class.method 形式
    if "." in func_part:
        cls_name, method_name = func_part.split(".", 1)
        cls = getattr(mod, cls_name, None)
        if cls is None:
            raise ImportError(f"模块 {mod_part} 无类 {cls_name}")
        return (cls, method_name)
    fn = getattr(mod, func_part, None)
    if fn is None:
        raise ImportError(f"模块 {mod_part} 无函数 {func_part}")
    return fn


def cross_check_allowlist(allowlist: set) -> Dict[str, Any]:
    """注册技能名必须都在 guardrails allow-list; 返回缺口。"""
    reg = set(names())
    # 技能目录名/名称用连字符, allow-list 同名。
    missing = sorted(reg - set(allowlist))
    return {"registered": sorted(reg), "not_in_allowlist": missing, "ok": not missing}


def summary() -> Dict[str, Any]:
    skills = discover()
    return {
        "count": len(skills),
        "skills": [{"name": s.get("name"), "version": s.get("version"),
                    "backend": s.get("backend", ""), "description": (s.get("description") or "")[:80]}
                   for s in skills],
        "openai_tools": as_openai_tools(skills),
    }


if __name__ == "__main__":
    import json
    from services.guardrails import TOOL_ALLOWLIST
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
    print("cross_check_allowlist:", json.dumps(cross_check_allowlist(TOOL_ALLOWLIST), ensure_ascii=False))
