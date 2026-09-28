# Union CNC AI Brain — 部署指南

> 三种部署方式：conda（推荐）/ Docker / venv

## 方式一：conda 部署（推荐，支持 STEP 精确解析）

### 1. 创建环境

```bash
conda env create -f environment.yml
conda activate step-render
```

环境包含：
- OCP 7.7.2.1（OpenCASCADE Python 绑定）
- cadquery 2.4.0（CAD 参数化建模）
- trimesh 4.12.2（3D 网格处理）
- cascadion 0.1.1（STEP→trimesh 适配器）
- ezdxf 1.4.4（DXF 图纸解析）
- fastapi + uvicorn（Web 服务）

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入 API Key（可选，无 key 则降级规则引擎）
```

### 3. 启动

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 7862
```

### 4. 验证

```bash
curl http://127.0.0.1:7862/api/health
# 期望: {"status":"healthy","version":"12.0.0-fusion",...}
```

---

## 方式二：Docker 部署（四大硬件厂商）

> **DRY 设计**：一个参数化 `Dockerfile`（`BASE_IMAGE` / `INSTALL_STEP` 两个 build arg）
> 覆盖四种硬件，厂商差异通过 `docker-compose.<vendor>.yml` override 叠加，避免复制粘贴三份同样的 Dockerfile。

| 硬件厂商 | 部署入口文件 |
|----------|--------------|
| 纯 CPU | `docker-compose.yml` + `docker-compose.cpu.yml` |
| AMD ROCm | `docker-compose.yml` + `docker-compose.rocm.yml` |
| NVIDIA CUDA | `docker-compose.yml` + `docker-compose.cuda.yml` |
| 摩尔线程 MUSA | `MUSA_vLLM_启动.bat` / `scripts/start_musa_vllm.sh`（本机 vLLM）+ 主服务用 CPU 镜像 |
| 公共 | `Dockerfile`（参数化）、`requirements-ocp.txt`（STEP 依赖）、`.dockerignore` |

### 0. 通用前置

```bash
cp .env.example .env   # 填入云端 API Key（可选，无 key 自动降级规则引擎，严禁硬编码密钥进镜像）
```

### 2.1 纯 CPU（无 GPU）

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build
```

- ✅ 基础镜像 `python:3.11-slim`，主服务（FastAPI）不依赖 GPU
- ✅ `INSTALL_STEP=1` 仍装 cadquery/cadquery-ocp（manylinux CPU wheel），保留 STEP 精确解析
- 🔧 需最小化镜像：把 `docker-compose.cpu.yml` 的 `INSTALL_STEP` 改为 `"0"`（STEP 降级 trimesh）

### 2.2 AMD ROCm（比赛赛道重点）

```bash
docker compose -f docker-compose.yml -f docker-compose.rocm.yml up -d --build
```

等价 `docker run`（含设备透传）：

```bash
docker run --device=/dev/kfd --device=/dev/dri --group-add video \
  -p 7862:7862 -v $PWD/data:/app/data cnc-ai-brain:rocm
```

- ✅ 基础镜像 `rocm/pytorch:rocm6.4`
- ✅ `--device=/dev/kfd`（计算）+ `--device=/dev/dri`（渲染）透传 AMD GPU
- 🔧 前置：安装 ROCm 内核驱动

### 2.3 NVIDIA CUDA

```bash
docker compose -f docker-compose.yml -f docker-compose.cuda.yml up -d --build
```

等价 `docker run`：

```bash
docker run --gpus all -p 7862:7862 -v $PWD/data:/app/data cnc-ai-brain:cuda
```

- ✅ 基础镜像 `pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime`
- 🔧 前置：安装 NVIDIA Container Toolkit（`nvidia-container-toolkit`）

### 2.4 摩尔线程 MUSA（当前主后端，本机 vLLM）

摩尔线程 MUSA 对 Docker 支持有限，当前主后端为**本机 vLLM MUSA**，因此：

1. 先启动本机 MUSA vLLM 推理后端（尊重端点 `:32102` / `:8000`，见 `config/models.json`）：
   - Windows：`MUSA_vLLM_启动.bat`
   - Linux：`MODEL_PATH=/data/models/Qwen2.5-7B-GPTQ-Int4 MODEL_NAME=qwen2.5-7b-gptq VLLM_PORT=8000 ./scripts/start_musa_vllm.sh`
2. 主服务用通用镜像（CPU）启动，通过 `host.docker.internal` 连接本机 vLLM：

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build
```

> 主服务容器内访问宿主机 MUSA 后端时，将 `config/models.json` 中 `api_url` 的
> `127.0.0.1` 改为 `host.docker.internal`（容器内 `127.0.0.1` 指向容器自身）。
> 基础配置已内置 `extra_hosts: host-gateway`，支持 Linux 直接解析宿主机。

### 2.5 日志 / 停止

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml logs -f cnc-ai-brain
docker compose -f docker-compose.yml -f docker-compose.cpu.yml down
```

> `docker compose`（V2 语法）与 `docker-compose`（V1）均可，V2 对多文件 `-f` 合并更规范，推荐使用 V2。

---

## 方式三：venv 部署（精简，无 STEP 精确解析）

```bash
python -m venv .venv
.venv\Scripts\activate
set PYTHONUTF8=1
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 7862
```

> **限制**：无 cascadion，STEP 上传仅支持 trimesh 网格解析（部分 STEP 可能失败），报价规则引擎正常。

---

## 生产环境建议

| 项目 | 建议 |
|------|------|
| 反向代理 | Nginx（HTTPS + 静态文件加速） |
| 进程管理 | systemd / PM2 / supervisor |
| 数据持久化 | 挂载 `data/` 目录到持久卷 |
| 日志 | 挂载 `logs/` 目录，配置 logrotate |
| 监控 | `/api/health` 健康检查端点 |
| 资源 | 最低 2GB RAM，推荐 4GB+（cadquery 解析大 STEP 需内存） |

### Nginx 配置示例

```nginx
server {
    listen 80;
    server_name cnc.example.com;

    client_max_body_size 100M;    # 上传大 STEP 文件

    location / {
        proxy_pass http://127.0.0.1:7862;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 端口说明

| 端口 | 服务 | 说明 |
|------|------|------|
| 7862 | FastAPI 主服务 | Web UI + API |
| 7863 | MTClaw Function Router | CNC 工具加速（可选） |
| 11434 | Ollama | 本地 LLM（可选） |
| 1234 | LMStudio | 本地 LLM（可选） |