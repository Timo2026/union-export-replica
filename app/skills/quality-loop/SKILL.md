---
name: quality-loop
description: Loop 自迭代评分 — 3 专家输出 → QualityCritic 评分 → score<60 召回薄弱专家 → 二次仍低强制 HITL。与 FleetCoordinator v4 QUALITY_THRESHOLD=60 / MAX_LOOPS=2 完全对齐。
version: 1
iron_rule: deterministic
backend: services.quality_scorer:evaluate_quality
openshell_policy: [iron-rule-1, hitl-required, skill-allowlist]
tool_contract:
  openai_function:
    name: quality_loop_evaluate
    description: 评分 + 决定下一步 (loop/hitl/done)
    parameters:
      type: object
      properties:
        expert_results: {type: object, description: "3 专家 (material/price/dfm) 的输出 dict"}
        synthesis: {type: string, description: "Orchestrator 综合结论文本 (可选)"}
        critique_text: {type: string, description: "LLM critic 评分文本 (含 '评分: 75/100' 等)"}
        loop_count: {type: integer, description: "当前已 Loop 次数", "default": 0}
      required: [expert_results, loop_count]
---

# quality-loop

v5.0.0 新增 — 从 FleetCoordinator v4 的 QualityCritic + OrchestratorV4 抽出。

## 职责

1. 综合评分：解析 critic 文本中的分数（如 "评分: 75/100"），否则本地 fallback (取 expert score 加权平均)
2. 检测薄弱专家：识别 critic 提到的弱 agent，启发式过滤误判
3. 决定下一步动作：
   - `score < 60 且 loop_count < 2` → `loop` (召回评分最低的专家)
   - `score < 60 且 loop_count >= 2` → `hitl` (强制人工审批, 不再强行通过)
   - `score >= 60` → `done` (通过)

## 铁律

- iron-rule-1: 评分阈值与原 v4 完全一致 (60 / max 2)，不擅自修改
- hitl-required: 二次评分仍低时强制 HITL，业务真相靠人工
- 计算 deterministic: 解析逻辑纯规则，无网络/无 LLM 依赖

## 输入输出

```
输入: {
  expert_results: {material: {score: 80}, price: {score: 75}, dfm: {score: 45}},
  synthesis: "...",
  critique_text: "评分: 65/100, dfm 较弱",
  loop_count: 0
}

输出: {
  score: 65,
  weak_agents: ["dfm"],
  critique_text: "...",
  loop_count: 0,
  action: "done",
  feedback_reason: "评分 65 >= 60, 通过"
}
```

## 测试

`tests/test_quality_loop.py` (4 用例):
  1. score >= 60 → done
  2. score < 60 + loop_count=0 → loop + 召回 weak_agents
  3. score < 60 + loop_count=2 → hitl (强制升级)
  4. 解析 critic 文本 "评分: 75/100" + 识别 "dfm 较弱"
