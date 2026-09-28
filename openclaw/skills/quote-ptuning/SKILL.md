---
name: quote-ptuning
description: 【已停用，勿用于出价】CNC加工报价 P-Tuning 系统。价格不准（硬编码兜底、偏差 -80.9%~-95.5%）。唯一出价口径改为 unionskill-quote → 7862 /api/upload-step。
capabilities:
- name: generate_quote
  description: CNC加工报价计算 - P-Tuning精准报价系统
  parameters:
  - name: part_name
    type: string
    required: true
    description: 零件名称
  - name: material
    type: string
    required: true
    description: 材料(如6061-T6, 304不锈钢)
  - name: surface
    type: string
    required: true
    description: 表面处理(如阳极氧化黑)
  - name: quantity
    type: int
    required: true
    description: 数量
  output: 报价JSON
  invoke:
    type: cli
    command: /home/Developer/miniconda3/envs/lk-skills/bin/python /home/Developer/.openclaw/skills/quote-ptuning/scripts/quote.py
      {{{part_name}}} {{{quantity}}} {{{material}}} {{{surface}}}
  example: '{"part_name":"法兰","material":"6061-T6","surface":"阳极氧化黑","quantity":10}'
materials:
- 材料(如6061-T6
- 304不锈钢)
invoke:
  type: python_function
  module: quote-ptuning.scripts.main
  function: run
---

> ⛔ **已停用 (2026-09-25, TIMO 决策) — 勿用于出价。**
>
> 47 skill 实测中本系统对 5 个测试零件全部偏差 −80.9%~−95.5%，且其引用的机加工时文件路径不存在。
>
> **唯一出价口径**: `unionskill-quote` → `POST http://127.0.0.1:7862/api/upload-step`
> （连字符；`-F file=@x.step -F material=6061 -F surface=anodized -F tolerance=IT9 -F process=三轴CNC -F quantity=N`）。
> 价格取响应的 `quote` 子对象，并断言 `estimated_weight_kg` 与本地 BOM 一致（差 <0.01kg）。
