---
name: batch-quote
description: 对 BOM 表（xlsx/csv）逐行跑黄金链批量报价，STEP 资产按物料编码前缀匹配走几何定价，产出汇总统计与报告。当需要一次报几十/几百个零件（如 400+ 常规机加工件）时调用。重批任务必须串行（内核桥限制）。
version: 1
iron_rule: deterministic
backend: scripts.batch_quote:bom_rows+quote_bom+summarize
tool_contract:
  openai_function:
    name: batch_quote
    description: BOM 批量报价 (确定性引擎逐行)
    parameters:
      type: object
      properties:
        action: {type: string, enum: [quote_bom]}
        bom_path: {type: string, description: BOM xlsx/csv (强制绝对路径)}
        assets_dir: {type: string, description: STEP/PDF 资产目录}
        customer_id: {type: string}
        out_path: {type: string, description: 报告落盘路径 (可选)}
      required: [action, bom_path]
---

# batch-quote

## 何时用
一张 BOM 多零件行、需要整表报价时。**不重写报价逻辑** —
委托 `scripts/batch_quote.py`（parse_spec → quote_bom → 每行走 CAT 黄金链 → HITL 闸门）。

## 输入 / 输出
- 入：`bom_path`（必填）/ `assets_dir`（STEP 命中则几何定价，否则文本估算）/ `customer_id`
- 出：`{ok, summary: {n_rows, n_quoted, n_with_step, quote_rate, sum_total}, report_path?}`

## 契约与失败策略
- `bom_path`/`assets_dir` 强制 `Path.resolve()`（内核桥 cwd=engine_src，相对路径必崩）。
- 每行结果 state=HITL — 批量报价永远过人工复核，不自动外发。
- 重 STEP 批任务禁止并发（内核桥串行铁律）；本 skill 一次只服务一个批。
- 报告落 data/（gitignored，data-stays-local）。

## 示例
`run(action="quote_bom", bom_path="C:/.../常规机加工件BOM.xlsx", assets_dir="C:/.../steps", customer_id="JIEVO")`
→ 410 行实证 summary `{quote_rate: 1.0, sum_total: 920054.82}`。
