---
name: cnc-risk-guardian
description: "CNC Risk Guardian - 智能报价守卫系统"
---

# CNC Risk Guardian - 智能报价守卫系统

## 功能
集成了10大组件的CNC报价全链路管线：
- **ModelRouter** — Ollama→DeepSeek→规则引擎三级降级推理
- **HardGuard** — 材料/表面/热处理/壁厚/公差/热力6类硬规则
- **DecisionLedger** — SQLite审计账本，可追溯每次决策
- **ArtifactHash** — SHA-256工件溯源，防篡改
- **ResourceGuard** — 训练/推理自动切换，系统资源保护
- **QuoteReview** — 双Agent交叉验证报价合理性
- **EvidenceRAG** — PDF文件/标准溯源
- TrainingRecipe — MiniCPM-1B LoRA训练配方

## 触发条件
- CNC报价、风险评估、报价守卫、工艺检查
- 用户发送 STEP/PDF/DWG 文件要求报价审核

## 目录结构
```
scripts/
  cnc_quote_pipeline_v2.py  # 全链路主管线 (236行)
  model_router.py            # 三级降级路由器 (186行)
  rule_guardian.py           # 硬规则守卫 (167行+115行YAML)
  decision_ledger.py         # SQLite审计账本 (244行)
  resource_guard.py          # 资源守护进程 (214行)
  artifact_hash.py           # SHA-256溯源 (104行)
  quote_review.py            # 多Agent交叉验证 (81行)
  evidence_rag.py            # PDF证据溯源 (87行)
rules/
  cnc_constraints.yaml       # 6类约束规则 (115行)
data/
  decision_ledger.db         # 审计数据库
```

## 使用示例
```bash
# 全链路报价 (7个真实STEP自动处理)
python3 scripts/cnc_quote_pipeline_v2.py

# 硬规则检查
python3 scripts/rule_guardian.py

# 审计查询
python3 scripts/decision_ledger.py query

# 多Agent交叉验证
python3 scripts/quote_review.py

# PDF溯源
python3 scripts/evidence_rag.py
```

## 集成
被其他Skill导入:
```python
from cnc-risk-guardian.scripts.model_router import ModelRouter
router = ModelRouter()
result = router.route("6061铝合金阳极氧化100件报价")
```

## 依赖
- Python 3.12+
- Ollama + qwen2.5:1.5b
- SQLite3 (内置)
