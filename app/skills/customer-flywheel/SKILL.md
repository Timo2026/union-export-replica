---
name: customer-flywheel
description: 客户跟进飞轮编排 - 报价发出后自动生成 5 步跟进任务链 (Day 1/3/7/14/30)，纯规则不允许 LLM 决策时机。
version: 1
iron_rule: deterministic
backend: services.customer_flywheel:CustomerFlywheel
openshell_policy: [iron-rule-1, local-only, skill-allowlist]
tool_contract:
  openai_function:
    name: customer_flywheel
    description: 跟进编排 (调度/取消/列表)
    parameters:
      type: object
      properties:
        action: {type: string, enum: [schedule, list, cancel]}
        context_id: {type: string}
        customer_id: {type: string}
      required: [action]
---
# customer-flywheel

v6.1 飞轮层 Skill。报价成功后调度 5 步跟进（D+1 确认 / D+3 轻推 / D+7 加诱因 / D+14 最终报价 / D+30 回流）。

铁律①保持：LLM 不决策跟进节奏，纯规则查 schedule 表。