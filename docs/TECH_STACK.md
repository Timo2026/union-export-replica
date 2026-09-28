# TECH STACK — 技术栈（NVIDIA 全栈 × StepFun 如实定位）

评分维度「平台适配性（DGX Spark / NVIDIA 技术栈 / StepFun 模型）」要求列明所用 NVIDIA SDK/模型
与 StepFun 阶跃星辰模型。以下**如实**列明：仅写节点上真实在用/真实存在的组件，不做无依据宣称。

## NVIDIA 技术栈（本地算力，当前在用）

| 层 | 组件 | 版本/口径 |
|----|------|-----------|
| 硬件/系统 | NVIDIA DGX Spark（GB10，128GB 统一内存），DGX OS 7.2.3 | 驱动 580.82.09，CUDA 13.0 |
| 模型 | `nemotron-omni-30b-a3b`（any-to-any 视觉+LLM+ASR） | NVFP4，`:8002` |
| 模型 | `nemotron-embed-1b`（非对称双塔 RAG 嵌入） | NVFP4，`:8011` |
| 模型 | `Qwen3-0.6B`（轻量辅助） | `:8902` |
| 推理服务 | vLLM OpenAI 兼容端点 + `--reasoning-parser nemotron_v3` | conda `envs/nemotron` |
| 量化/内核 | NVFP4 + FlashInfer JIT 构建 NVFP4 kernel | 缓存未命中时即时构建 |
| 护栏 | NeMo Guardrails（`nemo_soft`；未装则自动降级 `builtin`） | `config` 可切 |
| 检索 | 分层 RAG（Embed-1B + file 向量后端） | `services/rag_layers.py` |
| 确定性内核 | Timo CNC-AI-Brain（T4 目标，Timo 引擎） | `:7862`，**无 LLM 定价** |

## StepFun 阶跃星辰（如实：fallback 位，未接入、不出网）

按节点 `node_bootstrap.ipynb` 与 `timo.env` 的实际设计：

- 定位：**本地 Omni-30B 为主（primary），StepFun 阶跃星辰留作 OpenClaw 侧 fallback 位（D2）**。
- 接入状态：`timo.env` 中 `STEPFUN_API_KEY=''`（**空，未配置**）；遵循 `data-stays-local`，
  笔记本**不配置任何云端外发**，故 StepFun 当前**未接入、未出网**。
- 相关工具链（本地存在，供参赛者/复现使用）：`.stepcode`（阶跃星辰编码 CLI，`bin/step`）、
  `.steppage-mcp`（阶跃 MCP 服务 `steppage-mcp.mjs`）、插件 `steppage`。
- 铁律：即便未来接入 fallback，也只限 OpenClaw 提议层，**最终价格仍由本地确定性内核裁决**，不变铁律①。

> 交付如实性原则：本节不把 StepFun 写成"在用"。比赛中如需"StepFun 模型"一项，
> 我们以"fallback 位 + 阶跃工具链在场 + 数据不出境封装"如实呈现，而非伪造在线调用。

## 合规与治理

- `egress.allow=false`（SMTP/Webhook/IMAP 全 DENY），邮件仅草稿 —— data-stays-local。
- `tool_allowlist_enforced=true`，guardrails 输入阻断（prompt_injection / data_exfiltration / 等）。
