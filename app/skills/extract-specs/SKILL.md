---
name: extract-specs
description: "LLM 提议补全 RFQ 缺字段。只填空, 不覆盖确定性值。铁律: LLM 提议、引擎裁决。"
version: 1
iron_rule: llm_proposal
backend: services/llm_planner.py:extract_rfq
openshell_policy: [skill-allowlist]
tool_contract:
  openai_function:
    name: extract_specs
    description: LLM 补全 RFQ 缺字段
    parameters:
      type: object
      properties:
        email_text: {type: string}
---
# extract-specs

LLM 离线时显式 MOCK, 返回原 rfq, 不冒充。
