#!/usr/bin/env bash
# models/fetch_and_launch.sh — 复刻三路本地 vLLM 推理端点（NVFP4，离线）
#
# 忠实复刻自运行节点 ops/node_services.sh 的 _run_embed/_run_qwen06/_run_omni。
# 本脚本不下载权重（data-stays-local）：权重须已在 HF 离线缓存中，见 MODELS.md。
#
# 用法:
#   bash models/fetch_and_launch.sh [embed|qwen06|omni|all|check]
#     all   : 后台依次拉起三个端点（默认）
#     check : 只探活三个端点 /health 即返回
#     embed/qwen06/omni : 只拉起对应端点（前台，配合 tmux 更佳）
set -euo pipefail

NVIDIA_DIR="${NVIDIA_DIR:-$HOME/nvidia}"
HF_CACHE="${UEA_HF_CACHE:-$NVIDIA_DIR/hf-cache}"
NEMOTRON_PY="${NEMOTRON_PY:-$HOME/miniconda3/envs/nemotron/bin/python}"

# 离线环境（与节点一致）
export HF_HOME="$HF_CACHE" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

OMNI_REPO="models--nvidia--Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4"
EMBED_REPO="models--nvidia--Nemotron-3-Embed-1B-NVFP4"
QWEN06="${UEA_QWEN06_MODEL:-$HOME/inference/models/Qwen3-0.6B}"

launch_embed() {
  cd "$NVIDIA_DIR"
  exec "$NEMOTRON_PY" -m vllm.entrypoints.openai.api_server \
    --model "$HF_CACHE/hub/$EMBED_REPO/files" \
    --served-model-name nemotron-embed-1b \
    --runner pooling --convert embed \
    --max-model-len 8192 --max-num-seqs 64 \
    --gpu-memory-utilization 0.15 \
    --host 127.0.0.1 --port 8011 --trust-remote-code
}

launch_qwen06() {
  cd "$NVIDIA_DIR"
  # C4 fallback lane: bf16 ~1.5G; util 0.06 已远大于权重+激活需求。仅求 Omni 离线时
  # 能出"低质但真实"的续写（不 MOCK）。不加 reasoning-parser。
  exec "$NEMOTRON_PY" -m vllm.entrypoints.openai.api_server \
    --model "$QWEN06" \
    --served-model-name qwen3-0.6b \
    --max-model-len 32768 --max-num-seqs 16 \
    --gpu-memory-utilization 0.06 \
    --host 127.0.0.1 --port 8902 --trust-remote-code
}

launch_omni() {
  cd "$NVIDIA_DIR"
  # max-model-len <= 模型真实 max_position_embeddings (262144)。
  # 16k batched tokens 避免长 prefill 被切成 40+ 片导致 agent 超时。
  # repetition_penalty: 覆盖 generation_config 的 1.0（防止 agent 逐字复读上一轮骨架）。
  exec "$NEMOTRON_PY" -m vllm.entrypoints.openai.api_server \
    --model "$HF_CACHE/hub/$OMNI_REPO/files" \
    --served-model-name nemotron-omni-30b-a3b \
    --reasoning-parser nemotron_v3 \
    --max-model-len 262144 --max-num-batched-tokens 16384 --max-num-seqs 32 \
    --limit-mm-per-prompt '{"video":1,"image":1,"audio":1}' \
    --gpu-memory-utilization 0.55 \
    --override-generation-config '{"repetition_penalty": 1.05}' \
    --enable-prefix-caching --trust-remote-code \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --host 127.0.0.1 --port 8002
}

check() {
  for p in 8002 8011 8902; do
    if curl -fsS "http://127.0.0.1:$p/health" >/dev/null 2>&1 || \
       curl -fsS "http://127.0.0.1:$p/v1/models" >/dev/null 2>&1; then
      echo "  :$p  UP"
    else
      echo "  :$p  DOWN"
    fi
  done
}

case "${1:-all}" in
  embed)   launch_embed ;;
  qwen06)  launch_qwen06 ;;
  omni)    launch_omni ;;
  check)   echo "端点探活:"; check ;;
  all)
    echo "在后台拉起三个 vLLM 端点（日志 /tmp/uea-vllm-*.log）..."
    nohup "$0" embed  > /tmp/uea-vllm-embed.log  2>&1 &
    nohup "$0" qwen06 > /tmp/uea-vllm-qwen06.log 2>&1 &
    nohup "$0" omni   > /tmp/uea-vllm-omni.log   2>&1 &
    echo "已拉起。稍候片刻后运行 'bash models/fetch_and_launch.sh check' 探活。"
    echo "提示：生产请用 tmux（参照 ops/node_services.sh）以便守护与重启。"
    ;;
  *) echo "用法: $0 [embed|qwen06|omni|all|check]" >&2; exit 2 ;;
esac
