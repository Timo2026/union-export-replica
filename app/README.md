# Union Manufacturing Export Agent — 离线核心场景 Demo

黄金链（RFQ 邮件 → 报价 → 校验 → HITL/PASS/BLOCKED → 草稿回复）的**自包含离线演示包**。
确定性内核为 vendored（byte-identical），零网络、零 GPU、零外部服务依赖。

## 一键运行（核心场景）

```bash
# Windows / Linux / macOS 均可，仅需 Python 3.11+
pip install -r requirements.txt
python scripts/run_demo.py --offline
```

预期：控制台表格 6 条场景全部 `[OK]`，退出码 0，结果写入 `data/demo/demo_result.json`。

| 场景 | 结局 | 说明 |
|------|------|------|
| S1 | PASS | 标准 CNC 件自动批准 |
| S2 | PASS | 高价值件自动批准 |
| S3 | BLOCKED | 越权/不可承诺 → 拦截归档 |
| S4 | PASS | 另一 PASS 变体 |
| S5 | HITL | 触发人工复核 |
| M1 | HITL | 语音↔邮件公差冲突，系统不静默采纳任一方 |

## 飞轮 Demo（越报越准 · 租户隔离）

```bash
python scripts/run_flywheel_demo.py
```

预期：`{"all_ok": true, "samples_A": 3, "B_samples": 0, "sandbox_pass": true}`，退出码 0。
演示双层沙箱隔离（A 的报价历史绝不被 B 召回）+ 分级价格修正**提案**（COLD 5% / WARM 10% / HOT 15% 硬上限）。
铁律：飞轮只产证据与系数提案，**永不改确定性内核的 `final_price`**。

## 演示的铁律（真跑可见）

1. **数据不出本机**：所有发信 `auto_send=False`（仅草稿），无 SMTP/IMAP 真实外发。
2. **LLM 不定价**：报价由确定性内核计算，LLM 仅做抽取/推理，绝不改价；飞轮只提系数提案。
3. **人工在环**：HITL/BLOCKED 强制升级，不静默通过。

## 完整测试套件（可选，在源仓库跑）

```bash
python -m pytest tests/ -q   # 源仓库: 562 passed, 1 skipped
python -m pytest tests/test_flywheel.py -q   # 飞轮: 19 passed
```

## 目录

- `scripts/run_demo.py` — 核心场景入口
- `scripts/run_flywheel_demo.py` — 飞轮（越报越准 + 租户隔离）入口
- `adapters/timo_adapter.py` — 确定性报价内核（offline vendored）
- `services/flywheel/` — v6.2 飞轮包（租户解析 / 向量召回 / 分级修正 / 反应打标 / 闭环）
- `skills/` — 30 个 NemoClaw Skill（各带 SKILL.md + tool.py，含飞轮 4 skill）
- `openshell/` — 4 条策略（含 iron-rule-1 / local-only）
- `data/golden_scenarios.json` — 6 条演示场景数据

> 本包不含 `credentials.json` / `gmail_settings.json` / `*.sqlite3` / `tools/`（密钥、数据库与 6.4G 外部工具），符合"数据留在本地"铁律。
