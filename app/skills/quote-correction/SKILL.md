---
name: quote-correction
description: 对确定性引擎报价做 L2 历史锚点矫正（win/lost 召回 + 价带 + 分级封顶 ±5/10/15%），产出矫正提案与 sha 审计链。当报价需参考同客户历史成交价、且允许人工复核时调用。提案非终价 (proposal-only)。
version: 1
iron_rule: deterministic
backend: scripts.quote_correction:correct_quote_with_l2
tool_contract:
  openai_function:
    name: quote_correction
    description: L2 锚点矫正提案 (不改引擎权威价)
    parameters:
      type: object
      properties:
        action: {type: string, enum: [correct]}
        engine_quote: {type: object, description: 含 unit_price/context_id 的引擎报价}
        query: {type: string, description: 检索语料 (材料+表面+公差描述)}
        customer_id: {type: string, description: 租户过滤 (防跨客户泄漏)}
      required: [action, engine_quote, query, customer_id]
---

# quote-correction

## 何时用
黄金链出引擎价后，想参考该客户历史成交价带做**矫正提案**时。**复用 v6.2 PriceCorrector
+ scripts.quote_correction 轮子**，不另建矫正器。

## 输入 / 输出
- 入：`engine_quote` / `query` / `customer_id`
- 出：`{ok, proposal_only: true, correction: {...含 applied 信号与 sha 审计链}}`

## 契约与失败策略
- **proposal-only（铁律①）**：矫正结果绝不回写 unit_price 权威值；终价必经人工核。
- L2 无召回锚点 → `{ok: false, reason: "no_anchor"}` 诚实空转，不用假数据凑。
- D4 实证挂账：引擎价=几何成本价、PO=成交价（口径差 ~38%），MAPE 矫正无改善 —
  本 skill 输出仅供人工参考。
- L2 召回自带零价锚点过滤 + exclude_prefix 防自评泄漏（LOO）。

## 示例
`run(action="correct", engine_quote={unit_price: 222.8}, query="6061 阳极氧化 IT7", customer_id="JIEVO")`
→ `{ok: true, proposal_only: true, correction: {applied: ["price_band_pull"]}}`
