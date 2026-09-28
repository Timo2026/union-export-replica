# REAL STATE — 节点实测真实状态（DGX Spark）

> 本文件记录 **当前运行节点（DGX Spark）的实测真实状态**，非营销口径。
> 数据来自用户提供的 `nvidia-smi` / `free -h` / `top` / session 状态 introspection。

## 硬件与系统

| 项目 | 实测值 |
|------|--------|
| GPU | NVIDIA **GB10（DGX Spark 级，Grace-Blackwell，Arm CPU + 统一内存）** |
| 驱动 | NVIDIA-SMI **580.82.09**（对应 **CUDA 13.0**） |
| OS | Linux **6.11.0-1014-nvidia (arm64)**，DGX OS **7.2.3** |
| CPU | Arm 多核，观察到的单核 boost ≈ **7.59 GHz**；整体利用率 **< 1%（idle ~98.7%）** |
| 统一内存 | 总计 **≈121 GiB 可用**；实测已用 **≈99 GiB**（大头是 VLLM 进程） |

## GPU / 推理（VLLM 多实例）

| 指标 | 实测值 |
|------|--------|
| GPU 利用率 | **≈96%** |
| GPU 显存 | **≈74 GB**（多实例 2185+66202+6682 MiB，约为可用显存的 ~96%） |
| 推理框架 | **VLLM**（多 `VLLM::EngineCore` 实例） |
| 模型（主力） | **`nemotron-omni-30b-a3b`（NVFP4，any-to-any 视觉+LLM+ASR 统一端点）** |
| 模型（回落） | **stepfun-plan / step-5-preview**（仅回落位，data-stays-local 下不主动出网） |
| 吞吐 | **≈450 tokens/s**（40k 入 + 325 出 / 89s 会话） |
| KV-cache | 命中 **0%**、缓存 **0**（当前无命中） |

## Agent 技能真实可用度（OpenClaw 平台，47 项）

| 状态 | 数量 |
|------|------|
| 完全可用 | **11** |
| 部分可用（需调试） | 4 |
| 不可用（已标记） | 1 |
| 文档型（未实现） | 17 |
| 环境受阻（缺依赖/配置） | 9 |
| 硬件不匹配（本机无法直接跑） | 3 |
| 其他 | 2 |

> 说明：业务主干 `union-export-demo/skills/` 交付 **33 个业务技能目录**；上表 47 项是 OpenClaw
> 平台当前装配的**全部技能**（含 NVIDIA 栈技能、文档型、环境受阻型等）的真实盘点。两者口径不同，均如实列出。

## 典型端到端能力链

| 能力 | 代表技能 | 可用度 | 典型延迟 |
|------|----------|--------|----------|
| 模型推理 | VLLM EngineCore | ✅ | 0.5-2 s/req |
| CAD / 几何 | `step-factory`, `ocp-geometry-code`, `reid-os` | ✅ / 部分 | 5-30 s |
| DFM / 材料 | `dfam-check`, `material-surface-linkage` | ✅ / 部分 | <10 s |
| 报价 / 报价单 | `reid-os`, `email-quote`, `quotation-workflow` | ✅ | 10-30 s |
| 技能实验 | `skill-workshop` 等 | ✅ / 部分 | 1-30 s |

端到端（规划→调度→处理→执行→交付）实测约 **30-90 s**；子任务单步最长约 29 s。

## 网络端口（实测开放）

- **8888**：LiveKernel / union-export Workbench API（公网 NAT → :8051）
- **8002**：VLLM 模型服务（Omni-30B NVFP4）
- **8011**：Nemotron-Embed-1B（RAG 嵌入）
- **9000**：本机 JupyterLab（公网 NAT → :9051，`root_dir=/home/Developer/inference/notebooks`）
- 22（SSH）/ 443（HTTPS）

## 一次真实多模态闭环样例（6061 卡片阅读器外壳）

图纸 → 规格表 → 工艺路线，全链路在 OpenClaw + 本地 NVIDIA 栈上完成：

| 项目 | 规格 |
|------|------|
| 材料 | 6061 铝合金 |
| 主尺寸 | 宽 37 mm / 长 87.70 mm / 高 114.36 mm |
| 孔/螺纹 | Ø2.90 mm ×2，Ø2.05 mm ×3，M2.5-6H |
| 公差 | 未注参照 GB/T 1184-x，角度 0.05 |
| 表面处理 | 喷砂 + 阳极氧化 + 喷漆 |
| 落地 | CNC 铣/钻/抛光/阳极氧化；`step-factory`→`dfam-check`→`material-surface-linkage`→`reid-os`/`livekernel-drawing-pack-quote` |

> 一句话：本机能在 30-90 s 内完成「CAD 建模 → DFM 校核 → 报价 → 交付草稿」闭环，GPU ~96% 满负荷、CPU 基本闲置，适合高吞吐低延迟的制造询报价自动化。
