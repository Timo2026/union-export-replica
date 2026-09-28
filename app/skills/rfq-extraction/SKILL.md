---
name: rfq-extraction
description: 从外贸询盘邮件/文本抽取 canonical RFQ 结构化字段（材料/数量/表面处理/公差/尺寸/交期），标记缺失项。当用户提交询盘文本、需要把非结构化邮件转成可决策对象时调用。
version: 1
backend: services/intake.py:extract_rfq  (+ LLM 提议 via services/llm_planner.py:extract_rfq)
tool_contract:
  openai_function:
    name: rfq_extraction
    description: 抽取 RFQ 结构化字段
    parameters:
      type: object
      properties:
        email_text: {type: string, description: 询盘邮件正文}
      required: [email_text]
---

# rfq-extraction

## 何时用
收到一封/一段外贸询盘，需要转成 canonical RFQ。

## 输入 / 输出
- 入：`email_text`（字符串）
- 出：`{material, surface, quantity, dimensions_mm[], tolerance_grade, tolerance_mm, process, missing_information[]}`，字段归一到受控词表（6061/304/TC4…；阳极氧化/钝化…；IT4–IT10）。

## 契约与失败策略
- LLM 提议补全缺失字段，**正则+确定性值优先**（LLM 不覆盖已有值）。
- 缺关键项 → 填 `missing_information` → 下游验证升级 HITL，不臆造。
- LLM 离线 → 显式 MOCK，回退纯正则，结果确定。

## 示例
输入："quote 50 pcs 6061 aluminum brackets, 100x50x10mm, anodizing, IT7"
输出：`{material:6061, surface:阳极氧化, quantity:50, dimensions_mm:[100,50,10], tolerance_grade:IT7, missing_information:[]}`
