# Union Export Replica — NVIDIA 全栈 × 制造询报价 Agent（可复现交付包）

> 本仓库是运行在 **NVIDIA DGX Spark** 上的「AI 制造询报价智能体」的**忠实复刻包**：
> 后端/编排/技能取自**本节点真实运行态**（livekernel `:8888`、确定性引擎 `:7862`、6 服务 tmux 编排）；
> **线上对外 UI（`http://<NODE_PUBLIC_HOST>:8051`）**是 React/Vite 编译工作台 `v7.1.0`，其编译产物已与线上**逐字节核对（主 bundle md5 一致）**并纳入本包（[`app/webui-dist/`](app/webui-dist/)）。
> 目标是让任何持有一台 DGX Spark（或等效 GB10 主机）的人，**按本文档即可复刻同一套系统**。

---

> **⚠️ 前端真相（重要，勿混淆）**：你在线上 `:8051` 看到的工作台是 **React/Vite 编译版（`v7.1.0`，livekernel）**；本包已把它的**编译产物按 md5 逐字节纳入** [`app/webui-dist/`](app/webui-dist/)。而 `app/index.html`（v6.1.0 静态）与 `app/webui/index.html`（控制台 v12 融合版）是**本节点开发期遗留的静态 UI，不是线上 `:8051` 那一个**——此处如实标注。详见 [`app/webui-dist/README.md`](app/webui-dist/README.md)。

## 一、NVIDIA 全栈 × 本项目融合（核心看点）

本项目不是"调用某一个大模型"，而是把 **NVIDIA 从硬件到推理到模型优化的整条栈**，深度焊接进一条**确定性的制造询报价流水线**：

| NVIDIA 全栈层 | 在本项目中的角色 | 真实证据（节点实测，见 [`docs/REAL_STATE.md`](docs/REAL_STATE.md)） |
|---------------|------------------|------------------|
| **GB10 硬件**（Grace-Blackwell，Arm CPU + 统一内存，≈128GB 级） | 让"多模态大模型 + 向量检索 + CAD 几何 + 确定性计价"同驻一机，**数据不出本机** | 统一内存实测 ≈121GiB，可用即 128GB 级 |
| **CUDA 13.0 / 驱动 580.82.09 / DGX OS 7.2.3** | NVFP4 内核与 FlashInfer JIT 的运行底座 | `nvidia-smi 580.82.09`，`CUDA 13.0` |
| **vLLM 多实例**（多 `VLLM::EngineCore`） | 并发承载 Omni 多模态 / Embedding / 轻量辅助三类模型服务 | GPU 利用率 **≈96%**，显存 **≈74GB** |
| **Nemotron-Omni-30B-A3B（NVFP4）** | any-to-any 统一端点：**视觉（图纸/照片）+ 语言（询盘）+ 语音（ASR）**一次接入 | 主端点 `:8002`，吞吐 **≈450 tokens/s** |
| **Nemotron-Embed-1B（NVFP4）** | 询盘/物料知识检索（RAG）的语义向量（query:/passage: 前缀） | 嵌入服务 `:8011` |
| **Nemotron 推理优化**（NVFP4 / 显存调优 / 投机解码 / `nemotron_v3` reasoning-parser） | 把模型侧优化沉淀为可复用 Agent Skills，反向压低智能体时延与显存 | `.openclaw/skills/` NVIDIA 栈技能 |
| **NeMo Guardrails** | 询盘请求的软护栏（越界/敏感分流） | `nemo_soft` 护栏 |
| **OpenClaw + Agent Skills 编排** | 把上面各层编排成"图纸→DFM→报价→交付草稿"闭环 | 33 业务技能 + 平台 47 技能（11 完全可用） |

**融合的工程要点**：LLM **只提议、不定价**。所有最终价格、DFM 冲突、裁决由**确定性 Timo CNC 引擎**（`:7862`，sha256 锁定铁律①）计算；Nemotron-Omni 负责看懂图纸和询盘意图，Nemotron-Embed 负责召回工艺/物料知识，vLLM 负责把这条链在 GB10 上以 30–90s 的端到端延迟跑完，而**全程数据不出本机**（egress DENY，HF 离线，邮件只出草稿）。这是"NVIDIA 全栈落到一个具体行业问题"的完整样例。

> 关于**阶跃星辰 StepFun（stepfun-plan / step-5-preview）**：如实说明——它只作为**回落位（fallback）**，气隙（air-gapped）/ data-stays-local 下不会主动出网；本地 NVFP4 Nemotron 是唯一主力。详见 [`docs/TECH_STACK.md`](docs/TECH_STACK.md)。

---

## 二、一个真实闭环（多模态）

一次真实的多模态询报价（6061 铝制卡片阅读器外壳，全流程在 GB10 本地完成）：

- **输入**：一张含公差的工程图纸 → Nemotron-Omni（视觉）抽规格 → Embed-1B 召回材料/表面处理知识。
- **编排**：`step-factory`（CAD 生成 350+ 实体 STEP）→ `dfam-check`（DFM/材料/表面联动）→ `material-surface-linkage` → `reid-os` / `livekernel-drawing-pack-quote`。
- **定价**：Timo 确定性引擎出价（LLM 望价兴叹、无权改写）。
- **产出**：报价草稿（**egress DENY，仅草稿不发送**）。
- **实测**：端到端 **30–90s**，GPU ≈96%，CPU 基本闲置。详见 [`docs/REAL_STATE.md`](docs/REAL_STATE.md)。

---

## 三、目录结构（复刻包）

```
union-export-replica/
├─ README.md                       ← 本文件（项目说明 + NVIDIA 全栈融合）
├─ LICENSE                         ← MIT（源自 union-export-demo）
├─ .gitignore
├─ app/                            ← 业务主干：livekernel FastAPI（= union-export-demo）
│  ├─ services/                    ← api_server / 编排器 / 邮件子系统
│  ├─ skills/                      ← 33 个业务技能
│  ├─ config/                      ← models.nvidia-fullstack.yaml（已脱敏）/ skills.yaml 等
│  ├─ webui-dist/                  ← 线上 :8051 的 React/Vite 工作台 v7.1.0（与线上 md5 一致）
│  └─ requirements.txt
├─ engine/                         ← 确定性内核：Timo CNC 引擎（= timo_engine）
│  ├─ app/main.py  └─ environment.yml（conda: step-render, cadquery/trimesh/ezdxf）
├─ openclaw/skills/                ← OpenClaw Agent Skills（NVIDIA 栈 + union-export 桥接）
├─ cnc_inputs/step_samples/        ← 代表性 CAD .step 输入样例
├─ ops/node_services.sh            ← 6 服务 tmux 编排（幂等，采用已在监听者）
├─ models/                         ← 模型清单 MODELS.md + 拉取/启动脚本（非权重）
├─ env/                            ← conda 环境规格 + requirements 副本
└─ docs/                           ← 真实状态/技术栈/部署/技能/架构/复现/清单 等
```

> 不随包分发：**模型权重**（多 GB NVFP4）、**conda 环境二进制**、`node_modules`、
> **运行时订单库**（已删除）、任何**密钥/IP/token**（已脱敏）。这些一律用**清单 + 脚本**方式复现。

---

## 四、快速开始（复刻）

完整步骤见 [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md)，摘要：

```bash
# 0) 前置：一台 DGX Spark / GB10（CUDA 13.0、驱动 580+）；conda；已装在 ~/nvidia/hf-cache 的 NVFP4 模型
# 1) 建环境
conda env create -f env/step-render.yml
conda env create -f env/nemotron.yml
# 2) 拉取模型（权重经 HF 离线缓存挂载，不入库）
bash models/fetch_and_launch.sh          # 下载 + 起 vLLM(Omi:8002/Embed:8011/Qwen:8902)
# 3) 起确定性内核 + 编排器
bash ops/node_services.sh start
curl -s http://127.0.0.1:8888/health     # 应同时探活 livekernel 与 Timo 引擎
# 4) 一键自检（可选）
bash scripts/verify_replica.sh
```

---

## 五、文档索引

| 文档 | 内容 |
|------|------|
| [`docs/REAL_STATE.md`](docs/REAL_STATE.md) | **节点实测真实状态**（GPU/RAM/吞吐/47 技能盘点/端口/多模态样例） |
| [`docs/TECH_STACK.md`](docs/TECH_STACK.md) | 技术栈：NVIDIA SDK/模型 + StepFun（fallback 位，如实） |
| [`docs/NVIDIA_FULLSTACK.md`](docs/NVIDIA_FULLSTACK.md) | NVIDIA 全栈与本项目融合详解 |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | 部署说明 |
| [`docs/SKILLS.md`](docs/SKILLS.md) | Agent Skills 全景与护栏模型 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 架构与数据流 |
| [`docs/EMAIL_SUBSYSTEM.md`](docs/EMAIL_SUBSYSTEM.md) | 邮件子系统（IMAP 拉取 / 草稿回复 / 出网关） |
| [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md) | 如何从零复刻 |
| [`docs/MANIFEST.md`](docs/MANIFEST.md) | 原始→复刻路径映射 + 版本 + 完整性说明 |
| [`DELIVERY.md`](DELIVERY.md) | **交付包说明**：zip 内容、相对源副本的 4 处差异、有意排除项、验证步骤 |
| [`docs/SUBMISSION_CHECKLIST.md`](docs/SUBMISSION_CHECKLIST.md) | 黑客松交付项 / 时间线 / 评分映射 |
| [`docs/十日谈.md`](docs/十日谈.md) | **参赛征文成稿**（CSDN/知乎 可直接发布） |
| [`docs/DECAMERON.md`](docs/DECAMERON.md) | 十日谈长卷附录（逐日 事件/突破/踩坑/反思/量化） |
| [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) | **B站演示视频分镜脚本**（配音稿/命令/隐私红线） |

---

## 六、红线（务必遵守）

- **数据不出本机**：egress 全 DENY，HF 离线（`HF_HUB_OFFLINE=1`），邮件**只草稿不发送**。
- **LLM 不定价**：价格/DFM/裁决唯一权威是确定性 Timo 引擎（铁律①，sha256 锁定）。
- **不入库**：节点公网 IP / SSH 端口 / token / `STEPFUN_API_KEY`。本包 `public:` 已占位为 `NODE_PUBLIC_HOST`。
