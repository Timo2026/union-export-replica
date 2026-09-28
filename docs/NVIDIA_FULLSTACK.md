# NVIDIA FULLSTACK — 全栈与本项目的融合详解

> 本文件把「NVIDIA 全栈」逐层映射到本项目的一个具体行业问题——**AI 制造询报价**。
> 全部指标为**节点实测**（见 [`REAL_STATE.md`](REAL_STATE.md)）或来自运行配置，非营销口径。

## 硬件底座 → 为什么要 GB10

询报价智能体需要**四类负载同驻一机且互不冲突**：
1) 多模态大模型（看图 + 理解询盘 + 语音）——**吃显存/吞吐**；
2) 语义检索 Embedding——**吃显存**；
3) CAD 几何（cadquery/OCP/trimesh）——**吃 CPU/内存**；
4) 确定性计价内核（Timo）——**吃 CPU，要求可复现**。

**GB10 的 ≈128GB 统一内存**让这四类负载在一台桌面级机器上共存，这是"数据不出本机"还能跑全链路的前提。
实测：GPU ≈96%、显存 ≈74GB、内存 ≈99GiB/121GiB、CPU 基本闲置——瓶颈在 GPU（好事，说明算力喂饱）。

## 推理栈 → vLLM × NVFP4

| 环节 | 实现 | 实测/配置 |
|------|------|-----------|
| 服务框架 | **vLLM**，多 `VLLM::EngineCore` 实例 | 三端点：Omni :8002 / Embed :8011 / Qwen06 :8902 |
| 量化 | **NVFP4** | 4-bit 浮点，Blackwell 原生支持 |
| 内核 | **FlashInfer JIT** NVFP4 kernels | cache-miss 时 JIT 编译（首次启动较慢属正常） |
| 多模态 | Omni-30B `--limit-mm-per-prompt {"video":1,"image":1,"audio":1}` | any-to-any：一份权重吃图/文/音 |
| 推理链解析 | `--reasoning-parser nemotron_v3` | 把模型的思考链与最终答案分离 |
| 工具调用 | `--enable-auto-tool-choice --tool-call-parser qwen3_coder` | 让模型能调工具 |
| KV 复用 | `--enable-prefix-caching` | 复用长系统提示前缀 |

> 关键工程细节：Omni `--max-model-len` 必须 ≤ 模型真实 `max_position_embeddings (262144)`；`--max-num-batched-tokens 16384`
> 避免长 prefill 被切 40+ 片导致 agent 超时；`repetition_penalty=1.05` 覆盖默认 1.0 以防 agent 复读。

## 模型层 → Nemotron 家族

| 模型 | 作用 |
|------|------|
| **Nemotron-3-Nano-Omni-30B-A3B（NVFP4）** | 主力：视觉(图纸/照片)+语言(询盘)+语音(ASR) 统一端点 |
| **Nemotron-3-Embed-1B（NVFP4）** | RAG：询盘/物料/工艺知识检索（query:/passage: 前缀） |
| **Qwen3-0.6B** | Omni 离线时的轻量 LLM 回落 lane（只求不 MOCK） |
| **NeMo Guardrails** | 询盘软护栏（越界/敏感分流，`nemo_soft`） |

## Skills 层 → 把全栈能力"沉淀为可复用 Agent 技能"

这是**融合的真正落点**：模型侧优化不止于"跑得快"，而被封装成 `.openclaw/skills/` 里的
NVIDIA 栈技能（`nemotron-customize`、`nemo-mbridge-perf-memory-tuning`、`jetson-speculative-decoding`、
`jetson-optimize-memory`、`dynamo-troubleshoot`、`tilegym-cutile-python`、`nemo-retriever`…），
供智能体在需要时调用，**反向降低时延与显存**。详见 [`SKILLS.md`](SKILLS.md)。

## 黄金闭环（全栈如何串起来）

```
图纸/询盘/语音
   │  Nemotron-Omni (视觉+语言+ASR, NVFP4, :8002)
   ▼
步骤/意图/规格抽取  ── Nemotron-Embed (:8011) 召回工艺/物料知识
   │
   ▼
OpenClaw 编排 (Skills 分发, iron_rule 分级 / openshell 护栏)
   │  LLM 只提议，不定价
   ▼
Timo 确定性内核 (:7862, sha256 锁定铁律①)  → 唯一价格权威
   │
   ▼
报价草稿 (egress DENY, 只草稿不发送)
```

**一句话**：GB10 提供统一内存底座，vLLM+NVFP4 把 Nemotron 跑成 450 tok/s 的多模态引擎，
Skills 把模型优化沉淀为智能体能力，确定性内核守住"LLM 不定价"的工业底线，数据全程不出本机——
这就是本项目与 NVIDIA 全栈的融合。
