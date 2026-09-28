"""agent_spec.py — 加载并校验 agent.yaml (nemo-agents-spec-v1 风格部署契约).

校验: 必需字段存在、tool 名与 guardrails allow-list 一致、models.roles 覆盖 Model Mesh、
memory 五层齐全、deployment.profiles 合法。返回结构化校验结果 (不抛, 供测试/CLI 断言)。
诚实声明: 目标 NeMo Platform 版本的确切字段需以其 CLI/schema 复核; 本校验器保证本仓库契约自洽。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from services.config import _ROOT, _load_yaml
from services.guardrails import TOOL_ALLOWLIST

_REQUIRED_TOP = ["apiVersion", "kind", "metadata", "spec"]
_REQUIRED_SPEC = ["instructions", "models", "tools", "memory", "guardrails",
                  "control", "observability", "security", "deployment"]
_MESH_ROLES = {"FAST", "VISION", "REASON", "EMBED", "ASR", "DETERMINISTIC"}
_MEM_LAYERS = {"working", "fact", "semantic", "artifact", "episodic"}
_VALID_PROFILES = {"A", "B", "C", "D"}


def load_agent_spec(root: Path | str | None = None) -> Dict[str, Any]:
    root = Path(root) if root else _ROOT
    return _load_yaml(root / "config" / "agent.yaml")


def validate(spec: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    for k in _REQUIRED_TOP:
        if k not in spec:
            errors.append(f"缺顶层字段: {k}")
    if spec.get("kind") != "Agent":
        errors.append(f"kind 应为 Agent, 实为 {spec.get('kind')}")
    if not str(spec.get("apiVersion", "")).startswith("nemo.agents/"):
        warnings.append(f"apiVersion 非 nemo.agents/*: {spec.get('apiVersion')}")

    sp = spec.get("spec", {}) or {}
    for k in _REQUIRED_SPEC:
        if k not in sp:
            errors.append(f"spec 缺字段: {k}")

    # models.roles 覆盖 Model Mesh
    roles = set(((sp.get("models") or {}).get("roles") or {}).keys())
    missing_roles = _MESH_ROLES - roles
    if missing_roles:
        errors.append(f"models.roles 缺角色: {sorted(missing_roles)}")

    # tools 名必须在 guardrails allow-list 内 (一致性)
    tool_names = {t.get("name") for t in (sp.get("tools") or [])}
    unknown = tool_names - TOOL_ALLOWLIST
    if unknown:
        errors.append(f"tools 含未在 allow-list 的工具: {sorted(unknown)}")
    if not tool_names:
        errors.append("tools 为空")

    # memory 五层
    mem = set((sp.get("memory") or {}).keys())
    missing_mem = _MEM_LAYERS - mem
    if missing_mem:
        errors.append(f"memory 缺层: {sorted(missing_mem)}")

    # guardrails 三段
    gr = sp.get("guardrails") or {}
    for stage in ("input", "tool", "output"):
        if stage not in gr:
            errors.append(f"guardrails 缺段: {stage}")

    # deployment profiles
    profs = set((sp.get("deployment") or {}).get("profiles") or [])
    if not profs or not profs.issubset(_VALID_PROFILES):
        errors.append(f"deployment.profiles 非法: {sorted(profs)}")

    # external send 默认 draft_only (安全)
    ext = ((sp.get("security") or {}).get("external_send") or {}).get("default")
    if ext != "draft_only":
        warnings.append(f"security.external_send.default 非 draft_only: {ext}")

    return {"valid": not errors, "errors": errors, "warnings": warnings,
            "tool_count": len(tool_names), "roles": sorted(roles),
            "profiles": sorted(profs)}


if __name__ == "__main__":
    import json
    s = load_agent_spec()
    print(json.dumps(validate(s), ensure_ascii=False, indent=2))
