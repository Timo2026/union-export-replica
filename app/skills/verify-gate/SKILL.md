---
name: verify-gate
description: 辟·牟·援·推·止业务验收 + HITL 门禁。输出 PASS/HITL/BLOCKED，由 policy 裁决而非 LLM。
version: 1
iron_rule: deterministic
backend: services/verification.py:Verification.run
openshell_policy: [iron-rule-1, hitl-required, skill-allowlist]
tool_contract:
  openai_function:
    name: verify_gate
    description: 业务验收门禁
    parameters:
      type: object
      properties:
        ctx_dict: {type: object}
---
# verify-gate

确定性验收。HITL/BLOCKED 时 dispatcher 返回 hitl_required=true。
