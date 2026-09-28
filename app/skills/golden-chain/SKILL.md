---
name: golden-chain
description: Blueprint：CAT 控制器端到端黄金链 S1-S5+M1（Intake→RFQ→DFM→Quote→Verify→HITL/Reply→CRM→Audit）。
version: 1
iron_rule: deterministic
backend: agents/cat_controller.py:CATController.run
openshell_policy: [iron-rule-1, hitl-required, local-only, skill-allowlist]
tool_contract:
  openai_function:
    name: golden_chain
    description: 运行黄金链 Blueprint
    parameters:
      type: object
      properties:
        email_text: {type: string}
        use_llm: {type: boolean}
      required: [email_text]
---
# golden-chain

编排用 Blueprint。单步 Skill 仍受 OpenShell 约束。
