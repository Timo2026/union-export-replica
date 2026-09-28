#!/usr/bin/env bash
# ============================================================
# 摩尔线程 MUSA 本地 vLLM 推理后端启动脚本（Linux，本项目当前主后端）
#
# 主服务 config/models.json 已配置以下本地端点（请勿改动端口）：
#   - http://127.0.0.1:32102/v1  (Qwen3-8B GPTQ , model_id=musachat_local)
#   - http://127.0.0.1:8000/v1   (Qwen2.5-7B GPTQ, model_id=qwen2.5-7b-gptq)
#
# 前置：
#   1. 已安装摩尔线程 MUSA 驱动 + MUSA 版 vLLM（vllm-musa）
#   2. 已下载对应 GPTQ/Int4 模型到 MODEL_PATH
#
# 用法示例：
#   MODEL_PATH=/data/models/Qwen2.5-7B-GPTQ-Int4 MODEL_NAME=qwen2.5-7b-gptq VLLM_PORT=8000 ./scripts/start_musa_vllm.sh
# ============================================================

set -euo pipefail

# ── 可配置参数（DRY：通过环境变量或在此处修改默认值）──
MODEL_PATH="${MODEL_PATH:-/path/to/Qwen3-8B-GPTQ-Int4}"
MODEL_NAME="${MODEL_NAME:-musachat_local}"
VLLM_PORT="${VLLM_PORT:-32102}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-2048}"
QUANT="${QUANT:-gptq}"

echo "======================================================="
echo "  摩尔线程 MUSA 本地 vLLM 推理后端"
echo "  服务端点 : http://127.0.0.1:${VLLM_PORT}/v1"
echo "  模型标识 : ${MODEL_NAME}"
echo "  上下文长 : ${MAX_MODEL_LEN}"
echo "======================================================="

# vLLM >= 0.6 亦可改为: vllm serve "$MODEL_PATH" --served-model-name "$MODEL_NAME" ...
exec python -m vllm.entrypoints.openai.api_server \
    --model "${MODEL_PATH}" \
    --served-model-name "${MODEL_NAME}" \
    --host 0.0.0.0 \
    --port "${VLLM_PORT}" \
    --max-model-len "${MAX_MODEL_LEN}" \
    --dtype auto \
    --quantization "${QUANT}"