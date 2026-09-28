---
name: freight-customs
description: 计算 P1 商业落地成本（landed cost）：运费 + 关税 + Incoterms 费率分摊。基于确定性费率表（config/commercial.yaml），不调 LLM。当需要给报价叠加跨境物流/关税成本时调用。
version: 1
backend: services/commercial.py:compute_commercial
iron_rule: deterministic
tool_contract:
  openai_function:
    name: freight_customs
    description: 计算运费/关税/Incoterms 落地成本
    parameters:
      type: object
      properties:
        quote:
          type: object
          description: cnc-quote 输出（含 unit_price / total_price / final_price）
        rfq:
          type: object
          description: RFQ 字段（含 quantity / destination_country）
        cfg:
          type: object
          description: config/commercial.yaml 加载的费率表
        destination_country:
          type: string
        shipping_mode:
          type: string
          enum: [sea, air, land]
        incoterm:
          type: string
          enum: [EXW, FOB, CIF, DDP]
      required: [quote, rfq, cfg]
---

# freight-customs

## 何时用
客户要跨境交付（有 destination_country / Incoterm）时，在出厂价上叠加运费/关税。

## 输入 / 输出
- 入：`quote` + `rfq` + `cfg`（费率表）+ 可选 `destination_country/shipping_mode/incoterm`
- 出：`{incoterm, landed_cost, seller_quote_price, total_lead_time_days, breakdown{freight, customs, ...}, _source}`

## 契约与失败策略
- 费率全部来自 `config/commercial.yaml`，**确定性**，无 LLM 介入。
- 国家→地区映射缺失 → 回退 `region: "rest_of_world"` 费率，并在 breakdown 标 `assumed`。
- **铁律①**：landed_cost 数字由本函数权威，LLM/Dispatcher 不得改写。

## 示例
FOB + sea + 6061×50 → `landed_cost: 10230.5, breakdown: {factory: 9413, freight: 580, customs: 237}`。
