---
name: price-expert
description: CNC 加工报价专家 — 解释分项费用构成 (材料/加工/表面处理), 评估批量经济性, 毛利合理性。LLM 推理（llm_proposal）基于精确计算。
version: 1
iron_rule: llm_proposal
backend: services.llm_planner.LLMPlanner.chat_json
openshell_policy: [skill-allowlist]
tool_contract:
  openai_function:
    name: price_expert
    description: 报价专家 — 输入 calculation 字典, 输出 explanation (材料/加工/表面分项占比) + batch_economy + margin_score
    parameters:
      type: object
      properties:
        calculation: {type: object}
        user_input: {type: string}
      required: [calculation]
---

# price-expert

v5.0.0 新增 — 从 FleetCoordinator v4 的 quote_expert domain 抽出。

## 职责

基于 CalculationEngine 算出的精确分项费用（material_cost/machining_cost/surface_cost/total_single），LLM 只做：
- 解释分项费用占比（材料费 X%, 加工费 Y%, 表面 Z%）
- 评估批量经济性（数量翻倍单件成本下降幅度）
- 评估毛利合理性（与行业 20% 基准对比）
- 给出优化建议（如减少表面处理、批量优化）

## 铁律

- iron_rule: llm_proposal
- 数字不可改写, 仅解释
- LLM 离线降级: keyword-based mock 结论

## 输入输出

输入: {calculation: {material_cost_single, machining_cost_single, surface_cost_single, total_single, total_batch, quantity}}
输出: {ok, agent: "price_expert", explanation: {ratios, batch_economy, margin_score, suggestions}, source}
