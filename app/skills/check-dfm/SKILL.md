---
name: check-dfm
description: 材料×表面×公差工艺冲突检测（Timo ConflictChecker）。硬冲突→BLOCKED，警告→HITL。确定性，拒绝 LLM override。
version: 1
iron_rule: deterministic
backend: adapters/timo_adapter.py:TimoAdapter.conflict_check
openshell_policy: [iron-rule-1, skill-allowlist]
tool_contract:
  openai_function:
    name: check_dfm
    description: DFM 冲突检测
    parameters:
      type: object
      properties:
        material: {type: string}
        surface: {type: string}
      required: [material]
---
# check-dfm

铁律①：conflicts/valid 必须来自 ConflictChecker，Dispatcher/LLM 不得改写。
