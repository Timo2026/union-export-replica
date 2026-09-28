---
name: calc-quote
description: 基于零件参数用 Timo 确定性引擎产出报价。价格唯一权威来源，禁止 LLM 生成数字。
version: 1
iron_rule: deterministic
backend: adapters/timo_adapter.py:TimoAdapter.quote
openshell_policy: [iron-rule-1, hitl-required, skill-allowlist]
tool_contract:
  openai_function:
    name: calc_quote
    description: 确定性 CNC 报价
    parameters:
      type: object
      properties:
        material: {type: string}
        quantity: {type: integer}
      required: [material, quantity]
---
# calc-quote

铁律①：unit_price/final_price 必须与 Timo 返回值 sha256 一致。
