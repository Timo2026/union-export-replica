---
name: feasibility-checker
description: 设备能力校验 — 零件尺寸/重量/材料/公差四维核对工厂设备能力表，返回可用设备 + 阻断问题 + 建议。确定性，不产价（铁律②）。
version: 1
iron_rule: deterministic
backend: skills/feasibility-checker/tool.py
openshell_policy: [iron-rule-1, local-only, skill-allowlist]
tool_contract:
  openai_function:
    name: feasibility_check
    description: 设备能力可行性校验（不定价）
    parameters:
      type: object
      properties:
        length: {type: number}
        width: {type: number}
        height: {type: number}
        weight: {type: number}
        material: {type: string}
        tolerance_grade: {type: string}
      required: [length, width, height]
---
# feasibility-checker

精选自外部 skill 库（设备能力校验），并入项目 NemoClaw 体系。

**边界**：
- 铁律②：只判可行性，绝不输出价格；报价权威仍在确定性内核（`calc_quote`/ Timo）。
- 设备能力表为**默认占位值**（`_source: default-capability-table`），需工厂提供真实机床参数后更新，否则结果仅供演示。
- 离线本地计算，无网络依赖。
