---
name: dfm-expert
description: DFM 可制造性分析专家 — 检查最小壁厚 / 深孔长径比 / 螺纹底孔 / 装夹变形风险。LLM 推理基于精确几何。
version: 1
iron_rule: llm_proposal
backend: services.llm_planner.LLMPlanner.chat_json
openshell_policy: [skill-allowlist]
tool_contract:
  openai_function:
    name: dfm_expert
    description: DFM 专家 — 输入 dimensions, 输出 risks list + score + recommendations
    parameters:
      type: object
      properties:
        dimensions: {type: object, description: "尺寸字典 (mm)"}
        shape: {type: string, description: "零件形状"}
        user_input: {type: string}
      required: [dimensions]
---

# dfm-expert

v5.0.0 新增 — 从 FleetCoordinator v4 的 dfm_expert domain 抽出。

## 职责

基于精确几何尺寸，LLM 只做领域分析：
- 最小壁厚检查 (铝合金 CNC ≥ 1.5mm, 钢铁 ≥ 1.0mm)
- 深孔长径比 (L/D > 5 需特殊刀具)
- 螺纹底孔深度 (M8 标准底孔 φ6.8mm, 深度 ≥ 12mm)
- 装夹可行性 (薄壁零件易变形)
- 表面处理对薄壁的影响

## 铁律

- iron_rule: llm_proposal
- 数字不可改写, 仅分析
- LLM 离线降级: keyword rules (壁厚 < 1.5 → warning, etc.)

## 输入输出

输入: {dimensions: {outer_d, inner_d, length/width/height, thickness, holes?}, shape, user_input}
输出: {ok, agent: "dfm_expert", risks: [{type, severity, message}], score, recommendations, source}
