# 硬件适配与部署（多厂商）

> 本文档说明 CNC AI Brain 对四种硬件厂商的适配方式、自动探测机制与部署步骤。
> 版本：`config/version.txt`（单一来源） · 实测现状：摩尔线程 MUSA 已实测，其余厂商已提供部署支持。

## 一、厂商总览

系统通过「探测 → 路由」两步，将运行态自动对齐到目标硬件厂商：

| 厂商 | vendor 标识 | 推理后端 | 本地实测状态 | 部署入口 |
|------|-------------|----------|--------------|----------|
| 摩尔线程 MUSA | `musa` | vLLM MUSA（本机） | ✅ 已实测（当前生产后端） | `MUSA_vLLM_启动.bat` / `scripts/start_musa_vllm.sh` |
| NVIDIA CUDA | `nvidia` | vLLM / llama.cpp CUDA | 🚧 已提供部署支持 | `docker-compose.yml` + `docker-compose.cuda.yml` |
| AMD ROCm | `amd` | vLLM ROCm / Ollama ROCm | 🚧 已提供部署支持（未实测） | `docker-compose.yml` + `docker-compose.rocm.yml` |
| 纯 CPU | `cpu` | Ollama / llama.cpp（纯 CPU），兜底云端 API | ✅ 可用（无 GPU） | `docker-compose.yml` + `docker-compose.cpu.yml` |

> **如实说明**：当前本机（Windows）实测跑通的推理后端为摩尔线程 MUSA M1000（vLLM MUSA）。
> NVIDIA CUDA / AMD ROCm 已交付参数化 `Dockerfile` 与对应 `docker-compose.*.yml` 部署文件，
> 但尚未在本机完成实机验证，请按「已提供部署支持」理解。

---

## 二、自动探测机制（environment_detector）

`src/core/environment_detector.py` 负责输出归一化的 vendor 字符串，所有端口/地址均不硬编码。

### 2.1 检测优先级

`detect_vendor()` 按下述优先级判定，**宁可返回 `unknown` 也不瞎猜**：

1. **环境变量显式覆盖**：`CNC_AI_HARDWARE_VENDOR` / `HARDWARE_VENDOR`（用户意图最高）
2. **torch 运行时**：`torch_musa`（MUSA）> `torch.cuda.is_available()`（配合 `torch.version.hip` 区分 CUDA/ROCm）
3. **GPU 名称字符串匹配**：`wmic` / `nvidia-smi` / `rocm-smi` 产出（精确子串，长关键词优先）
4. **vLLM MUSA 端点探测**：环境变量 `MUSA_VLLM_ENDPOINTS`（逗号分隔，任一端点可达即判 MUSA）
5. **环境变量标记**：`MUSA_HOME` / `CUDA_HOME` / `ROCM_HOME` 等 SDK 标记
6. **无任何 GPU 信号** → `cpu`；**有信号但无法判定厂商** → `unknown`

### 2.2 厂商别名归一化

`VENDOR_ALIASES` 提供单一映射表，将常见字符串归一为 `nvidia / amd / musa / cpu / any / unknown`，例如：

| 原始字符串示例 | 归一化结果 |
|----------------|------------|
| `cuda` / `rtx` / `a100` / `h100` | `nvidia` |
| `radeon` / `rocm` / `hip` / `mi300` | `amd` |
| `musa` / `mtt` / `mthreads` / `摩尔线程` | `musa` |
| `cpu` / `none` | `cpu` |
| 无法识别 | `unknown` |

`normalize_vendor()` 供 `environment_detector` 与 `model_auto_loader` 复用，保证归一逻辑一致（DRY）。

### 2.3 输出结构

`detect()`（完整探测）在保留原有 `cpu / memory_gb / gpu` 字段（向后兼容）的同时，新增：

```json
{
  "hardware_profile": {
    "vendor": "musa",
    "capabilities": { "cuda": false, "hip": false, "musa": true },
    "gpu_names": ["Moore Threads MTT S1000"],
    "detail": "摩尔线程 MUSA GPU",
    "evidence": {
      "torch_cuda": false, "torch_hip": false, "torch_musa": true,
      "env_musa": true, "env_cuda": false, "env_rocm": false,
      "musa_endpoint": true
    }
  }
}
```

`evidence` 字段记录每条证据，便于追溯判定来源。

---

## 三、后端路由机制（model_auto_loader）

`src/core/model_auto_loader.py` 根据探测出的 vendor，对 `config/models.json` 中标注了
`vendor` 字段的模型进行排序路由：

- **合并去重**：合并 `cloud` / `local` / `models` 三处模型，解析 `${VAR}` / `${VAR:-default}` 环境变量占位符
- **路由排序键**（升序，越小越优先）：
  1. vendor 匹配等级：精确匹配 = 0 > 硬件无关（`any`）= 1 > 其它 vendor = 2
  2. 来源等级：遵循 `preference`（`cloud` 偏好下 cloud=0，否则 local=0）
  3. `-quality_score`（分数高者优先）

`config/models.json` 中 `vendor_routing` 配置块为各厂商声明了预期后端与端点（`nvidia` / `amd` / `musa` / `cpu`），
端口/地址均通过环境变量驱动，禁止硬编码。

---

## 四、各厂商部署步骤

> 通用前置：`cp .env.example .env` 填入云端 API Key（可选，无 key 自动降级规则引擎，严禁硬编码密钥进镜像）。

### 4.1 纯 CPU（无 GPU）

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build
```

- 基础镜像 `python:3.11-slim`，主服务（FastAPI）不依赖 GPU
- `INSTALL_STEP=1` 仍安装 cadquery/cadquery-ocp（manylinux CPU wheel），保留 STEP 精确解析
- 需最小化镜像：将 `docker-compose.cpu.yml` 的 `INSTALL_STEP` 改为 `"0"`（STEP 降级 trimesh）

### 4.2 NVIDIA CUDA

```bash
docker compose -f docker-compose.yml -f docker-compose.cuda.yml up -d --build
```

等价 `docker run`：

```bash
docker run --gpus all -p 7862:7862 -v $PWD/data:/app/data cnc-ai-brain:cuda
```

- 基础镜像 `pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime`
- 前置：安装 NVIDIA Container Toolkit（`nvidia-container-toolkit`）
- 推理端点（vLLM CUDA）通过环境变量 `VLLM_CUDA_BASE` 配置，默认 `http://127.0.0.1:8000/v1`

### 4.3 AMD ROCm

```bash
docker compose -f docker-compose.yml -f docker-compose.rocm.yml up -d --build
```

等价 `docker run`（含设备透传）：

```bash
docker run --device=/dev/kfd --device=/dev/dri --group-add video \
  -p 7862:7862 -v $PWD/data:/app/data cnc-ai-brain:rocm
```

- 基础镜像 `rocm/pytorch:rocm6.4`
- `--device=/dev/kfd`（计算）+ `--device=/dev/dri`（渲染）透传 AMD GPU
- 前置：安装 ROCm 内核驱动
- 目标硬件：AMD RYZEN AI MAX+ 395 + Radeon 8060S 64GB 统一显存（本机未实测）
- 推理端点（vLLM ROCm）通过环境变量 `VLLM_ROCM_BASE` 配置，默认 `http://127.0.0.1:8000/v1`

### 4.4 摩尔线程 MUSA（当前主后端，本机 vLLM）

摩尔线程 MUSA 对 Docker 支持有限，当前主后端为**本机 vLLM MUSA**：

1. 先启动本机 MUSA vLLM 推理后端（尊重端点 `:32102` / `:8000`，见 `config/models.json`）：
   - Windows：`MUSA_vLLM_启动.bat`
   - Linux：`MODEL_PATH=/data/models/Qwen2.5-7B-GPTQ-Int4 MODEL_NAME=qwen2.5-7b-gptq VLLM_PORT=8000 ./scripts/start_musa_vllm.sh`
2. 主服务用通用镜像（CPU）启动，通过 `host.docker.internal` 连接本机 vLLM：

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build
```

> 容器内访问宿主机 MUSA 后端时，将 `config/models.json` 中 `api_url` 的 `127.0.0.1` 改为
> `host.docker.internal`。基础编排已内置 `extra_hosts: host-gateway`，支持 Linux 直接解析宿主机。

---

## 五、验证

```bash
curl http://127.0.0.1:7862/api/health
# 期望: {"status":"healthy","mode":"...","version":"12.0.0-fusion",...}
```

`/api/health` 返回中包含 `hardware_profile.vendor`（`nvidia` / `amd` / `musa` / `cpu` / `unknown`），
可用于确认探测结果与预期厂商一致。

---

## 六、相关文件清单

| 文件 | 作用 |
|------|------|
| `src/core/environment_detector.py` | 多厂商 vendor 自动探测 |
| `src/core/model_auto_loader.py` | 按 vendor 路由模型降级链 |
| `config/models.json` | 模型配置（`vendor` 字段 + `vendor_routing` 块） |
| `Dockerfile` | 参数化镜像（`BASE_IMAGE` / `INSTALL_STEP`） |
| `docker-compose.yml` | 基础编排（各厂商公共） |
| `docker-compose.cpu.yml` / `docker-compose.cuda.yml` / `docker-compose.rocm.yml` | 各厂商 override |
| `requirements-ocp.txt` | STEP 精确解析依赖（OCP/cadquery/cascadion） |
| `MUSA_vLLM_启动.bat` / `scripts/start_musa_vllm.sh` | 摩尔线程 MUSA vLLM 启动脚本 |
| `.dockerignore` | Docker 构建忽略清单 |
| `docs/DEPLOY.md` | 通用部署指南（conda / Docker / venv） |