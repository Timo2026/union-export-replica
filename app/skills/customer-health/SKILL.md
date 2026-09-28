---
name: customer-health
description: 客户健康分 - 6 维度加权评分 (0-100) + 流失风险等级 (low/med/high) + 主动触达建议。
version: 1
iron_rule: deterministic
backend: services.customer_health:CustomerHealthEngine
openshell_policy: [iron-rule-1, local-only, skill-allowlist]
tool_contract:
  openai_function:
    name: customer_health
    description: 客户健康分计算
    parameters:
      type: object
      properties:
        action: {type: string, enum: [compute, list_at_risk, proactive_reach]}
        customer_id: {type: string}
        threshold: {type: number}
      required: [action]
---
# customer-health

v6.1 飞轮层 Skill。维度：frequency / win_rate / avg_margin / response_days / dispute_rate / tenure_days。

铁律①保持：纯规则无 LLM，输入来自 CRM SQL。