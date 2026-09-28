---
name: reid-operating-system
description: "Reid决策操作系统 — 分诊台(Triage) + 协议执行(Protocol) 决策引擎。单模型×多角色，15s极速决策。工作/家庭双领域路由，价值观校准，拉闸干预。"
metadata:
  category: decision
  version: "1.0.0"
  dependencies:
    - python: ">=3.8"
    - requests
  triggers:
    - 决策
    - 怎么做
    - 怎么回
    - 想听听你的意见
    - Reid
    - 分诊
    - 协议执行
    - 垣钧
    - 工作决策
    - 家庭决策
---

# Reid 决策操作系统

## 概述

一套完整的决策操作系统，专为单模型环境设计。通过**分诊台→模板选择→协议执行**三层架构，用2次模型调用实现结构化、可行动的决策输出。

## 架构

```
用户输入 → 分诊台(1次, ~2s) → 协议执行(1次, 5-10s) → 结构化输出
             ↑ 路由判断          ↑ 模板匹配
             ↑ 信号检测          ↑ 价值观校准
                                ↑ 资产追问
```

## 用法

> 2026-09-25 修正死入口: 原「方式1」是 `openclaw skill reid-operating-system "..."` —— OpenClaw
> **没有** `skill` 子命令 (实测 `OpenClaw does not know the command "skill"`, 提示用
> `openclaw skills`), 而 `openclaw skills` 也只提供 check/info/list/search/workshop,
> **没有 run**, CLI 无法直接跑本 skill; 原「方式2」是 `echo ... | reid_engine.py` 裸管道 ——
> 实测 `Permission denied` (脚本 mode 644, 无可执行位, 必须显式带解释器)。
> 两式均为死入口, 已改为实测 exit 0 的形式。

```bash
# 方式1：参数输入（用 skill 声明的解释器，requests 只在 lk-skills 环境里有）
/home/Developer/miniconda3/envs/lk-skills/bin/python \
  ~/.openclaw/skills/reid-operating-system/scripts/reid_engine.py \
  --input "这个报价要不要接？"

# 方式2：管道输入（引擎从 stdin 读取，但脚本不可执行，须带解释器）
echo "Matt让我写周报，但我这周没什么进展" \
  | /home/Developer/miniconda3/envs/lk-skills/bin/python \
    ~/.openclaw/skills/reid-operating-system/scripts/reid_engine.py
```

## 自检

```bash
# 脚本式自检 (设计意图, ~5s; 勿用 pytest — 已修，见 tests/test_matrix.py)
/home/Developer/miniconda3/envs/lk-skills/bin/python \
  ~/.openclaw/skills/reid-operating-system/tests/test_matrix.py --quick
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REID_MODEL` | nemotron-omni-30b-a3b | 决策模型名（默认就是 30B Omni，不是 1.5B） |
| `REID_TIMEOUT` | 30 | 单次调用超时(秒) |
| `OLLAMA_HOST` | http://127.0.0.1:8002/v1 | 推理服务地址。**变量名是历史遗留**：本机 :8002 是 vLLM 的 OpenAI 兼容端点，不是 Ollama —— 探活用 `/v1/models`(200)，`/v1/api/tags` 返 404 |

## 领域支持

### 工作领域（择幂科技/Xometry Asia）
- 日报 / 深度研究 / 快速问答 / 会议纪要 / 汇报 / 沙盘 / 奇思
- 输出：A稳妥/B强硬/C止损 + 政治风险 + 话术 + 资产追问

### 家庭领域（垣钧成长/亲子/夫妻）
- 教育决策 / 情绪安全 / 家庭规划 / 健康红线
- 输出：温和版/效率版 + 关系风险 + 话术 + 长期启示

## 拉闸机制

当检测到以下信号时自动触发干预：
- 情绪化 → 拉回真实目标
- 犬儒倾向 → 保持清醒但不否定
- 控制冲动 → 理解对方立场
- 牺牲倾向 → 保护长期信用

## 与CEO决策引擎的关系

| 维度 | CEO决策引擎 | Reid OS |
|:----:|:-----------:|:-------:|
| 适用场景 | 多模型蜂群/五证，复杂技术决策 | 日常运营决策，单模型高效路由 |
| 模型 | 自动发现本地+云端 | 固定 nemotron-omni-30b-a3b (30B) |
| 耗时 | 3-10分钟 | 8-15秒 |
| 输出 | 多路径+投票 | 结构化A/B/C方案 |
| 标签 | 报价/策略/技术 | 工作/家庭/通用 |
