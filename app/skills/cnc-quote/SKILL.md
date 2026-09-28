---
name: cnc-quote
description: 基于零件参数（材料/数量/尺寸/重量/表面积/公差/螺纹数）用确定性引擎产出报价（材料费+加工费+表面费+利润+交期）。当需要给出可溯源的 CNC 报价时调用。禁止用 LLM 生成价格数字。
version: 1
backend: adapters/timo_adapter.py:TimoAdapter.quote  (在线 :7862 /api/quote · 离线 import app.main_lite.calc_quote)
tool_contract:
  openai_function:
    name: cnc_quote
    description: 确定性 CNC 报价
    parameters:
      type: object
      properties:
        material: {type: string, enum: ["6061", "7075", "304", "316L", "TC4", "45钢", "Q235", "黄铜"]}
        quantity: {type: integer, minimum: 1}
        surface: {type: string}
        weight_kg: {type: number}
        max_dim_mm: {type: number}
        tolerance_grade: {type: string, enum: ["IT4", "IT5", "IT6", "IT7", "IT8", "IT9", "IT10"]}
      required: [material, quantity]
---

# cnc-quote

## 何时用
DFM 通过后，为 canonical RFQ 产出报价。**价格唯一权威来源**（铁律①：LLM 不生成数字）。

## 输入 / 输出
- 入：material/quantity/surface/weight_kg/max_dim_mm/tolerance_grade/thread_count/dims
- 出：`{unit_price, total_price, final_price, profit, lead_time_days, valid, conflicts, _source}`

## 契约与失败策略
- 在线优先 :7862；离线子进程 import 真实 `calc_quote`（**byte-identical**）。
- 每条价格带 `_source`（live:/api/quote 或 offline:calc_quote），可溯源。
- 单件超金额门禁 → 交 verification 升 HITL，不自动发。

## 示例
6061×50 anodizing IT7 → `unit_price 222.8, final_price 9413.3, profit 2172.3`（在线=离线一致）。
