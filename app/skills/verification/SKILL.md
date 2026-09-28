---
name: verification
description: 五步裁决门禁（辟·牟·援·推·止）。对 RFQ + 制造 + 商业三域做事实/规则/证据/外推/终止五维校验，给出 PASS/HITL/BLOCKED 终态与升级原因。当需要决定一张报价能否放出、是否转人工时调用。
version: 1
backend: services/verification.py:Verification.run
iron_rule: deterministic
tool_contract:
  openai_function:
    name: verification
    description: 五步裁决门禁 (辟牟援推止)
    parameters:
      type: object
      properties:
        ctx_dict:
          type: object
          description: 上下文 dict，至少含 rfq / manufacturing / commercial 三个子域
      required: [ctx_dict]
---

# verification

## 何时用
DFM + 报价 + 商业费率都算完之后，最后一步裁决：这张单能不能自动放出？

## 输入 / 输出
- 入：`ctx_dict`（rfq / manufacturing / commercial 三域合并）
- 出：`{status: PASS|HITL|BLOCKED, reasons[], gate_hits[]}`

## 契约与失败策略
- 五步确定性：辟（事实）→ 牟（利润）→ 援（证据）→ 推（外推风险）→ 止（终止）。
- 任意一步命中升级条件 → status 升级，不回退（PASS < HITL < BLOCKED）。
- **铁律①**：status 由本函数裁决权威，Dispatcher/LLM 不得改写。

## 示例
DFM valid + margin 28% + 有 RAG 证据 → `status: PASS`。
DFM valid + margin 12%（< 15% 门禁）→ `status: HITL, reasons: ["利润率低于门禁"]`。
