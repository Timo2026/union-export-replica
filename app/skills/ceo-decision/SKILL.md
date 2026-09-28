---
name: ceo-decision
description: CEO 智能决策引擎 — 5 证 (接受/历史/毛利/DFM/完整性) 评分 + 投票 + 置信度融合。decision ∈ {accept, reject, defer}。LLM 推理 (llm_proposal) + 离线 mock fallback。
version: 1
iron_rule: llm_proposal
backend: skills.ceo_decision.tool:run
openshell_policy: [skill-allowlist]
tool_contract:
  openai_function:
    name: ceo_decision
    description: CEO 决策 — 输入 decision_context (customer_history / risk_score / margin_pct / dfm_conflict), 输出 {decision, confidence, reasoning[], votes{}}
    parameters:
      type: object
      properties:
        decision_context: {type: object, description: "决策上下文 (客户历史 / 风险分 / 毛利 / DFM 冲突 / 完整性)"}
        threshold: {type: number, description: "接受阈值 (默认 70)", "default": 70}
      required: [decision_context]
---

# ceo-decision

v5.0.0 新增 — CEO 智能决策引擎 (简化版)。

## 设计原则

- 原 skills_extracted/ceo-decision-cb/scripts/ceo_engine.py 是 78KB 多模型蜂群 + 墨家五证 + 5 联动集成版本, 依赖外部 LLM API (127.0.0.1:1280/DashScope/DeepSeek)
- 本 skill 实现**离线可跑简化版**: 5 证评分 + 加权投票 + 阈值决策
- LLM 在线时扩展: 调用 LLMPlanner 对 reasoning[] 做润色 (未来扩展)

## 5 证 + 投票

| 证 (证型) | 输入 | 评分逻辑 |
|-----------|------|----------|
| acceptance (接受度) | quote.total_single | ≥ ¥10000 → 80; ≥ ¥5000 → 60; < ¥5000 → 40 |
| history (历史) | customer.is_new / won_count / lost_count | 老客 won≥3 → 80; 新客 → 50; lost≥2 → 30 |
| margin (毛利) | commercial.margin_pct | ≥ 25% → 90; ≥ 15% → 70; < 15% → 40 |
| dfm (DFM 冲突) | verification.conflicts | 0 冲突 → 90; 1 冲突 → 60; ≥2 → 30 |
| completeness (完整性) | missing_information count | 0 缺 → 90; 1-2 → 70; ≥3 → 40 |

投票: weighted_avg(scores) ≥ threshold → accept; < 40 → reject; 否则 defer
权重: acceptance 0.25 + history 0.15 + margin 0.25 + dfm 0.20 + completeness 0.15

## 铁律

- iron_rule: llm_proposal (LLM 提议, 引擎裁决 decision)
- LLM 离线降级: 5 证 mock 评分不静默冒充
- reject 决策附 reason: 哪些证 < 50

## 输入输出

```
输入: {
  decision_context: {
    quote: {total_single: 50000},
    margin_pct: 23.1,
    customer: {is_new: false, won_count: 5, lost_count: 1},
    verification: {conflicts: []},
    missing: 0
  },
  threshold: 70
}

输出: {
  ok, skill, decision: "accept"|"reject"|"defer",
  confidence: 75,
  reasoning: ["5 证综合 75/100", "客户老客 5 次 won", ...],
  votes: {acceptance: 80, history: 80, margin: 70, dfm: 90, completeness: 90},
  iron_rule: "llm_proposal"
}
```
