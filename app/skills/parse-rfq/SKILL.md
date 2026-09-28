---
name: parse-rfq
description: 从询盘邮件/文本抽取 canonical RFQ 字段（材料/数量/表面/公差/尺寸/交期），标记缺失项。确定性规则优先。
version: 1
iron_rule: deterministic
backend: services/intake.py:extract_rfq
openshell_policy: [iron-rule-1, local-only, skill-allowlist]
tool_contract:
  openai_function:
    name: parse_rfq
    description: 解析询盘 → RFQ
    parameters:
      type: object
      properties:
        email_text: {type: string}
      required: [email_text]
---
# parse-rfq

NemoClaw Skill：确定性 RFQ 抽取。LLM 不得改写 material/quantity 等已抽出字段。
