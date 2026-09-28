# SUBMISSION CHECKLIST — 黑客松交付项 / 时间线 / 评分映射

对齐「NVIDIA DGX Spark 黑客松（第三届）· Agent Skills 开发挑战赛」提交要求。
本复刻包对应一个可提交的 GitHub 标准仓库。

> 口径来源：本清单与保存的《项目提交要求》原文（**8 项交付**、**时间节点**、**100 分评分权重**）逐条核对一致。
> （原始两份文档不在 Spark 节点文件系统内，其要点已由早期会话留存并核对，非推测。）

## A. 提交至组委会表单的 URL 链接

| # | 交付项 | 状态 | 说明 / 负责 |
|---|--------|------|-------------|
| 1 | 项目开源提交（GitHub/码云 URL） | 🟢 交付包就绪（zip）· 🟡 待你建仓推送 | 交付包 `union-export-replica-github-20260928.zip`（= GitHub "Download ZIP" 形态，提交 `ed5432c`、1349 文件）已生成，`scripts/verify_replica.sh` 自检 **PASS**（IP·token·API-key 三扫 0 命中）；差异/排除项见 [`DELIVERY.md`](DELIVERY.md)。⚠️ 打包时发现并已脱敏 1 处 StepFun **真实 API key**（`engine/完善交付.md`），**推送前请在 StepFun 后台轮换该 key**。**建仓与推送仍需你本人**在有账号的终端执行（见 [`../ops/GITHUB_PUSH.md`](../ops/GITHUB_PUSH.md)） |
| 2 | 作品演示视频（B站 URL） | 🟡 脚本就绪待录制 | 分镜/配音稿/隐私红线见 [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md)；核心：黄金链现场 + 铁律① sha256 + 离线六场景兜底（`python app/scripts/run_demo.py --offline`） |
| 3 | 黑客松十日谈征文（CSDN/知乎 URL） | 🟡 成稿就绪待发布 | 可直接发 CSDN/知乎 的成稿见 [`十日谈.md`](十日谈.md)，长卷附录见 [`DECAMERON.md`](DECAMERON.md) |
| 4 | 团队合影（可云合影）上传表单 | ⛔ 待拍摄 | 非同城可云合影 |

## B. GitHub README 中应包含（本包已满足）

| # | 交付项 | 状态 | 位置 |
|---|--------|------|------|
| 5 | 项目说明文档（500 字以上） | ✅ | [`../README.md`](../README.md)（含 NVIDIA 全栈 × 项目融合 + 真实状态） |
| 6 | 部署说明 | ✅ | [`DEPLOYMENT.md`](DEPLOYMENT.md) / [`REPRODUCTION.md`](REPRODUCTION.md) |
| 7 | 技术栈说明（NVIDIA SDK/模型 + StepFun） | ✅ | [`TECH_STACK.md`](TECH_STACK.md) / [`NVIDIA_FULLSTACK.md`](NVIDIA_FULLSTACK.md)（StepFun 如实：fallback 位） |
| 8 | Skill Markdown 文件 | ✅ | `app/skills/*/`（33）+ `openclaw/skills/*/SKILL.md`；索引见 [`SKILLS.md`](SKILLS.md) |

## C. 关键时间节点

- 训练营：09-20（已过）
- **线上预赛提交截止：09-29 23:59**（优先交付 1/2/3 URL）
- 算力节点关闭：09-30 —— 推送/复现须在断算力前完成
- 十强公布：10-08
- 线下决赛路演：10-15 13:30–17:00（苏州金鸡湖）
- 颁奖：10-16 上午

## D. 评分维度 → 本作品的对应证据

| 维度 | 权重 | 对应证据 |
|------|------|----------|
| 实用性 / 行业落地 / 技术创新 | 25% | 真实制造询报价黄金链（6061 样例，30–90s 闭环），HITL/BLOCKED 人机协同 |
| 智能体与模型优化深度（Skills 设计与融合） | 25% | [`SKILLS.md`](SKILLS.md)：iron_rule 分级 + openshell 护栏 + 51 个 openclaw 技能 |
| 项目完整性（功能/前后端/文档） | 20% | FastAPI + Workbench UI + 33 业务技能 + 完整 `docs/` |
| 平台适配（DGX Spark / NVIDIA / StepFun） | 15% | [`NVIDIA_FULLSTACK.md`](NVIDIA_FULLSTACK.md) + [`REAL_STATE.md`](REAL_STATE.md)：GB10/NVFP4/vLLM/450tok·s⁻¹ + StepFun fallback 位 |
| 演示效果（Demo 视频） | 10% | 脚本就绪（[`DEMO_SCRIPT.md`](DEMO_SCRIPT.md)），待你录制（对应交付项 2） |
| 赛事征文（十日谈） | 5% | 成稿就绪（[`十日谈.md`](十日谈.md)），待你发布（对应交付项 3） |

## E. 我能代办 vs 需你执行

- 我代办（本包已完成）：README/docs/真实状态/技能索引/部署/复现/清单/脱敏。
- 需你本人：①GitHub/码云建仓并授权推送（外发 + 账号，见 ops/GITHUB_PUSH.md）②按 [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) 录 B站视频 ③把 [`十日谈.md`](十日谈.md) 发布到 CSDN/知乎 ④团队合影。
