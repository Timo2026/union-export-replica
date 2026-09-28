---
name: material-expert
description: 材料工程专家 — 验证材料选型 / 检查表面处理兼容性 / 推荐替代材料。基于 CalculationEngine 的精确重量/价格, LLM 推理（llm_proposal）。
version: 1
iron_rule: llm_proposal
backend: services.llm_planner.LLMPlanner.chat_json
openshell_policy: [skill-allowlist]
tool_contract:
  openai_function:
    name: material_expert
    description: 材料专家推理 — 输入 calculation 字典 (volume/weight/material_name/total_single), 输出 analysis dict (compatible/recommended/risks/score)
    parameters:
      type: object
      properties:
        calculation: {type: object, description: "fleet-coordinator 的 calculation 结果"}
        user_input: {type: string, description: "用户原始输入 (可选)"}
      required: [calculation]
---

# material-expert

v5.0.0 新增 — 从 FleetCoordinator v4 的 material_expert domain 抽出。

## 职责

基于精确计算数值（Python 已算出体积/重量/价格），LLM 只做：
- 验证材料选型是否合适（强度/硬度/延伸率匹配场景）
- 检查材料与表面处理的兼容性（anodizing_ok 字段）
- 推荐替代材料（如 6061 → 7075 升级强度）

## 铁律

- iron_rule: llm_proposal (LLM 提议, 引擎裁决数字)
- 数字 (volume/weight/total_single) 来自 CalculationEngine, 不可改写
- 离线降级: LLM 不可达时返 keyword-based mock 结论, 不静默冒充

## 输入输出

```
输入: {calculation: {material_name, volume_cm3, weight_kg_single, total_single, ...}, user_input}
输出: {ok, agent: "material_expert", analysis: {compatible, recommended, risks, score}, source: "llm|mock"}
```
