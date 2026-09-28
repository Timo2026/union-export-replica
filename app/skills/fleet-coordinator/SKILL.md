---
name: fleet-coordinator
description: FleetCoordinator v4 适配器 — 精确几何/重量/费用计算 + 3 专家 (material/quote/dfm) + Loop 自迭代。复用 DGX_Spark 工业经验 v4 的 Python 计算引擎 + Ollama qwen2.5:1.5b 专家推理。
version: 1
iron_rule: deterministic
backend: services.fleet_v4.adapter:FleetCoordinatorV4Adapter.run_quote
openshell_policy: [iron-rule-1, hitl-required, skill-allowlist]
tool_contract:
  openai_function:
    name: fleet_coordinator_v4
    description: 工业经验 v4 报价/DFM 协调 — 输入零件描述+尺寸, 返回精确计算 + 3 专家分析
    parameters:
      type: object
      properties:
        material: {type: string, enum: [6061, 7075, 304, carbon_steel], description: "材料牌号"}
        shape: {type: string, enum: [flange, bushing, block], description: "零件形状"}
        dimensions: {type: object, description: "尺寸字典 (mm) — flange/bushing 用 outer_d/inner_d/(thickness or length); block 用 width/height/thickness; 可选 holes"}
        quantity: {type: integer, description: "数量", minimum: 1}
        surface: {type: string, enum: [none, anodizing, pvd, spray, electroplating], description: "表面处理"}
        mode: {type: string, enum: [fast_path, expert_path], description: "fast=仅计算; expert=计算+3 专家+Orchestrator+Critic (需 Ollama 在线)"}
      required: [material, shape, dimensions, quantity]
---

# fleet-coordinator

v5.0.0 新增 — v4 适配 skill。

## 职责

把原 `unionstill_dfm_quote_agent.py` (独立 CLI) 的能力封装为可被 dispatcher 调用的 skill:

- **fast_path**: 仅 Python 计算 (CalculationEngine)，零 LLM，单次 < 50ms
- **expert_path**: 计算 + 3 专家 (material/quote/dfm) + Orchestrator 综合 + QualityCritic 评分 + Loop 自迭代 (< 60 触发)

## 数据源

- `services/fleet_v4/calculation.py` — CalculationEngine + MATERIAL_DB + SURFACE_PRICE + MACHINING_RATE + GROSS_MARGIN
- `services/_fleet_v4_original.py` — 原 v4 完整实现 (ExpertAgentV4/OrchestratorV4/QualityCritic) 备份, 懒加载

## 铁律

- iron-rule-1: 报价数字 100% 来自 CalculationEngine, 不可被 LLM 改写
- hitl-required: 精密公差/高金额/DFM 冲突 → 强制升级 HITL
- 计算引擎无网络依赖, Ollama 离线时自动降级 fast_path

## 输入输出

```
输入: {material, shape, dimensions, quantity, surface?, mode?}
输出: {ok, calculation: {...}, experts: {...}, synthesis, critic, iron_rule}
```

## 测试

`tests/test_fleet_v4.py` (6 用例):
  1. CalculationEngine 圆柱/空心/长方体几何精度
  2. calculate_quote 4 种材料 + 4 种表面处理
  3. 与方案文档 §5 测试用例对齐 (轴套 50 件 ¥76.53/pc)
  4. run_fleet_v4_quote fast_path < 100ms
  5. invalid 输入抛 ValueError
  6. Adapter mode=expert_path fallback fast_path 当 Ollama 离线
