---
name: agent-fleet-coordinator
description: "name: agent-fleet-coordinator"
---

---
name: agent-fleet-coordinator
version: 1.0.0
description: |
  多Agent舰队协调器 — 基于libs/agent_base的OO多Agent编排Skill
  
  功能:
  - 注册多个Agent（Skill包装器）
  - 任务分解（从"完整方案"拆成画图→报价→文档）
  - 并行/串行执行调度
  - 结果聚合
  - 熔断保护
  
  设计参考: cad-agent-qa (Pipeline模式 + OO架构)
  共享模块: libs/agent_base.py + libs/intent_router.py
author:
  - 大帅 (dashuai coach)
license: MIT
tags:
  - ai-agent
  - multi-agent
  - orchestration
  - fleet-coordinator
  - pipeline
  - opc-hackathon-2026

## 触发条件

- 用户说"完整方案"、"全流程"、"端到端"、"一条龙"
- 涉及多步骤任务（画图→报价→文档）
- 意图路由返回 'orchestrate' 时自动触发

## 架构

Pipeline模式（学自cad-agent-qa）:
```
TaskDecomposer → AgentRegistry → FleetScheduler → ResultAggregator
     ↓               ↓               ↓               ↓
  Step 1: draw   agent:step-factory  并行/串行    合并输出
  Step 2: quote  agent:quote-ptuning  调度       ZIP打包
  Step 3: doc    agent:doc-gen
```
