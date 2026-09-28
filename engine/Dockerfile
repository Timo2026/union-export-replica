# ============================================================
# Union CNC AI Brain — 参数化部署镜像
#
# DRY 设计：用一个 Dockerfile 覆盖四大硬件厂商，通过 BUILD ARG
# 切换基础镜像与 STEP 解析依赖，避免维护四份几乎相同的 Dockerfile。
#
#   ARG BASE_IMAGE    基础镜像（区分 ROCm / CUDA / CPU）
#   ARG INSTALL_STEP  是否安装完整 STEP 精确解析依赖
#                     （OCP/cadquery/cascadion，等价于 conda step-render 环境）
#
# 构建示例（日常推荐直接用 docker-compose.<vendor>.yml，见 docs/DEPLOY.md）：
#   # AMD ROCm（--device=/dev/kfd --device=/dev/dri 见 docker-compose.rocm.yml）
#   docker build --build-arg BASE_IMAGE=rocm/pytorch:rocm6.4 -t cnc-ai-brain:rocm .
#   # NVIDIA CUDA
#   docker build --build-arg BASE_IMAGE=pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime -t cnc-ai-brain:cuda .
#   # 纯 CPU（默认）
#   docker build -t cnc-ai-brain:cpu .
# ============================================================

ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

# FROM 之后重新声明 ARG，供后续 RUN 引用
ARG INSTALL_STEP=1

ENV PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ── 系统依赖 ──
# OCP(OpenCASCADE)/cadquery 需要 GL 与字体运行库（三种基础镜像均为 Debian/Ubuntu 系）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglu1-mesa libx11-6 libxext6 libxrender1 \
        libfontconfig1 libfreetype6 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ── Python 依赖 ──
# 核心依赖：fastapi/uvicorn/numpy/trimesh 等
COPY requirements.txt requirements-ocp.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 可选：完整 STEP 精确几何解析（cadquery / cadquery-ocp / cascadion）
#   —— 来源等价于 environment.yml 的 conda step-render 环境；纯 CPU 亦可用 manylinux wheel
RUN if [ "$INSTALL_STEP" = "1" ]; then pip install --no-cache-dir -r requirements-ocp.txt; fi

COPY . .

# 主服务端口统一 7862（与 docker-compose / CNC_AI_Brain_启动.bat / start_server.py 一致）
EXPOSE 7862

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7862"]