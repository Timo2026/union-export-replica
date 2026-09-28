"""services/egress_gate.py — D-P0.1 集中式发信主闸 (egress kill-switch).

铁律① (data-stays-local) 的集中强制层: 任何真实外发通道 (smtp/imap/webhook)
必须先过此闸。默认 DENY (fail-safe); 仅以下两种显式授权之一才放行:

  1. settings.yaml:
       egress:
         allow: true            # 总开关
         channels: {smtp: true} # 逐通道
  2. 环境变量 UEA_EGRESS_ALLOW="smtp,webhook" 或 "all"

总开关 allow=false 时, 即便 channels.<ch>=true 也拒 (主闸优先)。
被拒尝试写审计 data/egress_gate.jsonl (best-effort, 不抛)。
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

log = logging.getLogger(__name__)

KNOWN_CHANNELS = ("smtp", "imap", "webhook")


class EgressBlockedError(RuntimeError):
    """真实外发被集中闸拦截 (铁律①)."""


@dataclass
class EgressDecision:
    channel: str
    allowed: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {"channel": self.channel, "allowed": self.allowed, "reason": self.reason}


def _resolve_settings(settings: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if settings is not None:
        return dict(settings)
    try:
        from services.config import load_settings
        return load_settings() or {}
    except Exception:
        return {}


def _resolve_env(env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    return env if env is not None else os.environ


def _env_grants(channel: str, env: Mapping[str, str]) -> bool:
    raw = (env.get("UEA_EGRESS_ALLOW") or "").strip()
    if not raw:
        return False
    tokens = [t.strip().lower() for t in raw.split(",") if t.strip()]
    return "all" in tokens or channel.lower() in tokens


def check(channel: str, settings: Optional[Mapping[str, Any]] = None,
          env: Optional[Mapping[str, str]] = None) -> EgressDecision:
    """裁决某外发通道是否放行。默认 DENY。"""
    s = _resolve_settings(settings)
    e = _resolve_env(env)

    if _env_grants(channel, e):
        return EgressDecision(channel, True, "env UEA_EGRESS_ALLOW granted")

    egress = s.get("egress") or {}
    master = bool(egress.get("allow", False))
    ch_allowed = bool((egress.get("channels") or {}).get(channel, False))
    if master and ch_allowed:
        return EgressDecision(channel, True, "settings.egress granted")
    if ch_allowed and not master:
        reason = "settings.egress.allow=false 主闸关闭 (覆盖 channels)"
    else:
        reason = "默认拒绝: 无显式 egress 授权 (铁律① data-stays-local)"
    d = EgressDecision(channel, False, reason)
    _audit(d, e)
    return d


def assert_allowed(channel: str, settings: Optional[Mapping[str, Any]] = None,
                   env: Optional[Mapping[str, str]] = None) -> EgressDecision:
    """放行返 decision; 拒绝抛 EgressBlockedError。"""
    d = check(channel, settings=settings, env=env)
    if not d.allowed:
        raise EgressBlockedError(f"egress '{channel}' blocked: {d.reason}")
    return d


def _audit(decision: EgressDecision, env: Mapping[str, str]) -> None:
    """被拒尝试留痕 (best-effort)。"""
    try:
        p = Path("data") / "egress_gate.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        line = {"ts": time.time(), "event": "egress_denied", **decision.to_dict()}
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass
    log.warning("[egress-gate] DENY %s: %s", decision.channel, decision.reason)
