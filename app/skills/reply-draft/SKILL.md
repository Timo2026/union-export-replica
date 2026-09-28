---
name: reply-draft
description: 根据裁决结果（PASS/HITL/BLOCKED）起草英文外贸回复邮件草稿。PASS 给确认报价，HITL 给待确认措辞，BLOCKED 给替代方案。当需要把裁决结果转成可发送给客户的英文邮件时调用。
version: 1
backend: services/reply.py:build_reply
tool_contract:
  openai_function:
    name: reply_draft
    description: 起草英文外贸回复邮件
    parameters:
      type: object
      properties:
        ctx_dict:
          type: object
          description: 上下文 dict（含 rfq / quote / customer 等）
        verification:
          type: object
          description: verification skill 的输出（status / reasons）
      required: [ctx_dict, verification]
---

# reply-draft

## 何时用
裁决完成后，把结果翻译成客户能看懂的英文邮件。

## 输入 / 输出
- 入：`ctx_dict`（全局上下文）+ `verification`（裁决结果）
- 出：`{subject, body, auto_send, mode, guardrail_output}`

## 契约与失败策略
- 草稿由确定性模板生成；可选 LLM 润色（opt-in），**LLM 不改价格/交期数字**。
- 输出过 `guardrails.output`：禁止承诺（100% defect free / lowest price 等）。
- BLOCKED → 草稿含替代方案（`_alternative`），不直接拒绝。
- 外发由 `external_send` 策略门禁二次确认，草稿本身不触发发送。

## 示例
PASS + quote total ¥9413 → `subject: "Quotation for 6061 brackets", auto_send: false, mode: "confirm"`。
