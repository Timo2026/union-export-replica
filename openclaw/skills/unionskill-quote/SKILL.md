---
name: unionskill-quote
description: |
  UnionSkill CNC报价技能 — API驱动的智能报价单生成工具。
  通过调用OPC API完成报价计算、DFM检查、工艺对齐，生成专业报价单。
  支持STEP 3D模型生成（依赖pythonOCC）。
  触发词: "报价","quote","CNC报价","报价单","多少钱","价格","cost","price","加工费"
---

# UnionSkill Quote — CNC智能报价技能

> ⚠️ **本技能依赖OPC API服务器，不能独立运行。** 所有报价计算由远端API完成。

## 架构

```
用户输入(NL) → OPC API /v1/parse → 结构化参数
                                    ↓
                              OPC API /v1/quote → 价格
                                    ↓
                              OPC API /v1/dfm → DFM检查
                                    ↓
                              OPC API /v1/chat → 工艺建议
                                    ↓
                              生成报价单 (HTML/JSON)
                                    ↓
                    (可选) pythonOCC → STEP 3D模型
```

## API配置

| 环境 | Base URL | 用途 |
|------|----------|------|
| **生产(默认)** | `http://127.0.0.1:8002/v1` | 域名访问 |
| **直连(备用)** | `http://127.0.0.1:7862/api` | IP直连 |
| **本地开发** | `http://127.0.0.1:8002/v1` | 本地调试 |

- **API Key:** `local-noauth
- **模型:** `nemotron-omni-30b-a3b`

通过环境变量 `OPC_API_URL` 切换，默认 `http://127.0.0.1:8002/v1`

## 安装

```bash
# 自动安装依赖（pythonOCC + requests）
bash scripts/setup.sh
```

## 使用

### CLI模式
```bash
# 自然语言报价
python3 scripts/quote_skill.py "AL6061 100x50x20 10件 阳极氧化"

# 结构化报价
python3 scripts/quote_skill.py -m AL6061 -l 100 -w 50 -H 20 -q 10 --surface "阳极氧化本色"

# 输出JSON
python3 scripts/quote_skill.py "AL6061 100x50x20" --json

# 生成报价单HTML
python3 scripts/quote_skill.py "AL6061 100x50x20 5件" --sheet

# 生成STEP 3D模型（需要pythonOCC）
python3 scripts/quote_skill.py "AL6061 100x50x20" --step
```

### API调用模式（供其他skill调用）
```python
from quote_skill import UnionSkillQuote
usq = UnionSkillQuote()
result = usq.quote("AL6061 100x50x20 10件")
# → {unit_price, total_price, breakdown, dfm, advice, sheet_html}
```

## 输出格式

### 报价单包含
- 零件信息（材料、尺寸、数量）
- 工艺路线（CNC/线切割/放电等）
- 价格明细（材料费、加工费、表面处理费、测量费）
- DFM可制造性分析
- 交期估计
- 3D预览（可选）

## 依赖

| 依赖 | 用途 | 必须? |
|------|------|-------|
| requests | API调用 | ✅ 必须 |
| pythonOCC | STEP 3D生成 | ❌ 可选 |
| jinja2 | 报价单模板 | ❌ 可选( fallback到字符串模板) |

## 故障转移

1. `127.0.0.1` 不可达 → 自动切换 `127.0.0.1`
2. API完全不可达 → 提示用户检查服务器
3. pythonOCC未安装 → 跳过3D，仍输出报价单
