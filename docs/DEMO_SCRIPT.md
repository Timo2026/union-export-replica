# DEMO SCRIPT — B站演示视频分镜脚本

> 目标：一段 **4–5 分钟**的实录，向评委证明三件事——**①价格谁生成（确定性引擎）②Skills 管窄触发与业务能力 ③跑在 DGX Spark / NVIDIA 全栈上、数据不出本机**。
> 运行前提：服务已在跑（`bash ops/node_services.sh start`），或至少 `curl /health` 通过。若线上不稳，用 `run_demo.py --offline`（六场景）兜底录屏。
> **录前必读 [隐私红线](#附录b录制红线)**：打码客户信息，画面不露 token / 公网 IP / `.env`。

---

## 分镜表

| # | 时间 | 画面 | 配音稿（可照读） | 屏显 / 命令 |
|---|------|------|------------------|-------------|
| 0 | 0:00–0:15 | 片头：终端 `nvidia-smi` + GB10 桌面 | "这是一台 NVIDIA DGX Spark。我们不演示聊天，我们演示**一单可审计的生意**。" | `nvidia-smi`（CUDA 13.0 / 580.82.09） |
| 1 | 0:15–0:45 | 一句话定位卡 | "LLM 提议，**确定性引擎裁决价格**，Skills 管窄触发，DGX Spark + Nemotron 给算力。数据全程不出本机。" | 大字卡片：四句定位 |
| 2 | 0:45–1:30 | 系统全貌：六服务 + 健康检查 + 负载 | "六个服务同驻一机：多模态 Omni、向量 Embed、轻量兜底、确定性引擎、编排器。健康检查一次探活引擎与内核；GPU ≈96%，CPU 基本闲置。" | `bash ops/node_services.sh start`；`curl -s 127.0.0.1:8888/health`；`nvidia-smi` |
| 3 | 1:30–3:00 | **黄金链现场**：投一张 STEP（box/bracket） | "丢一张 6061 铝外壳图纸进去。链路：抽规格 → 检索材料知识 → STEP 几何 → DFM 检查 → 报价 → 校验 → 生成草稿。端到端 30–90 秒。" | Workbench UI 选/上传 `cnc_inputs/step_samples/*.step`；切到编排日志看 `step-analysis→extract-specs→dfam-check→cnc-quote→verify→write-reply` |
| 4 | 3:00–3:40 | **铁律① 现场**：确定性 vs 提议 | "价格不是我（模型）出的。看这里：模型只提交'提议'，Timo 引擎按 sha256 锁定出价，LLM 无权改写。换后端，价格不变。" | 引擎日志 / 报价单上的 sha256 指纹；可并排跑 local vs Nemotron 两次对比 |
| 5 | 3:40–4:20 | **Skills 深度**：negative trigger + A/B | "会报价不稀奇，**不该报时纹丝不动**才值钱。丢一句无关输入（'今天天气'）——不触发任何业务 skill。再看 A/B：关掉 Skills，字段准确率掉、HITL 拦截率掉。" | 控制台输入无关 query → 无 skill 触发；展示 A/B JSON 的两个数 |
| 6 | 4:20–4:50 | **NVIDIA 全栈收尾** | "从 GB10 到 CUDA 到 NVFP4 到 Nemotron，再到把优化沉淀成 Skills——全栈焊进一条确定性的制造流水线。StepFun 只作回落位，数据不出本机。" | 可放一张全栈架构图（`docs/NVIDIA_FULLSTACK.md`） |
| 7 | 4:50–5:15 | 结尾 | "30 秒口径：我们让 Agent 做成**可验证的生意**。代码与复现见仓库，扫码/见简介。" | 大字 30 秒口径 + 仓库 URL + 团队名 |

> 若删减到 ~3 分钟：保留场景 **0 / 3 / 4 / 7**（钩子→黄金链→铁律①→结尾）即可撑起核心叙事。

---

## 附录 A · 离线六场景兜底（run_demo.py --offline）

若不便起真实服务，用应用自带 `run_demo.py --offline` 的六个预置场景录屏（确定性、可复现、不依赖网络）：

```
# 从仓库根目录运行（六场景，确定性、可复现、不依赖网络）
python app/scripts/run_demo.py --offline
```

六场景通常覆盖：邮件询盘、语音询盘、STEP 图纸、批量化报价、HITL/BLOCKED 人工介入、回复草稿生成。逐个跑、逐个念"这一环谁在裁决"即可。

---

## 附录 B · 录制红线（隐私 / 合规）

- **打码**：客户名、邮箱、地址、真实订单号一律遮挡或替换为样例。
- **不露**：JupyterLab token、节点公网 IP、SSH 端口、`STEPFUN_API_KEY`、任何 `.env`。用 `127.0.0.1` 或 `<NODE_PUBLIC_HOST>` 占位。
- **发送**：演示中邮件系统只出**草稿**，不点发送；强调 egress DENY、data-stays-local。
- **数字**：口播用"约/数百 token·s⁻¹"等近似说法，精确值引 `docs/REAL_STATE.md`，避免不同取数窗口翻车。

---

## 附录 C · 平台投稿建议（B站）

- 标题示例：《DGX Spark 上的一单生意：LLM 不定价，引擎 sha256 锁死｜NVIDIA 黑客松》。
- 标签：`NVIDIA DGX Spark` `Nemotron` `NVFP4` `vLLM` `Agent Skills` `NCP-AAI` `智能制造` `开源`。
- 简介区放：仓库 URL（推送后回填）+ "复现见 README → docs/REPRODUCTION.md"。
- 封面用场景 4（铁律① sha256）那一帧，最有记忆点。
