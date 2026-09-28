"""verification skill — 委托 services/verification.Verification.run (v6.0.0 最小补全)."""
from __future__ import annotations
from typing import Any, Dict


def run(ctx, ctx_dict: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
    """五步裁决 (辟·牟·援·推·止). 委托 services.verification.Verification.run."""
    if not ctx_dict:
        return {"ok": False, "skill": "verification", "iron_rule": "deterministic",
                "error": "ctx_dict required"}
    try:
        from services.verification import Verification
        # 从 policy 拿 verifier
        policy = {}
        try:
            policy = ctx.get_ctrl().policy if hasattr(ctx, "get_ctrl") else {}
        except Exception:
            pass
        v = Verification(policy or {})
        res = v.run(ctx_dict)
        return {
            "ok": True, "skill": "verification", "iron_rule": "deterministic",
            "status": res.get("status", "UNKNOWN"),
            "reasons": res.get("reasons", []),
            "conflicts": res.get("conflicts", []),
            "risk_score": res.get("risk_score", 0.0),
            "gate_history": res.get("gate_history", []),
            "next_action": res.get("next_action"),
            "_source": "services.verification.Verification.run",
        }
    except Exception as e:
        return {"ok": False, "skill": "verification", "iron_rule": "deterministic",
                "error": repr(e)}
