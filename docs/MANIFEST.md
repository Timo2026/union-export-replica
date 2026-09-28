# MANIFEST — 源 → 复刻 映射 / 版本 / 完整性

> 本文件说明「复刻包」每一项**来自哪里、改了什么、为何**，保证可审计、可复现。

## A. 源 → 复刻 路径映射

| 源路径（节点） | 复刻路径 | 内容 | 复刻时处理 |
|----------------|----------|------|------------|
| `~/union-deploy/union-export-demo` | [`app/`](../app/) | livekernel FastAPI 编排器（`api_server.py` 版本 `6.1.0-livekernel`）、33 业务技能、**遗留静态 Workbench**（`index.html` v6.1.0 融合版 + `webui/index.html` 控制台 v12，**非线上 UI**）、邮件子系统 | 脱敏公网 IP → `NODE_PUBLIC_HOST`；删除 `*.env`/`*.db`/`node_modules`/备份/demo-freeze JSON/`__pycache__` |
| `~/timo_livekernel/webui-dist` | [`app/webui-dist/`](../app/webui-dist/) | **线上 `:8051` 的 React/Vite 编译工作台（`v7.1.0` / livekernel）**：`index.html`(941B 壳) + `assets/index-DSmUweh8.js`(1.3MB) + CSS + 图标/空态 PNG | **与线上逐字节一致**（主 bundle md5 = `d53bdd6d…`，壳 diff 一致）；相对 `/v1/*` 调后端，资源 base `/B/`；`webui-src`（React 源码）本节点不存在，故取编译产物 |
| `~/timo_engine` | [`engine/`](../engine/) | Timo CNC 确定性内核（`:7862`，sha256 铁律①）、CAD/几何依赖、`docker-compose.{cpu,cuda,rocm}.yml` | 删除运行时库 `orders.db`/`audit.db` |
| `~/.openclaw/skills` | [`openclaw/skills/`](../openclaw/skills/) | OpenClaw Agent Skills（**51** 目录：NVIDIA 栈 + 制造域 + 通用 + `union-export` 桥接 v6.3.2） | 排除 `*.oms.sig`（签名）、`credentials/`；删除 `opc-fusion-quote/data/calibration.db` |
| `~/STEP/`（代表性样例） | [`cnc_inputs/step_samples/`](../cnc_inputs/step_samples/) | 25 个 CAD `.step`（box/bracket/bearing/tube） | 取代表性子集，非全量 |
| `~/union-deploy/node_services.sh` | [`ops/node_services.sh`](../ops/node_services.sh) | 6 服务 tmux 编排（幂等，采用已在监听者） | 节点 IP/SSH 端口仅留本地 `node.env`，**不入库** |
| `~/nvidia/hf-cache` + `~/inference/models` | [`models/MODELS.md`](../models/MODELS.md) + `fetch_and_launch.sh` | 3 个模型（Omni-30B / Embed-1B NVFP4、Qwen3-0.6B）精确名/端口/启动参数 | **权重（≈41G）不入库**，用清单+脚本复现 |
| `~/miniconda3/envs`（6 个） | [`env/README.md`](../env/README.md) | 6 环境角色 + Python 版本 + 依赖清单位置 | 环境本体不入库 |

## B. 版本

| 组件 | 版本/口径 |
|------|-----------|
| livekernel FastAPI（本节点 `api_server`） | `6.1.0-livekernel` |
| 线上工作台（`app/webui-dist`，React/Vite 编译版） | `v7.1.0`（与 `:8051` md5 一致） |
| union-export 桥接 skill | `v6.3.2` |
| `config/skills.yaml` | `version 3` |
| `node_services.sh` | 2026-09-26（含 C4：恢复 0.6B fallback 链） |
| Timo 引擎 | 见 `engine/CHANGELOG.md` |
| 模型 | Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4 / Nemotron-3-Embed-1B-NVFP4 / Qwen3-0.6B |

## C. 完整性（三分类）

- ✅ **忠实复制**：应用代码、配置（含 `settings.dgx-spark-*.yaml`）、33 业务技能、51 openclaw 技能、编排脚本、STEP 样例、**线上 React 工作台 `webui-dist`（与 `:8051` md5 核对一致）**。
- 📋 **清单 + 脚本复现**（因体积/机器相关不入库）：模型权重（41G）、conda 环境、`node_modules`。
- 🧹 **脱敏/移除**（隐私红线）：节点公网 IP、JupyterLab token、`STEPFUN_API_KEY`、IMAP 凭据、运行时订单/审计库、日志、备份、`备份.zip`。

## D. 完整平台布局（可选参考）

源开发树 `~/timo_livekernel` 约 935M，是**运行时的完整开发/服务树**；本包只含**可运行子集**。其顶层布局（如实记录，供参考，**不随包分发**）：

```
timo_livekernel/            ~935M（开发/服务树，含下述大项与运行时产物）
├─ tailscale (≈48M) · 备份.zip (≈574M) · node_modules/ (≈1.5G)
├─ .openclaw/ (≈12M)         ← 本包仅取其 skills/ 子集 → openclaw/skills/
├─ webui-src/HTML (≈13M) · redteam_opt/ (≈6.1M) · docs/ (≈6.1M)
├─ workspace (≈8.9M) · scripts/ · logs/ · credentials/（不入库）
├─ demo-freeze/ · .stepcode / .steppage-mcp（阶跃星辰工具链）
└─ README.md · env310/data · verify/ · webui-dist/
```

> `union-export-demo`（本包 `app/`）是这套平台里**可独立运行的业务主干**（配置中被标为 trunk 运行时依赖），
> 与 `timo_engine`（`engine/`）、`.openclaw/skills` 共同构成"模型→技能→确定性内核→Workbench"的最小可复现闭环。

## E. 已知源系统脏数据（复刻时已清理）

- `union-export-demo/` 内曾有一个 Windows 绝对路径被当成目录名创建（`C:\Users\<user>\...\flywheel`），非运行所需，已删除。
- 若复刻时发现 `find . -name 'C:*'` 有结果，按此清理。
