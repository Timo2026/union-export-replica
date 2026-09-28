---
name: dfm-analysis
description: Analyze manufacturability/DFM risk for mechanical parts. Use when users ask 能不能加工、有没有工艺风险、DFM、薄壁、深孔、内角R、公差、表面处理风险. Provides conservative rule-based checks via scripts/dfm_check.py; complex drawings still require human/advanced review.
---

# DFM Analysis

Use the deterministic checker first for basic manufacturability risks:

```bash
/home/<user>/.miniconda/bin/python3 ~/.openclaw/skills/dfm-analysis/scripts/dfm_check.py --input "6061铝合金薄壁件，壁厚0.8mm，孔径10mm，孔深80mm" --json
```

## Scope
- Thin wall limits: aluminum ≥1.5mm, steel ≥3mm, titanium ≥4mm.
- Deep holes: depth/diameter >5 warns; >8 high risk.
- Small inner radius: R<1mm warns.
- Tight tolerance: around ±0.02mm warns.
- Surface treatment: reminds about masking, thickness compensation, and inspection.

## Boundaries
- Rule-based triage only; does not certify final manufacturability.
- For STEP/PDF drawings, combine this with geometry extraction or human review.
- If key fields are missing, ask for material, wall thickness, hole diameter/depth, tolerance, quantity, and surface treatment.
