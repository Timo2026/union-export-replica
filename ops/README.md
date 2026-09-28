# ops/ — 服务编排

## node_services.sh

6 服务 **tmux 监督器**，源自运行节点 `~/union-deploy/node_services.sh`。特性：**幂等**（已监听端口会被"采用"，只拉起缺失服务）。

```bash
bash ops/node_services.sh start     # 拉起 6 服务
bash ops/node_services.sh status    # 报告 UP/DOWN，不做变更
bash ops/node_services.sh stop      # 停止
bash ops/node_services.sh restart   # 重启
```

### 服务清单

| 服务 | 端口 | 说明 | 依赖环境 |
|------|------|------|----------|
| `livekernel` | **8888** | FastAPI 编排器（union-export-agent v7.1.0-livekernel）；公网经 NAT → Workbench | `occ` |
| `omni` | **8002** | Nemotron-3-Nano-Omni-30B-A3B（NVFP4，任意到任意 视觉+LLM+ASR） | `nemotron` |
| `embed` | **8011** | Nemotron-3-Embed-1B（NVFP4，RAG 嵌入，pooling） | `nemotron` |
| `qwen06` | **8902** | Qwen3-0.6B（Omni 离线时的 LLM fallback lane） | `nemotron` |
| `timo` | **7862** | Timo CNC 确定性报价引擎（**无 LLM 定价**，sha256 铁律①） | `occ` |
| `searxng` | 8080 | 本地元搜索（可选） | `searxng` |

### 本地配置（不入库）

`node_services.sh` 会从本地 `node.env`（若存在）读端口/模型路径等覆盖项。**节点公网 IP、SSH 端口、token 仅放本地 `node.env`，绝不入库。**

- `HF_CACHE` 默认 `$NVIDIA_DIR/hf-cache`（含 NVFP4 权重 ≈41G）。
- 健康自检：`curl -s http://127.0.0.1:8888/health`（同时探活 livekernel 与 Timo 引擎）。

> 直接按需跑单个 vLLM 端点见 [`../models/fetch_and_launch.sh`](../models/fetch_and_launch.sh)。

## GITHUB_PUSH.md

把本复刻包包成一个可公开的 GitHub 仓库的步骤。**推送是外发动作，需你本人在有 GitHub 账号的终端执行**（我代办到此为止，不代推送）。
