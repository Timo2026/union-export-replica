@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Union CNC AI Brain — MUSA 本地 vLLM 推理后端 (摩尔线程)

REM ============================================================
REM 摩尔线程 MUSA 本地 vLLM 推理后端启动脚本（本项目当前主后端）
REM
REM 主服务 config/models.json 已配置以下本地端点（请勿改动端口）：
REM   - http://127.0.0.1:32102/v1  (Qwen3-8B GPTQ , model_id=musachat_local)
REM   - http://127.0.0.1:8000/v1   (Qwen2.5-7B GPTQ, model_id=qwen2.5-7b-gptq)
REM
REM 前置：
REM   1. 已安装摩尔线程 MUSA 驱动 + MUSA 版 vLLM（vllm-musa）
REM   2. 已下载对应 GPTQ/Int4 模型到 MODEL_PATH
REM
REM 启动后，主服务（cnc-ai-brain）通过 config/models.json 的本地端点
REM 自动发现并优先调用本后端（quality_score 最高）。Docker 部署时主服务
REM 容器内请改用 http://host.docker.internal:<PORT>/v1 访问宿主机本后端。
REM ============================================================

REM ── 可配置参数（DRY：只在此处修改，勿硬编码到命令里）──
set "MODEL_PATH=D:\models\Qwen3-8B-GPTQ-Int4"
set "MODEL_NAME=musachat_local"
set "VLLM_PORT=32102"
set "MAX_MODEL_LEN=2048"
set "QUANT=gptq"

echo =======================================================
echo   摩尔线程 MUSA 本地 vLLM 推理后端
echo   服务端点 : http://127.0.0.1:%VLLM_PORT%/v1
echo   模型标识 : %MODEL_NAME%
echo   上下文长 : %MAX_MODEL_LEN%
echo =======================================================
echo.

REM vLLM >= 0.6 亦可改为:  vllm serve "%MODEL_PATH%" --served-model-name ...
python -m vllm.entrypoints.openai.api_server ^
    --model "%MODEL_PATH%" ^
    --served-model-name "%MODEL_NAME%" ^
    --host 0.0.0.0 ^
    --port %VLLM_PORT% ^
    --max-model-len %MAX_MODEL_LEN% ^
    --dtype auto ^
    --quantization %QUANT%

pause