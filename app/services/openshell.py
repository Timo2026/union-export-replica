"""openshell.py — OpenShell 策略引擎 (铁律①工程化).

加载 openshell/*.yaml, 在 Skill Dispatcher 每步强制执行:
  - iron-rule-1   : 确定性输出锁定 (sha256), 拒绝二次改写
  - hitl-required : 高风险字段触发 HITL
  - local-only    : 文件路径白名单
  - skill-allowlist: Skill 白名单
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional, Tuple

from services import skill_config as sc

_ROOT = Path(__file__).resolve().parent.parent
_OS_DIR = _ROOT / "openshell"

_POLICY_FILES = {
    "iron-rule-1": "iron-rule-1.yaml",
    "hitl-required": "hitl-required.yaml",
    "local-only": "local-only.yaml",
    "skill-allowlist": "skill-allowlist.yaml",
}


def _load_yaml(path: Path) -> Dict[str, Any]:
    import yaml  # type: ignore
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_policies(os_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """加载 4 个策略 YAML; 缺 iron-rule-1 直接 raise (fail-fast)."""
    d = Path(os_dir) if os_dir else _OS_DIR
    out: Dict[str, Dict[str, Any]] = {}
    for pid, fname in _POLICY_FILES.items():
        p = d / fname
        if not p.exists():
            if pid == "iron-rule-1":
                raise FileNotFoundError(f"openshell/{fname} missing — fail-fast (铁律①)")
            out[pid] = {"policy_id": pid, "enabled_default": True, "_missing": True}
            continue
        out[pid] = _load_yaml(p)
    return out


def sha256_obj(obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _path_allowed(path: str, allow_prefix: List[str], deny_glob: List[str]) -> bool:
    if not path:
        return True
    raw = str(path).replace("\\", "/")
    low = raw.lower()
    for g in deny_glob or []:
        g2 = g.lower().replace("**/", "").replace("**", "").lstrip("*")
        if g2 and g2 in low:
            return False
        if g.startswith("*.") and low.endswith(g[1:].lower()):
            return False
    if not allow_prefix:
        return True
    # normalize
    try:
        p = PurePosixPath(raw)
    except Exception:
        p = PureWindowsPath(raw)
    s = str(p).replace("\\", "/")
    for pref in allow_prefix:
        pref2 = pref.replace("\\", "/").rstrip("/") + "/"
        if s.startswith(pref2) or s == pref.rstrip("/"):
            return True
        # 相对路径也允许 (data/uploads/...)
        if ("/" + s).startswith(pref2) or s.startswith(pref2.lstrip("/")):
            return True
    return False


def check_skill_allowed(skill_id: str, policies: Dict[str, Any],
                        cfg: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
    viols: List[Dict[str, Any]] = []
    if not sc.policy_enabled(cfg, "skill-allowlist"):
        return True, viols
    pol = policies.get("skill-allowlist") or {}
    allowed = set(pol.get("allowed") or [])
    if not allowed:
        return True, viols
    if skill_id not in allowed:
        viols.append({"policy": "skill-allowlist", "skill": skill_id,
                      "reason": f"{skill_id} 不在白名单"})
        return False, viols
    # disabled skill in skills.yaml
    if not sc.skill_enabled(cfg, skill_id):
        viols.append({"policy": "skills.yaml", "skill": skill_id, "reason": "skill 已禁用"})
        return False, viols
    return True, viols


def check_local_paths(args: Dict[str, Any], policies: Dict[str, Any],
                      cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    viols: List[Dict[str, Any]] = []
    if not sc.policy_enabled(cfg, "local-only"):
        return viols
    pol = policies.get("local-only") or {}
    fps = pol.get("file_paths") or {}
    allow = list(fps.get("allow_prefix") or ["data/"])
    deny = list(fps.get("deny_glob") or [])
    path_keys = ("path", "file", "drawing", "step_path", "files", "file_path", "audio_path")
    candidates: List[str] = []
    for k in path_keys:
        v = args.get(k)
        if isinstance(v, str):
            candidates.append(v)
        elif isinstance(v, (list, tuple)):
            candidates.extend(str(x) for x in v if isinstance(x, (str, Path)))
    for pth in candidates:
        if not _path_allowed(pth, allow, deny):
            viols.append({"policy": "local-only", "path": str(pth),
                          "reason": "路径不在沙箱白名单"})
    return viols


def lock_key(skill_id: str, args: Optional[Dict[str, Any]] = None) -> str:
    """v6.1.0: 确定性输出锁的键 = skill_id + 输入指纹。

    铁律①语义是"同一输入下确定性输出不可被改写", 不是"同一 skill 永远只能有一种输出"。
    不同输入(不同询盘邮件)产生不同报价是合法的; 无 args 时退化为纯 skill_id (兼容旧调用)。
    """
    if not args:
        return skill_id
    return f"{skill_id}:{sha256_obj(args)[:16]}"


def lock_deterministic_output(skill_id: str, output: Any,
                              policies: Dict[str, Any],
                              locks: Dict[str, str]) -> Dict[str, Any]:
    """记录确定性 skill 输出哈希。返回 {locked, sha256}."""
    iron_on = policies.get("iron-rule-1", {}).get("locked", True) is not False
    applies = set((policies.get("iron-rule-1") or {}).get("applies_to") or [])
    if skill_id not in applies and applies:
        # 仍允许显式 iron_rule=deterministic 的 skill 锁定
        pass
    digest = sha256_obj(output)
    if skill_id not in locks:
        locks[skill_id] = digest
    return {"locked": iron_on, "sha256": digest, "first_seen": locks.get(skill_id) == digest}


def verify_locked_output(skill_id: str, output: Any, locks: Dict[str, str],
                         policies: Dict[str, Any]) -> List[Dict[str, Any]]:
    """输出是否与锁定哈希一致; 不一致 → violation."""
    viols: List[Dict[str, Any]] = []
    if not sc.policy_enabled(None, "iron-rule-1"):
        # 即使配置说关, locked 策略文件仍强制
        pass
    pol = policies.get("iron-rule-1") or {}
    if pol.get("locked") is False and not pol.get("enabled", True):
        return viols
    if skill_id not in locks:
        return viols
    digest = sha256_obj(output)
    if digest != locks[skill_id]:
        viols.append({"policy": "iron-rule-1", "skill": skill_id,
                      "reason": "确定性输出被改写",
                      "expected_sha256": locks[skill_id], "actual_sha256": digest})
    return viols


def check_hitl(output: Any, policies: Dict[str, Any],
               cfg: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
    """根据 hitl-required 策略评估是否需要人工."""
    reasons: List[Dict[str, Any]] = []
    if not sc.policy_enabled(cfg, "hitl-required"):
        return False, reasons
    pol = policies.get("hitl-required") or {}
    if not isinstance(output, dict):
        return False, reasons
    triggers = pol.get("triggers") or []
    for t in triggers:
        field = t.get("field")
        op = t.get("op", "gt")
        val = t.get("value")
        actual = output.get(field)
        if actual is None:
            continue
        hit = False
        try:
            if op == "gt":
                hit = float(actual) > float(val)
            elif op == "gte":
                hit = float(actual) >= float(val)
            elif op == "eq":
                hit = actual == val
            elif op == "in":
                hit = actual in (val or [])
        except (TypeError, ValueError):
            hit = False
        if hit:
            reasons.append({"policy": "hitl-required", "field": field,
                            "op": op, "threshold": val, "actual": actual})
    return bool(reasons), reasons


class OpenShell:
    """Dispatcher 使用的门禁对象。"""

    def __init__(self, cfg: Optional[Dict[str, Any]] = None,
                 policies: Optional[Dict[str, Any]] = None,
                 os_dir: Optional[Path] = None):
        self.cfg = cfg if cfg is not None else sc.load()
        self.policies = policies if policies is not None else load_policies(os_dir)
        self.locks: Dict[str, str] = {}
        self.violations: List[Dict[str, Any]] = []

    def precheck(self, skill_id: str, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        ok, viols = check_skill_allowed(skill_id, self.policies, self.cfg)
        viols = list(viols)
        viols.extend(check_local_paths(args or {}, self.policies, self.cfg))
        self.violations.extend(viols)
        return viols

    def postcheck(self, skill_id: str, output: Any, iron_rule: str = "",
                  args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        viols: List[Dict[str, Any]] = []
        is_det = iron_rule == "deterministic" or skill_id in set(
            (self.policies.get("iron-rule-1") or {}).get("applies_to") or [])
        key = lock_key(skill_id, args)
        if is_det:
            # 若同输入已有锁且哈希不同 → violation (防二次改写)
            viols.extend(verify_locked_output(key, output, self.locks, self.policies))
            if key not in self.locks:
                lock_deterministic_output(key, output, self.policies, self.locks)
        hitl, reasons = check_hitl(output, self.policies, self.cfg)
        self.violations.extend(viols)
        return {
            "ok": not viols,
            "violations": viols,
            "hitl_required": hitl,
            "hitl_reasons": reasons,
            "iron_locked": is_det and key in self.locks,
            "output_sha256": self.locks.get(key) if is_det else None,
        }

    def attempt_override(self, skill_id: str, new_output: Any) -> Dict[str, Any]:
        """模拟 LLM/外部试图改写确定性输出 — 应被拒绝."""
        viols = verify_locked_output(skill_id, new_output, self.locks, self.policies)
        self.violations.extend(viols)
        return {"allowed": not viols, "violations": viols}

    def status(self) -> Dict[str, Any]:
        pol_status = []
        for pid, pol in self.policies.items():
            pol_status.append({
                "id": pid,
                "enabled": sc.policy_enabled(self.cfg, pid),
                "locked": bool((pol or {}).get("locked", False)),
                "missing_file": bool((pol or {}).get("_missing")),
                "description": (pol or {}).get("description", ""),
            })
        return {"policies": pol_status, "locks": dict(self.locks),
                "violations": list(self.violations[-20:]),
                "violation_count": len(self.violations)}
