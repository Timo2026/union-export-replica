---
name: quote-calibration
description: 报价偏差学习 - 基于 won/lost outcome 累计 price_bias_pct (上限 ±10%)，作为参数注入 Timo (不改 Timo 内部)。
version: 1
iron_rule: deterministic
backend: services.quote_calibration:QuoteCalibration
openshell_policy: [iron-rule-1, local-only, skill-allowlist]
tool_contract:
  openai_function:
    name: quote_calibration
    description: 价格自学习
    parameters:
      type: object
      properties:
        action: {type: string, enum: [record, get_adjustments]}
        context_id: {type: string}
        customer_id: {type: string}
        material: {type: string}
        quoted_unit_price: {type: number}
        actual_unit_cost: {type: number}
        outcome: {type: string, enum: [won, lost, no_response]}
      required: [action]
---
# quote-calibration

v6.1 飞轮层 Skill。决策矩阵：
- won + 偏差 > +5% → price_up_pct_3
- lost + 偏差 > -2% → price_down_pct_5
- 等其他组合见 services/quote_calibration.py

铁律①保持：bias_pct 仅作为 Timo 参数注入，不改 calc_quote 内部。