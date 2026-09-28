---
name: orchestrator
description: 智能编排器 - 自动发现 + 调用其他 skill 的能力，支持任务分解、能力匹配、工作流执行。处理需要多步骤、多技能协作的复杂请求。
version: 1
iron_rule: llm_proposal
backend: skills.orchestrator.tool:run
openshell_policy: [skill-allowlist]
tool_contract:
  openai_function:
    name: orchestrate
    description: 编排器 - 接收复杂请求，分解、匹配、生成执行计划
    parameters:
      type: object
      properties:
        request: {type: string, description: "用户原始请求 (自然语言)"}
        workflow_name: {type: string, enum: [flange_quote, shaft_sleeve_quote, rectangular_quote, general_quote], description: "可选预定义工作流"}
      required: [request]
---

# orchestrator

v5.0.0 — 编排器。复用 skills_extracted 设计意图，自己实现简化版 (原 zip 无 scripts)。

## 职责

1. **任务分解**: 自然语言 → 步骤序列
2. **能力匹配**: 按关键词匹配 skills (reuse skill_dispatcher._RULE_ROUTES)
3. **工作流执行**: 4 个预定义 workflow (flange_quote / shaft_sleeve_quote / rectangular_quote / general_quote)
4. **计划生成**: 返 plan = [{skill_id, args}, ...] 给 dispatcher 顺序执行

## 4 个预定义 workflow

- `flange_quote`: parse_rfq → check_dfm → fleet-coordinator → verify_gate → write_reply → quality-loop
- `shaft_sleeve_quote`: 同上 (bushing 形状)
- `rectangular_quote`: parse_rfq → check_dfm → fleet-coordinator → verify_gate → write_reply
- `general_quote`: chat_understand (LLM 意图分类) → 自动选 skill 序列

## 铁律

- iron_rule: llm_proposal (orchestrator 提议 plan, dispatcher 执行)
- 不直接调 skill, 只返 plan
- LLM 离线降级: keyword rules + 预定义 workflow

## 输入输出

输入: {request: "6061 法兰 1200 件 报价", workflow_name?: "flange_quote"}
输出: {ok, plan: [{step: 1, skill: "parse_rfq", args: {...}}, ...], source: "workflow|llm|keyword"}
