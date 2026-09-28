---
name: supplier-match
description: 在客户确认订单后，对 RFQ（材料/工艺/数量/交期/公差）按材料/工艺/交期/产能/质量/评分/地区多维标签打分，从 data/suppliers.sqlite3 选最优 Top3 加工厂并打分（不打真实价格）。当需要把已确认订单分派给候选外协商时调用。
version: 1
backend: supplier_module.supplier_db + supplier_module.matcher
tool_contract:
  openai_function:
    name: supplier_match
    description: 标签打分 Top3 供应商匹配
    parameters:
      type: object
      properties:
        rfq:
          type: object
          description: RFQ 字段（material/processes/quantity/promised_lead_time_days/tolerance_grade/destination_region）
        top_n:
          type: integer
          description: 返回 Top N（默认 3，上限 5）
      required: [rfq]
---

# supplier-match

## 何时用
客户已确认（customer_confirmed=true）进入供应商履约流水线；要从 `data/suppliers.sqlite3` 选 TopN 加工厂做后续询价/PO。**不**用于客户面前报价——客户侧价格由 `cnc-quote` 给出。

## 输入 / 输出
- 入：`rfq`（material/processes/quantity/promised_lead_time_days/tolerance_grade/destination_region）+ 可选 `top_n`（默认 3）
- 出：`[(score, supplier_dict), ...]` — 每个 supplier_dict 含 id/name/region/processes/materials/capacity_per_month/lead_time_days/quality_grade/rating/contact_email/contact_phone

## 契约与失败策略
- 7 维加权打分：材料命中 +3、工艺命中 +2、交期满足、产能充足、质量等级、评分线性、地区一致
- 同分按 supplier id 升序（确定性）
- 严格小于阈值（features_count<10 && route<10）才走 AUTO；其余走人工复审（叠加非替换）
- 真几何相似度（shape signature）未实现，标签打分足够 v2.3.0 演示；embedding 列 roadmap

## 隐私
- 标签打分只用技术字段（材料/工艺/数量/交期/公差），不含客户 PII
- 与 `desensitize` 配合：选出的供应商后续接收的是脱敏 ZIP，**不**是 RFQ 原文件

## backend 路径
- `supplier_module/supplier_db.py`（init_suppliers_db / list_suppliers / filter_by_capability）
- `supplier_module/matcher.py`（score_supplier / match_top_n）
- `data/suppliers.sqlite3`（10 家种子：domestic/asia/europe/north_america）