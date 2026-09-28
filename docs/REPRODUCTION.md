# REPRODUCTION — 从零复刻本系统

> 目标：在一台干净的 **DGX Spark / GB10**（或等效：CUDA 13.0、驱动 580+、≈80GB+ 显存）上，把本包跑成
> 与源系统一致的「本地多模态制造询报价智能体」。数据全程不出本机。

## 0. 前置条件

| 项 | 要求 |
|----|------|
| 机器 | NVIDIA DGX Spark（GB10，≈128GB 统一内存）或等效 |
| 驱动/CUDA | NVIDIA-SMI **580.82.09** / **CUDA 13.0**（或更新） |
| OS | DGX OS 7.2.3 或含 NVIDIA 驱动的 Linux (arm64) |
| 工具 | `conda`（miniconda3）、`tmux`、`curl`、`vllm`（NVFP4 构建） |
| 模型 | NVFP4 权重在 HF 离线缓存（见 [`../models/MODELS.md`](../models/MODELS.md)） |

## 1. 建环境

```bash
# 推理环境（vLLM + Nemotron）
conda create -y -n nemotron python=3.12
conda activate nemotron && pip install vllm   # 选对应 CUDA 13.0 的 NVFP4 构建

# 引擎 / CAD 环境（Timo 确定性内核：cadquery/trimesh/ezdxf）
conda env create -f ../engine/environment.yml     # name: step-render
# 或：conda create -n occ python=3.11 后 pip install -r engine/requirements.txt -r engine/requirements-ocp.txt
```

> 6 个环境的角色/版本见 [`../env/README.md`](../env/README.md)。

## 2. 起推理端点（NVFP4，离线）

```bash
bash ../models/fetch_and_launch.sh all       # 后台拉起 :8002 / :8011 / :8902
bash ../models/fetch_and_launch.sh check     # 探活
```

## 3. 起确定性内核 + 编排器

```bash
bash ../ops/node_services.sh start           # tmux 拉起 6 服务，幂等（采用已在监听者）
bash ../ops/node_services.sh status
curl -s http://127.0.0.1:8888/health        # 应同时探活 livekernel 与 Timo 引擎
```

> `node_services.sh` 会从本地 `node.env` 读端口/模型路径（**不入库**）。首次使用可按注释建 `node.env`，
> 或用默认值。节点公网 IP / SSH 端口**只放本地 `node.env`，绝不入库**。

## 4. 冒烟验证

```bash
bash ../scripts/verify_replica.sh            # 结构 + 秘密扫描 + 端口探活
```

## 5. 访问

| 入口 | 地址 |
|------|------|
| Workbench / LiveKernel API | `http://127.0.0.1:8888/`（经 NAT 对外 → `:8051`） |
| 健康探活 | `curl -s http://127.0.0.1:8888/health` |
| 模型端点 | `:8002` Omni · `:8011` Embed · `:8902` Qwen06 |

## 已知差异（如实）

- **模型权重、conda 二进制、`node_modules` 不在包内**，需按上文在目标机准备。
- 源系统运行在含调试日志/缓存的开发树（`timo_livekernel`，约 935M）；本包只含**可运行子集**，
  完整布局见 [`MANIFEST.md`](MANIFEST.md#完整平台布局可选参考)。
- 邮件子系统 IMAP 账号/密码**不入库**，需在 `node.env`/`union-export-demo/services/.env` 本地配置（见 [`EMAIL_SUBSYSTEM.md`](EMAIL_SUBSYSTEM.md)）。
