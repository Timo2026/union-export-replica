# MODELS — 模型清单（复刻用）

> **本仓库不含任何模型权重**（NVFP4 权重约 41G，且按 data-stays-local 不入库）。
> 下方为复刻所需的**精确模型名 / 获取方式 / 启动命令**。

## 1. 三个本地推理端点（vLLM，NVFP4）

| 角色 | HF 模型目录（挂在 `$HF_CACHE/hub/`） | 服务名 | 端口 | 说明 |
|------|--------------------------------------|--------|------|------|
| 主力多模态 | `models--nvidia--Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4` | `nemotron-omni-30b-a3b` | **8002** | any-to-any：视觉 + LLM + ASR 统一端点；`--reasoning-parser nemotron_v3` |
| 语义嵌入 | `models--nvidia--Nemotron-3-Embed-1B-NVFP4` | `nemotron-embed-1b` | **8011** | RAG 检索向量（query:/passage: 前缀） |
| 轻量回落 | `$HOME/inference/models/Qwen3-0.6B` | `qwen3-0.6b` | **8902** | Omni 离线时的 LLM 回落 lane |

> `$HF_CACHE` 默认 `~/nvidia/hf-cache`（节点实测 41G，含 `eagle3-nano-30b`、`hub`、`modules`、`xet`）。

## 2. 公共环境（离线）

```bash
export HF_HOME="$HF_CACHE" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
```

- vLLM 首次以 **NVFP4** 启动时，**FlashInfer 会 JIT 编译 NVFP4 内核**（cache-miss 时编译较慢，属正常）。
- 模型获取：在有网机器上从 Hugging Face 拉取后离线拷入，或设 `UEA_HF_CACHE` 指向已有缓存。

## 3. 快速启动（等价 `models/fetch_and_launch.sh`）

```bash
# 每个模型一条 vLLM serve；端口如上
PY="$HOME/miniconda3/envs/nemotron/bin/python"
export HF_HOME="$HF_CACHE" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

$PY -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 --port 8002 \
  --model "$HF_CACHE/hub/models--nvidia--Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4/files" \
  --served-model-name nemotron-omni-30b-a3b \
  --reasoning-parser nemotron_v3

$PY -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 --port 8011 \
  --model "$HF_CACHE/hub/models--nvidia--Nemotron-3-Embed-1B-NVFP4/files" \
  --served-model-name nemotron-embed-1b

$PY -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 --port 8902 \
  --model "${UEA_QWEN06_MODEL:-$HOME/inference/models/Qwen3-0.6B}" \
  --served-model-name qwen3-0.6b
```

> 生产编排（6 服务 tmux、幂等、采用已在监听者）见 [`../ops/node_services.sh`](../ops/node_services.sh)。

## 4. 阶跃星辰 StepFun（如实：回落位）

- **阶跃 StepFun（`stepfun-plan` / `step-5-preview`）仅作 fallback**；`STEPFUN_API_KEY` 在本地为**空**，未接线，data-stays-local 下**不主动出网**。本地 NVFP4 Nemotron 是唯一主力。
