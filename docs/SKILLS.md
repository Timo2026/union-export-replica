# SKILLS — Agent Skills 全景（作品核心）

本作品的智能体由 **Skills 驱动并优化**。评分维度「智能体与模型优化技术深度（Skills 设计与融合）25%」即针对此处。
Skills 分两套：**业务技能**（`app/skills/`，33 个）与 **NVIDIA 栈技能**（`openclaw/skills/`，把模型优化沉淀为可复用 Agent 技能）。

## A. 技能护栏模型（`app/config/skills.yaml` v3）

每个 skill 声明两件事，构成确定性/LLM 的强隔离：

- `iron_rule`：
  - `deterministic` —— 全走确定性内核，LLM 不可覆盖（定价、冲突、裁决）。
  - `llm_proposal` —— LLM 仅*提议*补全，不覆盖确定性值（如 `extract_specs`）。
- `openshell` 护栏：`iron-rule-1`（价格唯一权威）/ `local-only` / `skill-allowlist` / `hitl-required`。

分发器：`strategy: auto`、`llm_role: llm`、`fallback_rules: true`、单任务 `max_skills_per_task: 8`、`audit_max: 50`。

## B. 业务技能（按职能分组，`app/skills/`）

| 分组 | Skills |
|------|--------|
| 询盘解析 | `parse-rfq` · `rfq-extraction` · `extract-specs` |
| 确定性报价 | `cnc-quote` · `batch-quote` · `quote-calibration` · `quote-correction` |
| DFM / 冲突 | `check-dfm` · `dfm-expert` · `dfm-conflict` · `feasibility-checker` |
| 图纸输入 | `step-analysis` · `extract-specs` · `render-thumbnail` |
| 知识检索 | `rag-ingest` · `material-expert` |
| 供应链 / 出口 | `supplier-match` · `freight-customs` |
| 决策 / 飞轮 | `golden-chain` · `ceo-decision` · `customer-flywheel` · `customer-health` · `quality-loop` · `retention-alert` |
| 校验 / 生成 | `verification` · `write-reply` |
| REID / OS | `reid-os` |

> 定价/裁决类技能（对应 `skills.yaml` 的 `calc_quote`/`check_dfm`/`verify_gate`）均为
> `deterministic + iron-rule-1 + hitl-required`。`step-analysis` 承接 STEP/CAD 几何进料（示例见 `cnc_inputs/step_samples/`：box/bracket/bearing 等 25 个）。

## C. Agent 运行入口（OpenClaw 桥接）

- `union-export`（v6.3.2，`openclaw/skills/union-export/SKILL.md`）：**薄桥接**——把外部请求转发到
  本地 livekernel（默认 `http://127.0.0.1:8888`，env `UEA_LIVEKERNEL_URL` 覆盖），
  `allowed-tools: Read, Bash(curl *)`，**自身不计算价格**；livekernel 持有意图路由、Timo 确定性报价、
  冲突检测、iron-rule-1 sha256 锁定、草稿回复。

## D. NVIDIA 栈技能全量清单（`openclaw/skills/`，磁盘共 **51** 个技能目录）

> 口径说明：磁盘上有 **51** 个技能目录；另有业务主干 `app/skills/` **33** 个；OpenClaw **平台实时登记 47 项**
> （含各来源汇总后的可统计项，详见 [`REAL_STATE.md`](REAL_STATE.md) 可用度盘点，其中 11 完全可用）。
> 三个数不同：口径分别是"openclaw 磁盘目录 / 业务主干目录 / 平台登记可统计项"。

**NVIDIA / 加速计算栈（把模型优化沉淀为技能）**

| Skill | 作用 |
|-------|------|
| `nemotron-customize` | Nemotron 定制/裁剪 |
| `nemo-mbridge-perf-memory-tuning` | NeMo MBridge 性能/显存调优 |
| `nemo-mbridge-perf-moe-optimization-workflow` | MoE 优化工作流 |
| `nemo-automodel-model-onboarding` | NeMo AutoModel 新模型接入 |
| `nemo-retriever` / `nemo-retriever-mcp` / `nemo-rl-docs` | NeMo 检索 / RL |
| `nemotron-speech` | 语音识别的技能封装 |
| `jetson-llm-serve` / `jetson-llm-benchmark` | Jetson LLM 服务 / 基准 |
| `jetson-speculative-decoding` | 投机解码加速 |
| `jetson-optimize-memory` / `jetson-memory-audit` / `jetson-inference-mem-tune` | 内存优化/审计 |
| `jetson-diagnostic` / `jetson-print-device-info` / `jetson-quick-start` | 设备诊断/信息/入门 |
| `dynamo-troubleshoot` / `dynamo-router-starter` / `dynamo-recipe-runner` | NVIDIA Dynamo 排障/路由 |
| `tilegym-cutile-python` | TileGym/cuTile 内核 |
| `vss-setup-video-analytics-api` | Metropolis VSS 视频分析 |
| `tao-setup-nvidia-gpu-host` / `tao-run-inference-service` / `tao-run-on-local-docker` | TAO 部署 |
| `aiq-deploy` / `cuopt-install` / `cupynumeric-install` / `dali-dynamic-mode` | AIQ/CuOpt/cuPyNumeric/DALI |
| `accelerated-computing-cudf` / `warp-eval` | RAPIDS cuDF / Warp |
| `rag-blueprint` / `rag-eval` / `rag-perf` | RAG 蓝图/评测/性能 |
| `quotation-workflow` / `quote-ptuning` | 报价工作流 / P-Tuning |

**制造 / 报价域技能**

| Skill | 作用 |
|-------|------|
| `cnc-quote-system` | CNC 报价系统编排 |
| `dfam-check` | DFM/可制造性、材料、表面处理联动 |
| `material-surface-linkage` | 材料-表面处理联动 |
| `step-factory` | 生成 CAD STEP（实测 350+ 实体/次） |
| `reid-operating-system` | REID 操作系统（报价单生成） |
| `opc-fusion-quote` | OPC 融合报价 |
| `unionskill-quote` | 联合技能报价 |

**通用 / 工程技能**：`code-review`、`diagnosing-bugs`、`domain-modeling`、`tdd`、`grilling`、`superhero`、`customer-communication-writing`（演示/工程辅助）。

## E. Skills 如何"驱动并优化智能体"

1. **驱动**：dispatcher 依据询盘意图把子任务路由到对应 skill（如 CNC 图纸询盘 →
   `step-analysis` → `extract-specs` → `check-dfm` → `cnc-quote` → `verify_gate` → `write-reply`）。
2. **优化**：NVIDIA 栈技能把模型侧优化（NVFP4/显存/投机解码/推理解析）沉淀为可复用 skill，
   反向降低智能体时延与显存；飞轮技能（`customer-flywheel`/`quote-calibration`）只产出**系数提案**
   （COLD 5% / WARM 10% / HOT 15% 上限），**永不改确定性内核 `final_price`**。
