# -*- coding: utf-8 -*-
import json, re
from .reasoning_chain import ReasoningChain, StepType

_APPROVE = ("approve", "approved", "pass", "通过", "同意")
_REJECT = ("reject", "rejected", "否决", "拒绝", "rejected", "驳回")

class SerialExpertOrchestrator:
    def __init__(self, ai_wrapper, experts, bus, skill_registry=None, schema_validator=None):
        self.ai = ai_wrapper
        self.experts = experts or {}
        self.bus = bus
        self.skill_registry = skill_registry
        self.schema_validator = schema_validator

    def _ask(self, name, expert_cfg, message, context):
        sp = expert_cfg.get("system_prompt", "你是领域专家。")
        raw = ""
        try:
            raw = self.ai.chat("待决策事项: " + message + "\n上下文: " + json.dumps(context, ensure_ascii=False, default=str),
                               system_prompt=sp, temperature=0.3, max_tokens=600)
        except Exception:
            raw = ""
        rec = "abstain"
        low = (raw or "").lower()
        if any(k in low for k in _REJECT):
            rec = "reject"
        elif any(k in low for k in _APPROVE):
            rec = "approve"
        return {"expert": name, "recommendation": rec, "raw": (raw or "")[:400],
                "has_veto": bool(expert_cfg.get("has_veto")),
                "has_override": bool(expert_cfg.get("has_override"))}

    def convene(self, message, context_dict=None, expert_list=None, progress_cb=None):
        context = context_dict or {}
        expert_list = expert_list or list(self.experts.keys())
        transcript = []
        veto_by = None
        override_by = None
        decision = "APPROVED"
        for idx, name in enumerate(expert_list):
            if progress_cb:
                try: progress_cb(idx, name)
                except Exception: pass
            cfg = self.experts.get(name, {})
            r = self._ask(name, cfg, message, context)
            transcript.append(r)
            if r["recommendation"] == "reject" and r["has_veto"]:
                veto_by = name
                decision = "REJECTED"
        # CEO override pass
        for r in transcript:
            if r["has_override"] and r["recommendation"] == "approve" and veto_by:
                decision = "APPROVED"
                override_by = r["expert"]
        rationale = "专家会议结论" + (": %s 行使一票否决" % veto_by if veto_by else "")
        if override_by:
            rationale += "; CEO 覆写否决"
        return {
            "decision": decision,
            "veto_by": veto_by,
            "override_by": override_by,
            "reason": rationale,
            "rationale": rationale,
            "transcript": transcript,
        }
