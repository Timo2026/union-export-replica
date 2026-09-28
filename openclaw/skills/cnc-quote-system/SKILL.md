---
name: cnc-quote-system
description: "【已停用，勿用于出价】CNC智能报价系统。价格不可信（实测同件与 opc-fusion-quote 差 17.9 倍，自身告警价格偏低）。唯一出价口径改为 unionskill-quote → 7862 /api/upload-step。"
metadata:
  category: manufacturing
  source: OpenClaw-CNC-Skills
  triggers:
    - CNC报价
    - 零件报价
    - 制造报价
    - 材料成本
    - 加工费
---

# cnc-quote-system

> ⛔ **已停用 (2026-09-25, TIMO 决策) — 勿用于出价。**
>
> 47 skill 实测：同件 `AL6061 100×50×20×10` 本系统报 ¥57.13，与 `opc-fusion-quote` 的 ¥1020.30 差 17.9 倍，
> 且本系统自身告警「价格偏低，建议复核」。
>
> **唯一出价口径**: `unionskill-quote` → `POST http://127.0.0.1:7862/api/upload-step`
> （连字符；`-F file=@x.step -F material=6061 -F surface=anodized -F tolerance=IT9 -F process=三轴CNC -F quantity=N`）。
> 价格取响应的 `quote` 子对象，并断言 `estimated_weight_kg` 与本地 BOM 一致（差 <0.01kg）。

**Category:** manufacturing

CNC智能报价系统 - 基于RAG的制造零件报价工具。支持材料检索、成本估算、风险预警。当用户需要CNC零件报价、制造成本估算或知识库检索时使用此技能。

## Usage

To use this CNC manufacturing skill:

1. Identify the manufacturing parameters (material, dimensions, quantity, surface treatment)
2. Execute the skill's main script or function
3. Review the generated quote/report

## Bundled Scripts

The following scripts are available in the `scripts/` directory:

- `cnc_quote_engine.py` - Executable component
- `hybrid_retriever.py` - Executable component
- `case_retriever.py` - Executable component
- `risk_control.py` - Executable component

To execute a script:
```bash
python scripts/cnc_quote_engine.py
```

## Configuration & Assets

Available configuration and asset files:

- `config.json`
- `cases.json`
- `requirements.txt`

