---
name: reid-os
description: Reid 决策操作系统 — 分诊台 (Triage) + 协议执行 (Protocol) + 价值观校准 + 拉闸干预。15s 极速决策。工作/家庭双领域路由。LLM 推理 (llm_proposal) + 离线 mock。
version: 1
iron_rule: llm_proposal
backend: skills.reid_os.tool:run
openshell_policy: [skill-allowlist]
tool_contract:
  openai_function:
    name: reid_os
    description: Reid 决策 — 输入 request, 输出 {domain, action, reason, values_aligned, intervention}
    parameters:
      type: object
      properties:
        request: {type: string, description: "用户请求 (自然语言)"}
      required: [request]
---

# reid-os

v5.0.0 新增 — Reid 决策操作系统 (简化版, 离线可跑)。

## 设计原则

- 原 skills_extracted/reid-operating-system 是 1.0.0 版本, 含分诊台 + 协议执行 + 价值观校准 + 拉闸干预
- 本实现核心逻辑: 关键词分诊 + 协议模板 + 价值观校准检查

## 三层架构

```
用户输入 → 分诊台 (1 次, 关键词路由) → 协议执行 (1 次, mock 模板) → 结构化输出
             ↑ 路由判断 (work / family / unknown)   ↑ 价值观校准 (values_aligned)
             ↑ 信号检测 (关键词触发拉闸)              ↑ 拉闸干预 (危险/紧急/不可逆)
```

## 输入输出

```
输入: {request: "怎么处理客户投诉?"}
输出: {
  domain: "work" | "family" | "unknown",
  action: "走 COPC 协议 / 走 RCF 协议 / 走 RFCP 协议 / 拉闸",
  reason: "工作场景, 涉及客户关系, 走 COPC 协议",
  values_aligned: true | false,
  intervention: null | "warning: 紧急/危险/不可逆关键词触发",
  iron_rule: "llm_proposal"
}
```

## 触发关键词

- 工作域: 工作/客户/订单/报价/项目/合同/工单/客户投诉
- 家庭域: 家庭/孩子/老人/配偶/父母/生活/健康
- 拉闸: 紧急/危险/不可逆/投诉到总部/撤资/破产
- 价值观: 利他/共赢/长期/信任/承诺

## 铁律

- iron_rule: llm_proposal (Reid 提议路由, dispatcher 执行)
- LLM 离线降级: mock 协议模板不静默冒充
- 拉闸检测: 命中"危险/不可逆"关键词必返 intervention 警告
