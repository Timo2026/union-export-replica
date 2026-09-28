# DEPLOYMENT — 在 DGX Spark 本地算力部署智能体

> 面向评委的复现说明。三部分：①部署智能体 ②优化大模型 ③设计 Agent Skills。
> 所有命令与默认值均来自节点实际配置（`node_services.sh`、`config/settings.dgx-spark-*.yaml`、
> `config/skills.yaml`），未做无依据的假设。

## 0. 前置条件

- 平台：NVIDIA DGX Spark（GB10 / 128GB 统一内存），DGX OS 7.2.3，CUDA 13.0，驱动 580.82.09
- conda 环境：`~/miniconda3/envs/nemotron`（vLLM）、`~/miniconda3/envs/occ`（Timo 引擎）
- 模型已离线就位于 HF 缓存（`HF_HUB_OFFLINE=1`）：Nemotron Embed-1B、Nemotron-3-Nano-Omni-30B-A3B（NVFP4）
- `node_services.sh` 幂等：已监听端口会被"采用"，只拉起缺失的服务

## 1. 部署智能体（一键）

```bash
cd ~/union-deploy
./node_services.sh start        # 拉起 6 服务（embed/qwen06/omni/timo/searxng/livekernel）
./node_services.sh status       # 报告各服务 UP/DOWN，不做任何变更
```

预期监听：

| 服务 | 端口 | 说明 |
|------|------|------|
| livekernel | 8888 | FastAPI 编排器（对内默认服务遗留静态 Workbench）；**线上对外工作台 = React/Vite `webui-dist`（`v7.1.0`，同源相对 `/v1/*`）**，见下方「前端」 |
| omni | 8002 | 视觉+LLM+ASR 统一端点（NVFP4，nemotron_v3 推理解析） |
| embed | 8011 | RAG 嵌入（NVFP4，需 query:/passage: 前缀） |
| qwen06 | 8902 | 轻量辅助模型 |
| timo | 7862 | 确定性报价引擎（**无 LLM 定价**） |
| searxng | 8080 | 本地元搜索 |

健康自检：`curl -s http://127.0.0.1:8888/health`（同时探活 livekernel 与确定性引擎）。
> 注：本交付 lab 的 JupyterLab 公网 :9051 映射到节点 :9000，root_dir=`/home/Developer/inference/notebooks`，
> token 见节点本地 `node.env`（不写入交付包，遵守 data-stays-local）。

### 前端（线上工作台 = React/Vite `webui-dist`）

线上 `:8051` 的工作台是 **Vite 编译的 React SPA**（product version `v7.1.0`）。其编译产物已按 md5 **逐字节**纳入本包 [`app/webui-dist/`](../app/webui-dist/)（主 bundle `index-DSmUweh8.js`，md5 `d53bdd6d…`，与线上一致）。

- **资源 base `/B/`**（壳在 `/`、资源在 `/B/assets/*`）；**后端走同源相对 `/v1/*`**（无硬编码 IP）。
- 本地忠实预览：把 `webui-dist` 同时挂到 `/` 与 `/B`，`/v1/*` 交给 `:8888` 后端。`app/webui-dist/README.md` 给了一段 FastAPI 挂载示例（`/` 挂载放最后，避免遮蔽 `/v1` 路由）。
- 本节点 `:8888`（`api_server.py` 版本 `6.1.0-livekernel`）默认服务的是**遗留静态工作台**；要复现线上 `:8051` 那套 React UI，用上面的方式挂 `webui-dist`。线上 `:8051` 的具体反代/NAT 在另一节点，本机无法取证，此处只述可验证部分。

### 离线最小复现（零 GPU/零网络）

```bash
pip install -r requirements.txt
python scripts/run_demo.py --offline     # 6 条场景，控制台全 [OK]，退出码 0
python scripts/run_flywheel_demo.py      # 双层沙箱 + 分级价格修正提案（COLD 5%/WARM 10%/HOT 15% 上限）
```

## 2. 优化大模型

- **NVFP4 量化**：Nemotron 家族全部 NVFP4；NVFP4 kernel 首次调用由 FlashInfer JIT 构建。
- **HF 离线**：`HF_HOME`/`HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`，避免节点反复拉取。
- **vLLM + 推理解析**：OpenAI 兼容端点，`--reasoning-parser nemotron_v3`。
- **MoE**：30B 总参 / 3B 激活，深度推理与低时延折中。
- **RAG 分层与显式降级**：Embed-1B 强制非对称双塔前缀（无前缀排序错误：0.3758 vs 0.5209），
  首调用放宽 timeout 至 15s；失败进 60s 冷却后 `HashEmbedder` 哈希降级，**标注 MOCK，绝不冒充在线**。
- **退化不留死角**：Timo 引擎不可达时走 byte-identical 离线兜底并显式标注（`allow_fallback: true`）。

## 3. 设计 Agent Skills

- 装配清单：`config/skills.yaml`（version 3）。分发器 `strategy: auto`、`llm_role: llm`、
  `fallback_rules: true`、`max_skills_per_task: 8`、`audit_max: 50`。
- 每个 skill 声明 `iron_rule`（`deterministic` 走内核 / `llm_proposal` 仅提议）与 `openshell` 护栏
  （`iron-rule-1`/`local-only`/`skill-allowlist`/`hitl-required`）。
- 关键 skill 的定价/裁决类（`calc_quote`/`check_dfm`/`verify_gate`）均 `deterministic + iron-rule-1 + hitl-required`。
- OpenClaw 侧以 `union-export` 桥接 skill（v6.3.2）把外部请求转发到本地 livekernel，
  自身**不计算价格**（`allowed-tools: Read, Bash(curl *)`）。

## 治理默认（节点更收紧）

- `egress.allow=false`：SMTP/Webhook/IMAP 全关；邮件**仅草稿**。
- guardrails `nemo_soft`（未装 nemoguardrails 时自动降级 builtin），`tool_allowlist_enforced=true`。
