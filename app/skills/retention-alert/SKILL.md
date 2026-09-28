---
name: retention-alert
description: 流失预警 - 高风险 + 长期未联系客户自动生成主动触达列表。
version: 1
iron_rule: deterministic
backend: services.customer_flywheel:RetentionAlert
openshell_policy: [iron-rule-1, local-only, skill-allowlist]
tool_contract:
  openai_function:
    name: retention_alert
    description: 流失预警扫描
    parameters:
      type: object
      properties:
        threshold: {type: number}
        no_contact_days: {type: number}
      required: []
---
# retention-alert

v6.1 飞轮层 Skill。基于 customer_health + last_contact_at 触发告警。

铁律①保持：纯规则，无 LLM 决策。