#!/usr/bin/env bash
# node_services.sh — idempotent 6-service supervisor for the union-export agent
# stack on the GB10 spark node (121Gi unified memory, SM 12.1).
#
# It ADOPTS any service already listening on its port and (re)launches only what
# is missing, inside named tmux sessions, serially, behind a memory floor and a
# global lock so the co-resident vLLM servers never OOM the box.
#
# Launch order == dependency order. livekernel is LAST on purpose: its
# ModelRouter._probe caches endpoint liveness (10s TTL since the 2026-09-22
# probe-cache fix), so every backend it routes to should already be up — a cold
# router would otherwise report stale offline until the TTL expires.
#
# 2026-09-22 pivot (user 拍板「放弃 30B, 全部接 Omni 30B」): reason30b :8000 除名 —
# Omni 与 30B 同代同宗但 unified-memory 不可共存 (30B 任何 util 配方 KV cache
# 分配期 crash-loop, watchdog 22 次重启)。驻留收缩为 Omni 唯一推理端点。
#
# 2026-09-26 C4 (user 拍板 A「恢复 0.6B fallback 链」): qwen06 :8902 加入 —
# Omni 单点无降级是模型设置页巡检 P1 项; LLMPlanner/ModelRouter 已接线
# (primary 离线 → fallback, TTL 重探, source=fallback 诚实标注), 本服务是
# 该链的落点。0.6B bf16 权重 ~1.5G, gpu-util 0.06, 对 unified memory 压力可忽略。
# 注意其 chat 为原生 OpenAI 协议 (非 :8901 shim 的 /generate 转译; shim 是
# OpenClaw 临时件, upstream 现坏 405, 不属本链 — 退役处置见 OpenClaw 线)。
#
#   embed      :8011  nemotron-embed-1b       RAG embeddings (pooling)
#   qwen06     :8902  Qwen3-0.6B              LLM fallback lane (Omni 离线时顶班)
#   omni       :8002  nemotron-omni-30b-a3b   any-to-any vision + LLM + ASR (统一推理端点)
#   timo       :7862  cnc-ai-brain            deterministic quote engine (no LLM pricing)
#   searxng    :8080  searxng (loopback)      meta-search for /v1/web/search lane
#   livekernel :8888  union-export-agent      FastAPI orchestrator (public via NAT)
#
# Secrets / node coords: NONE live here. Per-service environment is sourced from
# chmod-600 files under $UEA_DEPLOY_DIR (default ~/union-deploy) that are captured
# on-node and never exported. The node's public IP/SSH port live only in the
# operator's local env, never in this file (loopback binds only).
#
# Usage:
#   node_services.sh status             report all 6 (UP/DOWN, tmux-managed?), no mutation
#   node_services.sh start <svc|all>    idempotent: launch only what is down
#   node_services.sh restart <svc>      force stop+start one service
#   node_services.sh stop <svc|all>     stop tmux session and free the port
#   node_services.sh _run <svc>         INTERNAL: foreground launch (run by tmux)
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"

NVIDIA_DIR="${UEA_NVIDIA_DIR:-$HOME/nvidia}"
DEPLOY_DIR="${UEA_DEPLOY_DIR:-$HOME/union-deploy}"
LOG_DIR="${UEA_LOG_DIR:-$NVIDIA_DIR/logs}"
LOCK_FILE="$DEPLOY_DIR/.services.lock"
HF_CACHE="${UEA_HF_CACHE:-$NVIDIA_DIR/hf-cache}"
NEMOTRON_PY="${UEA_NEMOTRON_PY:-$HOME/miniconda3/envs/nemotron/bin/python}"
OCC_PY="${UEA_OCC_PY:-$HOME/miniconda3/envs/occ/bin/python}"
TIMO_DIR="${UEA_TIMO_DIR:-$HOME/timo_engine}"
LK_DIR="${UEA_LK_DIR:-$HOME/timo_livekernel}"
SEARXNG_DIR="${UEA_SEARXNG_DIR:-$HOME/searxng}"
SEARXNG_PY="${UEA_SEARXNG_PY:-$HOME/miniconda3/envs/searxng/bin/python}"
MEM_FLOOR_GB="${UEA_MEM_FLOOR_GB:-6}"
READY_TIMEOUT="${UEA_READY_TIMEOUT:-300}"
# 轮转保留几代服务日志。0 = 旧行为(截断)。默认 5: 一次崩溃与前 4 次
# 重启的栈都还在，watchdog 拉起死掉的服务后仍有证据可查 —— 崩溃发生在
# 重启后第一秒，而旧代码的 `: > log` + tmux `>` 双截断正好把它抹掉。
# (2026-09-25 livekernel 15:22:58 / 15:48:15 两次不明重启就是这么查不出原因的)
LOG_KEEP="${UEA_LOG_KEEP:-5}"

SERVICES_ALL="embed qwen06 omni timo searxng livekernel"

mkdir -p "$LOG_DIR" "$DEPLOY_DIR"
# FlashInfer JIT-builds NVFP4 kernels on cache-miss; that build shells out to
# ninja (conda env bin) and nvcc (system CUDA). A bare tmux shell has neither,
# which kills the EngineCore during profile_run. Put both on PATH for every
# vLLM launch below.
export PATH="$(dirname "$NEMOTRON_PY"):/usr/local/cuda/bin:$PATH"

port_of() {
  case "$1" in
    embed) echo 8011 ;; qwen06) echo 8902 ;; omni) echo 8002 ;;
    timo) echo 7862 ;; searxng) echo 8080 ;; livekernel) echo 8888 ;; *) echo "" ;;
  esac
}

port_up() {
  local p; p="$(port_of "$1")"
  [ -n "$p" ] && [ -n "$(ss -ltnH "sport = :$p" 2>/dev/null)" ]
}

avail_gb() { awk '/MemAvailable/{printf "%d", $2/1024/1024}' /proc/meminfo; }

mem_ok() { [ "$(avail_gb)" -ge "$MEM_FLOOR_GB" ]; }

# 轮转而非截断: 把当期日志归档为 .1，旧的 .1→.2 …，超出 LOG_KEEP 的最老删除。
# 语义(已隔离测试): 空文件不轮转 / 目标不存在 exit 0 / LOG_KEEP=0 退化为截断。
rotate_log() {
  local f="$1" i
  [ -f "$f" ] || return 0
  [ -s "$f" ] || return 0
  if [ "$LOG_KEEP" -le 0 ]; then : > "$f" 2>/dev/null || true; return 0; fi
  rm -f "$f.$LOG_KEEP" 2>/dev/null || true
  i=$((LOG_KEEP - 1))
  while [ "$i" -ge 1 ]; do
    [ -f "$f.$i" ] && mv -f "$f.$i" "$f.$((i + 1))" 2>/dev/null
    i=$((i - 1))
  done
  mv -f "$f" "$f.1" 2>/dev/null || true
}

acquire_lock() {
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "node_services: another start/stop holds $LOCK_FILE — exiting (serial launches only)"
    exit 0
  fi
}

# ---------- foreground launchers (invoked by tmux via `_run <svc>`) ----------
_run_embed() {
  set -a; [ -f "$DEPLOY_DIR/embed.env" ] && . "$DEPLOY_DIR/embed.env" || true; set +a
  export HF_HOME="$HF_CACHE" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
  cd "$NVIDIA_DIR"
  exec "$NEMOTRON_PY" -m vllm.entrypoints.openai.api_server \
    --model "$HF_CACHE/hub/models--nvidia--Nemotron-3-Embed-1B-NVFP4/files" \
    --served-model-name nemotron-embed-1b \
    --runner pooling --convert embed \
    --max-model-len 8192 --max-num-seqs 64 \
    --gpu-memory-utilization 0.15 \
    --host 127.0.0.1 --port 8011 --trust-remote-code
}

_run_qwen06() {
  set -a; [ -f "$DEPLOY_DIR/qwen06.env" ] && . "$DEPLOY_DIR/qwen06.env" || true; set +a
  export HF_HOME="$HF_CACHE" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
  cd "$NVIDIA_DIR"
  # C4 fallback lane: 权重 ~1.5G bf16; util 0.06 已远大于权重+激活需求。
  # 不加 reasoning-parser (0.6B 的思考链短且 quality 已知 degraded, 本链只求
  # Omni 离线时不 MOCK、能出低质但真实的续写); max-model-len 32768 足够
  # RFQ 抽取/路由分类的短上下文。
  exec "$NEMOTRON_PY" -m vllm.entrypoints.openai.api_server \
    --model "${UEA_QWEN06_MODEL:-$HOME/inference/models/Qwen3-0.6B}" \
    --served-model-name qwen3-0.6b \
    --max-model-len 32768 --max-num-seqs 16 \
    --gpu-memory-utilization 0.06 \
    --host 127.0.0.1 --port 8902 --trust-remote-code
}

_run_omni() {
  set -a; [ -f "$DEPLOY_DIR/omni.env" ] && . "$DEPLOY_DIR/omni.env" || true; set +a
  export HF_HOME="$HF_CACHE" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
  cd "$NVIDIA_DIR"
  # max-model-len must stay <= the model's real max_position_embeddings (262144).
  # 324000 needed VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 and silently produced garbage
  # past 262144; clients now get a clean 400 instead. 16k batched tokens keeps
  # long prefills from being sliced into 40+ chunks (4096 caused agent timeouts).
  # repetition_penalty: the model's generation_config.json ships 1.0, which let
  # the agent loop replay the previous turn's skeleton verbatim.
  exec "$NEMOTRON_PY" -m vllm.entrypoints.openai.api_server \
    --model "$HF_CACHE/hub/models--nvidia--Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4/files" \
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

_run_timo() {
  set -a; [ -f "$DEPLOY_DIR/timo.env" ] && . "$DEPLOY_DIR/timo.env" || true; set +a
  cd "$TIMO_DIR"
  exec "$OCC_PY" -m uvicorn app.main:app --host 127.0.0.1 --port 7862
}

_run_livekernel() {
  set -a; [ -f "$DEPLOY_DIR/livekernel.env" ] && . "$DEPLOY_DIR/livekernel.env" || true; set +a
  cd "$LK_DIR"
  exec "$OCC_PY" -m uvicorn services.api_server:app --host 0.0.0.0 --port 8888
}

_run_searxng() {
  set -a; [ -f "$DEPLOY_DIR/searxng.env" ] && . "$DEPLOY_DIR/searxng.env" || true; set +a
  cd "$SEARXNG_DIR"
  exec "$SEARXNG_PY" -m searx.webapp
}

# ---------- lifecycle ----------
wait_port() {
  local svc="$1" t=0
  while [ "$t" -lt "$READY_TIMEOUT" ]; do
    if port_up "$svc"; then echo "  $svc READY on :$(port_of "$svc") after ${t}s"; return 0; fi
    sleep 3; t=$((t + 3))
  done
  echo "  $svc NOT ready within ${READY_TIMEOUT}s — see $LOG_DIR/$svc.log"; return 1
}

start_svc() {
  local svc="$1"
  if port_up "$svc"; then echo "$svc: UP (adopted) on :$(port_of "$svc") — skipping"; return 0; fi
  case "$svc" in
    embed|qwen06|omni)
      if ! mem_ok; then
        echo "$svc: SKIP launch — MemAvailable $(avail_gb)G < floor ${MEM_FLOOR_GB}G (OOM guard)"
        return 2
      fi ;;
  esac
  tmux kill-session -t "$svc" 2>/dev/null || true
  # 轮转归档旧日志(svc.log → svc.log.1 → …)，崩溃栈不再被销毁
  rotate_log "$LOG_DIR/$svc.log"
  tmux new-session -d -s "$svc" "bash '$SCRIPT_PATH' _run '$svc' >> '$LOG_DIR/$svc.log' 2>&1"
  echo "$svc: launched in tmux '$svc' (log $LOG_DIR/$svc.log)"
  wait_port "$svc" || return 1
}

stop_svc() {
  local svc="$1" p pid
  tmux kill-session -t "$svc" 2>/dev/null && echo "$svc: killed tmux '$svc'" || echo "$svc: no tmux session"
  if port_up "$svc"; then
    p="$(port_of "$svc")"
    pid="$(ss -ltnpH "sport = :$p" 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2 || true)"
    if [ -n "${pid:-}" ]; then
      kill "$pid" 2>/dev/null || true; sleep 2
      kill -0 "$pid" 2>/dev/null && { kill -9 "$pid" 2>/dev/null || true; sleep 1; }
      echo "$svc: freed :$p (pid $pid)"
    fi
  fi
}

status_all() {
  echo "node_services status — MemAvailable $(avail_gb)G (floor ${MEM_FLOOR_GB}G)"
  local svc state managed
  for svc in $SERVICES_ALL; do
    if port_up "$svc"; then state="UP   :$(port_of "$svc")"; else state="DOWN :$(port_of "$svc")"; fi
    if tmux has-session -t "$svc" 2>/dev/null; then managed="tmux:$svc"; else managed="unmanaged"; fi
    printf '  %-11s %-13s %s\n' "$svc" "$state" "$managed"
  done
}

main() {
  local mode="${1:-status}"; shift || true
  case "$mode" in
    status) status_all ;;
    _run)
      local svc="${1:?_run needs a service}" fn
      fn="_run_$svc"
      declare -F "$fn" >/dev/null || { echo "node_services: no launcher for '$svc'"; exit 1; }
      "$fn" ;;
    start)
      acquire_lock
      local target="${1:-all}" svc rc=0
      if [ "$target" = "all" ]; then
        for svc in $SERVICES_ALL; do start_svc "$svc" || rc=$?; done
        echo "---"; status_all; return "$rc"
      fi
      start_svc "$target" ;;
    restart)
      acquire_lock
      local svc="${1:?restart needs a service}"
      stop_svc "$svc"; sleep 2; start_svc "$svc" ;;
    stop)
      acquire_lock
      local target="${1:-all}" svc
      if [ "$target" = "all" ]; then for svc in $SERVICES_ALL; do stop_svc "$svc"; done
      else stop_svc "$target"; fi ;;
    *)
      echo "usage: node_services.sh {status|start [svc|all]|restart svc|stop [svc|all]}"; exit 1 ;;
  esac
}

main "$@"
