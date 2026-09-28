---
name: write-reply
description: 英文客户回复草稿。默认模板确定性起草；可选 LLM，但仍 draft_only，不自动发送、不编造价格承诺。
version: 1
iron_rule: draft_only
backend: services/reply.py:build_reply (+ llm_planner.draft_reply)
openshell_policy: [skill-allowlist]
tool_contract:
  openai_function:
    name: write_reply
    description: 英文回复草稿
    parameters:
      type: object
      properties:
        use_llm: {type: boolean}
---
# write-reply

铁律：外部发送默认 draft_only，数字以 verify/quote 结果为准。
