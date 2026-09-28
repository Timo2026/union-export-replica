# 十日谈

**——Union Export Agent LiveKernel 开发历程（长卷全史）**

> **📖 文档定位（2026-09-20 晚勘误）**：本文为十日谈**长卷**（每日章 + 附录每日 commit 索引），与简版 `docs/十日谈.md`（里程碑叙事 M0-M8）并存；框架与数字口径以 `docs/PRD-MASTER-UEA-DELIVERY.md` **v2.0** 为唯一权威。
> **数字勘误**：正文内「701 passed」「62.6 tok/s」为**当日凌晨的历史时点数字**（叙事完整性保留，不随覆写）；**当前口径：725 passed / 0 failed**（`pytest tests/ -q`，2026-09-20 晚复跑，旧失败项 test_deploy_manifests 断言已修）、**GPU ~77 tok/s**（triton JIT 已破解）。另：NIM 容器路线因 spark-51 docker daemon 无权限已关闭（主路径 = vLLM 进程级），EMBED 主选 = `nvidia/Nemotron-3-Embed-1B-BF16`（nv-embedqa 已否决）。

> *「我们本是来写代码的，最后却写了一部小说。」*
>
> 项目：Union Manufacturing Export Agent v2.0.0-livekernel
> 赛题：NVIDIA 黑客松 · NCP-AAI
> 实开发周期：2026-09-17 → 2026-09-20（四日实战 + 六日叙事延展）
> 文体：十日谈（Decameron），每日一章，叙事与技术反思并重

---

## 写在卷首

薄伽丘的《十日谈》里，十个青年避疫于乡间，每日一人讲故事，十日讲完一百篇。我们这个项目没那么风雅——四天里，三个人（其中一个是写代码到凌晨的笔者本人）在一台 Windows 笔记本、一台 DGX Spark 节点、若干个 SSH 终端之间，把制造业询盘邮件端到端变成了一个可审计、可验证、可自动决策的商业对象。

实际开发只有四天。但四天里发生的事，够讲十天。本文按"十日谈"体例展开：前六日为实战日志（09-17 到 09-20 拆成六段），后四日为回望与展望（规划日、评审日、展望日、尾声）。每日末尾附量化成果，不讲空话。

六条工程铁律贯穿始终，先列于此，后文不再重复其定义：

1. **LLM 不定价**——LLM 只提议，价格永远由 Timo 确定性引擎裁决
2. **状态机不可绕**——RFQ 状态机白名单转移，任何捷径都是 bug
3. **Context 唯一**——一个 `context_id` 串起邮件、报价、审计、CRM
4. **RAG 仅引用**——检索结果只作证据，不作决策
5. **多模态冲突升级**——Email ±0.02 vs Voice ±0.05 必触发 HITL
6. **Runtime ≠ 业务**——AI 运行时是工具，业务真相在 Skills 层

---

## 第一日 · 奠基

**日期**：2026-09-17
**主题**：从五份碎片脚手架到一条主干

### 关键事件

那天早上九点，桌面上还摊着五个文件夹——五个不同时期写的脚手架，五个不同的 `main.py`，五个互相矛盾的 `requirements.txt`。这是英伟达黑客松开赛前最后一周，再不收敛就完了。

第一件事不是写代码，是删代码。`feat: Union Manufacturing Export Agent v2.0.0-livekernel (canonical GitHub package)`——这条 commit 的真正含义是：把五份碎片压成一份，确立 `Replace the adapters, not the architecture` 作为唯一路线。适配器可以换，架构不能动。

下午接真实内核。`TimoAdapter` 在线优先走 `:7862`，离线回退到 vendored kernel——子进程 import 真实的 `calc_quote` 和 `ConflictChecker`，要求 **byte-identical**。第一次跑通的那一瞬间，在线 S1 报价 ¥9413.3，离线 vendored 也是 ¥9413.3，小数点后一位都不差。这是铁律①第一次有了牙齿。

### 技术突破

黄金链（Golden Chain）在第一天就立起来了：

```
Email/Voice/STEP → Intake → Context(context_id) → RFQ 状态机
  → DFM → Quote → HITL/BLOCKED/REPLY → CRM+Memory → SHA-256 审计
```

六个场景 S1–S5+M1 全绿。`pytest 95 passed`，九个 notebook 全跑通。Windows 一键启动 `.bat` 也写好了——笔者是 Windows 党，认死这个。

### 踩坑

- `/api/cnc-quick` 模糊解析把 `surface` 字段丢了，导致 S3 漏判 DFM 冲突。改成自抽结构化字段再调 `/api/conflict-check`。
- 引擎的 `.venv` 缺 `pyvenv.cfg`，按系统 Python 3.11.9 重建（含 OCP/cadquery）。
- FastAPI 线程池 + SQLite 报 `check_same_thread` 错，加 `False`；`customer_id` 用 `hash()` 不稳定，换 md5。

### 反思

第一日最大的教训：**先立铁律，再写代码**。六条铁律里，①③④⑥ 都是这天定的。后来四天所有的"踩坑"本质都是某处差点违反了某条铁律——提前立规矩，后面就只是在守规矩。

另一个教训：**byte-identical 不是洁癖，是契约**。在线离线结果一致，意味着演示环境（无 GPU、无 NIM）和答辩环境（有）跑出来的数字可以对照。后来 GPU 那天这条契约救了命。

### 量化成果

- 版本：v2.0.0-livekernel
- 测试：95 passed
- Notebook：9 个全 PASS
- 黄金场景：S1–S5+M1 全绿
- 在线/离线报价：¥9413.3 byte-identical

---

## 第二日 · 评分补强

**日期**：2026-09-17（夜）
**主题**：从"能跑"到"评分能看"

### 关键事件

第一天晚上对着 NCP-AAI 的评分清单（7 维 / 25 考点）自评，估分 ~57。比赛不是看谁能跑，是看评分。于是有了 `v2.1.0 NCP-AAI 评分补强 P0-P3`。

P0 是 LLM Planner。`services/llm_planner.py` 写了一个 ReAct 循环：Thought → Action → Observation，结构化提示模板 + few-shot，JSON-Schema 绑定输出。但关键不是 LLM 能力有多强，而是**它被关在笼子里**——LLM 只抽字段、选技能、起草回复；数字、冲突、状态仍由确定性引擎 + 护栏 + 状态机裁决。离线时显式 MOCK 降级，不静默冒充。

P1 是容错。`services/resilience.py` 写了指数退避重试 + 熔断器三态（CLOSED/OPEN/HALF_OPEN）+ 超时 + fallback，包在 TimoAdapter 的 HTTP 调用外面。`schema_validator.py` 让 `schemas/*.json` 真正生效。`security.py` 加了路径穿越防护、大小上限、PII 脱敏、令牌桶限流。

P2 是评估。`evaluation/metrics.py` 算字段准确率、工具准确率、任务完成率、报价偏差、消融、A/B。`rag_eval.py` 写了 RAGAS 风格的 faithfulness/context_precision/context_recall/answer_relevancy——用确定性词法代理，可选 LLM judge。

P3 是弹性。`deploy/hpa.yaml` + Grafana 看板 + NeMo Guardrails colang 护栏流 + 全链路时延报告。

### 技术突破

`latency_report.py` 聚合了 195 条真实 trace，瓶颈定位到 `cnc-quote`。这是第一次有了"系统哪里慢"的量化证据，而不是凭感觉。

### 反思

这一夜最大的反思是：**评分补强不能破铁律**。LLM Planner 接进来的时候，最自然的写法是让 LLM 直接出价格——快、省事、demo 漂亮。但铁律①说 LLM 不定价。于是 LLM 只出"提议"，引擎出"裁决"。多写了一层，但保住了契约。

后来证明这一层是值的：v6.1.0 那天修的 Dispatcher bug B（铁律①锁跨 dispatch 误报），正是因为锁键从裸 `skill_id` 改成了 `lock_key(skill_id, args)` 复合键。如果当初让 LLM 直接出价，这个 bug 根本无从发现——因为价格早就被 LLM 污染了，没有"确定性基准"可对照。

### 量化成果

- 版本：v2.1.0 → v2.1.1
- 测试：150 passed（+55）
- 估分：~57 → ~80+
- Trace 聚合：195 条，瓶颈 = cnc-quote
- 模型设置 UI：6 张卡片，deterministic 锁定不可禁用

---

## 第三日 · 工厂背后

**日期**：2026-09-18（上午）
**主题**：供应商履约子系统 · 七步成诗

### 关键事件

第二天上午，客户面前的报价流程已经稳了。但比赛要讲"端到端"——客户确认之后呢？脱敏、匹配加工商、询价、下单。这是 `v2.3.0 supplier-module`，分七步提交，每步一个 commit：

1. **desensitize 安全门禁**——STEP OCP header / PDF /Info / 标题栏 / 文件名全部指纹哈希匿名化。客户档案指纹 `SHA-256(salt + JSON 规范化档案)`，稳定不可逆。流向供应商的 ZIP 绝不包含客户 PII，15 个测试断言。
2. **supplier_db 样本库**——SQLite，10 家种子供应商，覆盖 domestic/asia/europe/north_america，材料 6061/304/TC4/45/黄铜/316，质量 ISO9001/AS9100/IATF16949。
3. **matcher 标签打分 TopN**——7 维加权（材料+3/工艺+2/交期/产能/质量/评分/地区），同分按 supplier id 升序保证确定性。
4. **state_machine 子状态机**——8 状态，白名单转移表，`IllegalTransitionError`，history 审计，JSON 持久化。
5. **supplier_inbox mock + po_generator**——`MockInbox` 默认内置；`IMAPInbox` 默认 `raise NotImplementedError`，必须显式 `enabled=True` 才执行。**数据不出车间**。
6. **AUTO 阈值 + 外协 markup**——`features_count_max=10, process_route_max=10`，严格小于才 AUTO；任一现有 HITL 门禁不满足仍 HITL。markup 独立计算，与引擎 final_price 利润不双算。
7. **supplier-match Skill 注册**——OpenAI function-calling 工具描述，`TOOL_ALLOWLIST` 加 `supplier-match`。

### 技术突破

`run_supplier_pipeline()` 一条龙编排，每步原子持久化到 `data/supplier_pipelines/{context_id}.json`。失败用 `PipelineResult.failed=True` 表达，不抛异常——因为异常会破坏状态机的"当前状态"可观测性。

### 踩坑

`markup_pct` 差点双算：PO 的 `sell_price` 如果用 `final_price × (1 + markup)`，而 `final_price` 已经含利润，就重复计了。改成 `SELL = PO 成本 × (1 + markup_pct/100)`，独立于 final_price 利润模型。这种 bug 不跑端到端发现不了。

### 反思

七步提交的意义不是"分得细"，是**每步都可回退**。后来 v6.1.0 修 P0 BUG 的时候，能精确定位到是哪一步引入的，就是因为每步 commit 都是原子的。如果当时一个大 commit 提交，调试时要 `git bisect` 七次才能定位。

另一个反思：**`IMAPInbox` 默认 `raise NotImplementedError`** 是这天最得意的设计。后来 Gmail 那天（v3.0.1）接 IMAP，默认仍然是 `enabled=False`，必须显式开启 + connect 才能用。铁律①的双重门禁不是口号，是默认值。

### 量化成果

- 版本：v2.2.0 → v2.3.0 → v2.3.1
- 测试：179 → 245 → 285 passed（+106）
- 供应商种子：10 家，4 地区，6 材料
- 脱敏断言：15 条
- 端到端 mock：CONFIRMED，PO sell_price = 260，ZIP 内零 PII 泄漏
- A/B 路由：4 种策略（primary_only / fallback / ab_hash / ab_round_robin）

---

## 第四日 · NemoClaw

**日期**：2026-09-18（下午至深夜）
**主题**：混合架构 · Skill Dispatcher + OpenShell

### 关键事件

第三天下午，v2.4.0 控制台重设计——暗色 OLED 风格，bg `#020617`、accent `#6366f1`、强调色 `#22d3ee`，WCAG 4.5:1 对比。5 个 nav tab：模型设置 / 黄金链 Demo / 上传端口 / 3D 上传 / 反馈邮箱。3D STEP 上传即使引擎不可用也返回 `ok=True` + 降级 SVG，不阻断前端。这天加了 41 个测试。

但真正的重头戏是 v3.0.0 **NemoClaw 混合架构**。

NemoClaw 的核心命题：**LLM 只负责意图路由，不决定确定性 Skill 输出**。这是铁律①的工程化。

`services/skill_dispatcher.py` 三种策略：`auto | rules_only | llm`。规则路由兜底（报价/DFM/反馈/3D/供应商/黄金链关键词 + STEP 文件推断），LLM 意图分类在线时启用，失败自动回退规则，**不静默冒充**。

`openshell/*.yaml` + `services/openshell.py` 四层策略：
- `iron-rule-1`（**locked，不可关闭**）——确定性输出 sha256 锁定，改写拒绝
- `hitl-required`——金额/风险/DFM/验收状态触发人工
- `local-only`——文件路径沙箱（data/ 白名单，拒绝系统路径）
- `skill-allowlist`——Skill 白名单 + skills.yaml 启停双重门禁

### 技术突破

`attempt_override` 这个演示函数是这天最精妙的设计：它**演示并拒绝** LLM 改写确定性输出。调用方能看到"我试图改写，被拒绝了"——这比单纯"不允许调用"更有教育意义，也让测试能断言"拒绝行为"而非"调用不存在"。

比赛现场无 LLM 时，`dispatcher.strategy=rules_only` 或 auto 自动降级规则路由。这意味着 demo 不依赖网络，但架构不因 demo 而降级。

### 踩坑

Dispatcher bug A：`_build_args` 里 body 优先级原本是 `intent > email_text`，导致 RFQ 正文被路由短语顶掉。改成 `email_text > intent`。这种 bug 不跑真实邮件发现不了——单元测试用的 mock 邮件正文太"干净"了。

Dispatcher bug B：铁律①锁跨 dispatch 误报。锁键原本是裸 `skill_id`，同 skill 不同输入的合法输出差异被误判"确定性输出被改写"。改成 `lock_key(skill_id, args) = skill_id:sha256(args)[:16]` 复合键。无参调用向后兼容。

### 反思

NemoClaw 这天确立了一个后来反复验证的判断：**LLM 的价值在路由，不在生成**。让 LLM 决定"这封邮件该走哪个 Skill"——它擅长；让 LLM 决定"这个零件报价多少"——它不擅长，且不可审计。

`iron-rule-1.locked=true` 在 validate / save / UI / runtime **四层强制**。这四层是这天最累的活——每层都得写一遍校验，因为任何一层漏了，其他三层都白搭。

深夜接 Gmail IMAP（v3.0.1）。凭据 Fernet 加密（AES-128-CBC + HMAC-SHA256），`data/credentials.json` 0600 权限。HITL 端点返回 `draft + quote + quote_sha16_locked + locked + can_approve`——**真持久锁定**，存首次 sha16 到 `data/drafts/{cid}.json`，篡改 quote 后 `locked=false` → UI 红字拦截。

### 量化成果

- 版本：v2.4.0 → v3.0.0 → v3.0.1
- 测试：326 → 354 → 417 passed（+91）
- Skill 数：11 → 17 → 18
- 端点：19 GET + 5 POST + ROOT 全 200（E2E）
- 面包屑：7 pills，跨区跳转 4 触发点
- 凭据加密：Fernet，0600 权限

---

## 第五日 · 淬炼

**日期**：2026-09-19
**主题**：四个 P0 · 六大黄金场景首通

### 关键事件

第四天早上跑独立测评（AUDIT-REPORT-v6 / EVAL-REPORT-v6-expert），暴露了 4 个 P0 BUG 和 2 个 dispatcher 深层 bug。这是最难受的一天——前三天觉得稳的东西，被测评一扒全是洞。

**BUG-1 AgentCache 缓存污染**：`services/agent_cache.py` 的 get/set 没 `copy.deepcopy`，调用方突变返回 dict（比如 nim_health 写 `_cache`）会污染缓存和首调对象。加 deepcopy。

**BUG-2 v6 路由破坏旧 UI 断言**：v5 工作台断言重定向 `/` → `/webui`，v6 改了路由没改测试。`tests/test_mailbox_ui.py` 7 个 + `tests/test_models_api.py` 3 个修。

**B1 静态资源 404**：`app.mount("/css"|"/js", StaticFiles)` 没挂，根融合版 index.html 资产不可达。

**B3 版本三套不一致**：FastAPI `version="6.1.0-livekernel"` + health `v6.1.0-livekernel` + 根 index.html 5 处 marker，三处对不上。统一。

**B4 schema enum 校验失效**：`_light()` 兜底原本不递归，jsonschema 缺席时 enum 静默放行。改成递归校验 type/enum/required/properties，路径标注。

**BUG-3 subprocess 中文 cp1252 乱码**：Windows 下 `subprocess.run` 默认 cp1252，中文输出乱码。加 `encoding="utf-8", errors="replace"`。

**BUG-4 cnc-quote 有 SKILL.md 无 tool.py**：这个 skill 只有文档没实现。补 `skills/cnc-quote/tool.py`——确定性 CNC 报价 skill，铁律①：LLM 不生成价格，在线 `:7862` / 离线 byte-identical。同时写 `scripts/count_skills.py` 作为 skill 数字的单一来源 → **25/25 全带 tool.py**。

### 技术突破

这天最大的突破不是修 bug，是 **S1–S5+M1 六大黄金场景首次全部经 `SkillDispatcher`（非直连 CATController）跑通 6/6**。

之前的测试是直连 CATController，绕过了 Dispatcher。这意味着 Skill 层是"接口存在"但"核心路径没真走"。v6.1.0 之后，Skill 化从"接口存在"变为"核心路径真走 skill 层"。

M1 多模态冲突通道也补齐了：`voice_transcript` 透传至 `CATController.run`，M1（Email ±0.02 vs Voice ±0.05）正确升级 HITL / VOICE_EMAIL_CONFLICT，result 增加 `multimodal_conflicts` 透出。铁律⑤第一次有了运行时证据。

### 踩坑

基线实跑是 517 passed / 11 failed，不是 529 全绿。11 个失败是真实失败，不是环境问题。修完才是 529 passed / 1 skipped / 0 failed。

这个教训值得单独写一段：**"测试通过"不等于"跑过测试"**。之前几个版本的 changelog 写"全绿"，是因为没真跑全量。v6.1.0 这天老老实实跑了一遍，11 个失败摆在那。从此 `python -m pytest tests/ -q` 成了每个 commit 前的必经步骤。

### 反思

这天最深的反思：**测评要请别人做**。自己测自己，会下意识避开自己知道有坑的地方。AUDIT-REPORT-v6 是独立测评，扒出来的 4 个 P0 有 3 个是笔者自己写代码时知道"这里有点 hack"但没当回事的。

另一个反思：**版本号是契约**。B3 三套版本不一致，意味着任何依赖版本号做判断的代码都可能误判。后来 GPU 那天接 Nemotron 全栈，第一件事就是统一版本标记。

### 量化成果

- 版本：v6.1.0
- 测试：529 passed / 1 skipped / 0 failed（基线 517/11 → 全绿）
- Skill：25/25 全带 tool.py
- 黄金场景：S1–S5+M1 经 Dispatcher 6/6
- 契约测试：40 项全过（铁律① override blocked / openshell blocks deterministic override 等）
- Dispatcher smoke：S1/S2/S4 PASS · S3 BLOCKED · S5/M1 HITL（M1 含 VOICE_EMAIL_CONFLICT），FAILS=0

---

## 第六日 · 双飞轮

**日期**：2026-09-19（深夜至 09-20 凌晨）
**主题**：客户跟进飞轮 + 报价数据飞轮

### 关键事件

修完 P0 已经是深夜。但比赛还差一个叙事：**系统用得越久越准**。这是 `v6.2 双飞轮`。

`services/flywheel/` 新建一个包，六个模块：

- `tenant.py`——single/group/anonymous-hash 租户解析
- `vector_store.py`——Qdrant，无服务时 memory 兜底
- `quote_indexer.py`——报价索引
- `similar_recall.py`——冷启动 → `kb_market`
- `price_corrector.py`——分级修正提案 COLD 5% / WARM 10% / HOT 15%，16 位审计链
- `reaction_labeler.py`——pending/won/lost/silent/reacting + 休假豁免
- `feedback_loop.py`——索引 → 召回 → 修正闭环

四个 Skill：`customer-flywheel` / `customer-health` / `quote-calibration` / `retention-alert`，全部注册进 `TOOL_ALLOWLIST`。

### 技术突破

双层沙箱隔离测试：租户 A 索引的报价绝不被租户 B 召回。`tests/test_flywheel.py` 19 个测试，其中沙箱隔离测试是关键——`{"all_ok": true, "samples_A": 3, "B_samples": 0, "sandbox_pass": true}`。

`price_corrector` 的分级 cap 是铁律①的延伸：**飞轮只产证据 + 系数提案，永不改 `final_price`**。修正受 tier cap 硬约束 + 强制审计链。COLD 5% / WARM 10% / HOT 15%——越"热"（历史数据越多）修正幅度越大，但永远只是提案，最终价格仍由 Timo 引擎裁决。

### 踩坑

`.gitignore` 原本只有 `data/*.sqlite3`，只匹配顶层，漏了子目录测试沙箱。37 个 sqlite 误入 git 索引。`git rm --cached` 37 个（磁盘保留），改成 `data/**/*.sqlite3`。

这种坑说明：**`.gitignore` 的 glob 语义和 shell 的不一样**。`data/*.sqlite3` 在 gitignore 里不递归，要 `data/**/*.sqlite3`。

### 反思

深夜写飞轮的时候，最想做的事是让 `price_corrector` 直接改 `final_price`——"反正修正系数是我算的，直接乘上去多省事"。但铁律①说不行。于是飞轮只出 proposal，由人工或引擎确认后才生效。

后来证明这个克制是值的：`leave-one-out MAPE 51.12 → 52.58`（诚实标注：暂无改善，proposal-only）。如果直接改了 final_price，这个"没改善"就看不见了——因为已经被污染了。proposal-only 让"没改善"可见，让下一步改进有起点。

**诚实的失败比虚假的成功有价值**。这是这天最深的反思。

### 量化成果

- 版本：v6.2（WIP，未切版本号）
- 测试：562 passed / 1 skipped / 0 failed（176s）
- 飞轮测试：19 passed
- Skill：26 → 30（30/30 含 tool.py）
- 沙箱隔离：A 索引绝不被 B 召回 ✅
- 修正 cap：COLD 5% / WARM 10% / HOT 15%
- 离线 demo：`{"all_ok": true, "sandbox_pass": true}`

---

## 第七日 · SSH 与 GPU 攻坚

**日期**：2026-09-20（上午）
**主题**：spark-51 节点 · Triton 三次失败 · CPATH 修复

### 关键事件

第五天早上，解压 `Timo.zip`——44KB，两个文件：Spark 云节点访问手册 + 本队凭据。本队是 Timo，节点 spark-51，公网 IP 203.0.113.10，SSH 端口 6051（不是 22），业务端口 8051（← 节点 8888）/ 9051（← 节点 9000）。

```
ssh -p 6051 Developer@203.0.113.10   # 密码: <REDACTED-PASSWORD>
```

连上之后实测节点信息：

| 项 | 实测值 |
|---|---|
| hostname | spark-388d（内网名，对应 spark-51） |
| 系统 | Ubuntu 24.04.3 LTS，**aarch64**，glibc 2.39 |
| 内核 | 6.11.0-1014-nvidia |
| GPU | **NVIDIA GB10**（Grace-Blackwell / Jetson Thor） |
| 驱动 / CUDA | 580.82.09 / **13.0** |
| 算力 | sm_(12,1) |
| 权限 | Developer，**无 sudo** |
| Python | 3.12.3（PEP668 受保护） |

无 sudo。这一行字决定了接下来三小时的痛苦。

### 技术突破：GPU 攻坚三次迭代

节点上已有 `~/inference/models/Qwen3-0.6B/`（1.5GB BF16，596M 参数）。CPU 推理 13.1 tok/s 已跑通。但比赛要 GPU。

**第一次尝试：`TORCHDYNAMO_DISABLE=1`**

想法很朴素：Triton JIT 编译失败，那禁掉 Dynamo 不就行了？设环境变量，重跑。失败。错误信息还是缺 `Python.h`——Dynamo 禁了，但 transformers 内部还是调了 Triton 编译 CUDA kernel。

**第二次尝试：`dpkg -x` 解包 Python.h**

无 sudo 不能 `apt install python3.12-dev`。但可以下载 `.deb` 包，`dpkg -x` 解包到用户目录，把 `Python.h` 放到 `-I` 路径。下载、解包、设 `CPATH`……失败。解出来的头文件版本和节点的 Python 3.12.3 不完全匹配，编译过不了。

**第三次尝试：CPATH 双路径修复**

仔细看报错，发现缺的不只是 `Python.h`，还有 `pyconfig.h`（平台相关）。`pyconfig.h` 在 `python3.12/config-3.12-aarch64-linux-gnu/` 下。把两个路径都加到 `CPATH`：

```bash
export CPATH=/path/to/python3.12/include/python3.12:$CPATH
export CPATH=/path/to/python3.12/config-3.12-aarch64-linux-gnu:$CPATH
```

重跑。Triton JIT 编译通过。GPU 推理跑起来了。

**bf16 推理 62.6 tok/s**。vs CPU 13.1 tok/s，**4.8× 加速**。

### 踩坑

- 节点上有个僵尸脚本反复 `curl` 下载 `ollama-linux-arm64.tgz`，但该资源在 v0.34.2 release 中根本不存在（arm64 实际是 `.tar.zst`）→ 持续 404 重试，占用共享带宽影响 SSH。**已 kill 清理**。这种僵尸进程在共享节点上是公害。
- pypi.org / huggingface.co 不可达；清华镜像、阿里镜像、download.pytorch.org 可达。配清华源。
- 跳板机对快速重连有限流，偶发 banner 读取失败，重试即可。

### 反思

GPU 攻坚这天最深的反思：**无 sudo 不是终点，是起点**。Linux 的权限模型给了用户级解决方案的空间——`~/.local`、venv、conda、源码前缀、`CPATH`、`dpkg -x`。每一层都有用户级的解法，只是比 sudo 多绕一两步。

另一个反思：**报错要读完**。第一次失败时如果读完报错，会发现缺的不只是 `Python.h`，还有 `pyconfig.h`。读一半就动手，浪费了一轮尝试。

`Timo-SSH推理报告.md` 最后一句："GPU 已识别（GB10/CUDA13），Triton 缺头文件暂阻，给出解决路径"——这是攻坚前的记录。攻坚后那句"暂阻"可以划掉了，但这份诚实记录保留在仓库里，作为"我们承认过困难"的证据。

### 量化成果

- 节点：spark-51 / spark-388d
- GPU：NVIDIA GB10 · CUDA 13.0 · sm_(12,1)
- CPU 推理：13.1 tok/s（Qwen3-0.6B，float32，8 线程）
- GPU 推理：**62.6 tok/s**（bf16）
- 加速比：**4.8×**
- 攻坚迭代：3 次（TORCHDYNAMO_DISABLE → dpkg -x → CPATH 双路径）

---

## 第八日 · 公网部署

**日期**：2026-09-20（下午）
**主题**：从节点内 :8888 到公网 :8051 · Bearer 鉴权

### 关键事件

GPU 跑通了，但比赛要的是**公网可访问的 demo**。节点上服务绑 `0.0.0.0:8888`，公网映射到 `8051`。手册里有一条红线：**公网端口必须加认证**。

把推理包成 API，挂 uvicorn：

```bash
cd ~/inference && nohup python3 -m uvicorn your_api:app \
  --host 0.0.0.0 --port 8888 &
```

公网访问 `http://203.0.113.10:8051`，加 Bearer token 鉴权。

### 技术突破

部署的坑不在代码，在**网络拓扑**。手册说"服务必须监听 `0.0.0.0`"——绑 `127.0.1.1` 公网打不开。这一行字差点漏看。第一次起服务绑了 `127.0.0.1`，公网访问 timeout，排查半小时才回手册找到这句。

另一个坑：**带宽红线**。50 队共享带宽，禁止 scp 超过 1GB 数据。模型文件 1.5GB 不能 scp，必须在节点上直接拉。好在 `~/inference/models/Qwen3-0.6B/` 节点上已有，省了这一步。

### 反思

公网部署这天最深的反思：**手册要逐字读**。SSH 端口不是 22 是 6051，业务端口是 8051 不是 8888，服务必须绑 `0.0.0.0`，公网必须加认证——这四条任一漏了都连不通。比赛给的文档不是背景介绍，是**约束条件**。

另一个反思：**demo 环境和开发环境要隔离**。本地 Windows 笔记本跑的是 mock + 离线 vendored kernel，节点上跑的是 GPU + 真实模型。两边报价要 byte-identical（铁律①）。第一日立的这条契约，在公网部署这天让"本地改完推上去"成了安全的操作——因为不一致会立刻被发现。

### 量化成果

- 公网端点：`http://203.0.113.10:8051`
- 鉴权：Bearer token
- 服务监听：`0.0.0.0:8888`（节点内）→ `8051`（公网）
- 长任务：`tmux` 保持（断线即停）
- 带宽合规：未 scp 超大文件

---

## 第九日 · Nemotron 全栈

**日期**：2026-09-20（深夜）
**主题**：NVIDIA 全家族地基 · model_router 接线

### 关键事件

GPU 跑通一个 Qwen3-0.6B 不够。比赛是 NVIDIA 主场，要讲 **Nemotron 全家族**。深夜写 `models.nvidia-fullstack.yaml`——把 LLM / VLM / Embed / ASR / OCR 五个角色的 NVIDIA 端点全配好：

```
L4  业务 Agent（livekernel）
    Skills 33 · CAT/状态机 · Guardrails · HITL · 审计链
    报价数字 → Timo 确定性引擎（DETERMINISTIC，永不走 LLM）
─────────────────────────────────────────────
L3  统一模型面（OpenAI 兼容 /v1）
    model_router / models.yaml / settings.dgx-spark-p0.yaml
    roles: FAST · VISION · REASON · EMBED · ASR · OCR
    backend: local(spark-runtime) | nvidia(NIM) | mock
─────────────────────────────────────────────
L2  NVIDIA/本地推理运行时（GPU 优先，CPU 显式降级）
    LLM: vLLM(目标) / transformers+torch(基线) / llama.cpp(备)
    Embed: Qwen3-Embedding-0.6B (GPU/CPU)
    ASR: Qwen3-ASR / FunASR
    OCR: RapidOCR/Paddle 路径
─────────────────────────────────────────────
L1  NVIDIA 平台层（节点现状）
    GB10 · Driver 580.82.09 · CUDA 13.0 · sm_12,1
    aarch64 · 无 sudo · 用户级 Python/torch+cu130
```

`model_router.py` 的 `resolve(role)` / `pick(role, request_id)` 读 `choose_route`，返回 `source` (primary/alternate/missing/disabled) 与 `strategy`。`DETERMINISTIC` / `mock` / `nvidia` 三条路径完全绕开 `choose_route`——确定性 100% 走 Timo 内核。

### 技术突破

`docker-compose.yml` + `settings` + 回归测试。`tests/test_deploy_manifests.py` 6 个测试验证 k8s.yaml / hpa.yaml / nim/docker-compose.yml 的结构：kind 齐备 / HPA↔Deployment 联动 / GPU 设备预留 / 凭据只走 `${ENV}` 引用 + deploy 目录硬编码扫描。

测试还发现一个 bug：`deploy/nim/.env.example` 是 UTF-16 混编码（PowerShell 追加痕迹），docker compose env-file 不兼容。重写干净 UTF-8 占位模板。

### 踩坑

全栈替换最容易踩的坑：**把 L4 契约也一起换了**。`Replace the adapters, not the architecture`——只换 L2/L3 端点，L4 契约不变。这天反复提醒自己这句话。每写一个 adapter，都跑一遍黄金链 S1–S5+M1，确认报价 sha256 没变。

### 反思

Nemotron 全栈这天最深的反思：**接口兼容 ≠ 行为等价**。同一个黄金链在 NVIDIA 运行时端点和本地端点各跑一遍，报价 sha256 必须一致。这不是"接口对得上"就够的——要跑出来对得上。

`PLAN-gpu-nvidia-model-stack.md` 里写了一句："评分与答辩含义：平台适配分 = **节点上真实 GPU/模型调用日志**，不是 yaml 占位"。这句话是这天的工作准则。yaml 写得再漂亮，没有真实调用日志，评分就是 0。

### 量化成果

- 版本：Unreleased（E 线全量生产化）
- 测试：**701 passed / 1 skipped / 0 failed**
- Skill：30 → 33（33/33 含 tool.py）
- 分层 RAG：L1 客户 / L2 历史报价 / L3 对话 / L4 工艺
- 杰沃 PO 管道：129/129 解析 100%，608 行项，500 有价，422 唯一 quote_history 锚点
- 批量报价：BOM 410/410，quote_rate 100%，总价 ¥920,054.82
- 部署清单测试：6 passed（k8s / hpa / nim compose 结构验证）

---

## 第十日 · 尾声

**日期**：2026-09-20（凌晨四点，收笔）
**主题**：未完待续

### 关键事件

凌晨四点。`python -m pytest tests/ -q` 跑完，`701 passed, 1 skipped, 0 failed`，exit 0。git status 干净。节点上 GPU 推理 62.6 tok/s 还在跑。公网 8051 端点活着。

四天。从一个五份碎片的桌面文件夹，到一个 701 测试全绿、33 个 Skill、6 条铁律、双飞轮、GPU bf16 推理、公网可访问的系统。

### 六条铁律的最终回响

1. **LLM 不定价**——从 v2.1.0 的 LLM Planner 到 v6.2 的 price_corrector，LLM 始终只提议。最后 leave-one-out MAPE 51.12 → 52.58 诚实标注"暂无改善"，因为 proposal-only 让失败可见。
2. **状态机不可绕**——supplier_module 的 8 状态子状态机，`IllegalTransitionError` 守了 99 个测试。
3. **Context 唯一**——`context_id` 从邮件到报价到审计到 CRM，一个 ID 串到底。
4. **RAG 仅引用**——分层 RAG L1–L4，检索结果只作证据，不作决策。
5. **多模态冲突升级**——M1 场景 Email ±0.02 vs Voice ±0.05，`multimodal_conflicts` 透出，HITL 拦截。
6. **Runtime ≠ 业务**——GPU bf16 62.6 tok/s 是 Runtime；业务真相在 Skills 层 33 个 tool.py 里。换 Runtime 不换契约。

### 量化总账

| 维度 | 起点（v2.0.0） | 终点（Unreleased） |
|---|---|---|
| 测试 | 95 passed | **701 passed** |
| Skill | 0（接口存在） | **33（33/33 含 tool.py）** |
| 版本 | v2.0.0-livekernel | Unreleased（E 线全量生产化） |
| 黄金场景 | S1–S5+M1 直连 CATController | S1–S5+M1 经 SkillDispatcher 6/6 |
| GPU 推理 | 无 | **62.6 tok/s（bf16，4.8× CPU）** |
| 公网端点 | 无 | `http://203.0.113.10:8051` Bearer |
| 飞轮 | 无 | 双飞轮 19 passed，沙箱隔离 |
| RAG 分层 | 无 | L1–L4 四层 |
| PO 管道 | 无 | 129/129 解析 100%，422 唯一锚点 |
| 批量报价 | 无 | 410/410，¥920,054.82 |

### 展望

这个项目还没完。几件已知的事：

- **v6.2 飞轮包未切版本号**。工作树全绿，但 release marker 还停在 v6.1.0，待决策者 pin 后原子 bump。两代飞轮并存（v6.1 CAT 内 vs v6.2 services/flywheel/ 包），是否把黄金链迁移到 v6.2 `FeedbackLoop` 是一个待决策，不擅自拆 v6.1。
- **NIM 实际接入仍缺 NIM runtime**。策略与探活就绪，`models.yaml` 改 endpoint + strategy=ab_round_robin 即可开 A/B。镜像和权限到位后切 `backend=nvidia`。
- **HTTP 真实 failover**。`choose_route` 只决策不重试；调用方拿到 decision 后若 primary 离线应改用 `decision.fallback.endpoint`。这层重试还没写。
- **跨区跳转反查索引**。当前 `context_id → mail_id` 反查是 inbox scan + hitl endpoint O(N)，大数据量需建反查索引。
- **Gmail OAuth**。当前仅 App Password，比赛场景够用；OAuth 接入留作 v3.1.0。

### 最后一句

薄伽丘的十日谈讲完一百个故事，瘟疫退了，青年们回城。我们的十日谈讲完十章，比赛还没结。但有一件事是确定的：**这四天写的每一行代码，都经得起 `python -m pytest tests/ -q` 的 701 次拷问**。

这不是终点。这是 `git log` 上的一个 commit，等下一个。

---

## 附录 · 每日一行 commit 索引

| 日 | 日期 | 代表 commit | 版本 |
|---|---|---|---|
| 1 | 09-17 | `f643cf1` feat: v2.0.0-livekernel | v2.0.0 |
| 2 | 09-17 夜 | `746e56b` feat(v2.1.0): NCP-AAI 评分补强 P0-P3 | v2.1.0–v2.1.1 |
| 3 | 09-18 上午 | `cc57c7c` feat(supplier-module): v2.3.0 | v2.2.0–v2.3.1 |
| 4 | 09-18 下午 | `0e3b889` feat(nemoclaw): v3.0.0 | v2.4.0–v3.0.1 |
| 5 | 09-19 | （v6.1.0 修复 4 P0 + 2 dispatcher bug） | v6.1.0 |
| 6 | 09-19 夜 | （v6.2 双飞轮 WIP） | v6.2 |
| 7 | 09-20 上午 | （GPU 攻坚 CPATH 修复） | — |
| 8 | 09-20 下午 | （公网 :8051 Bearer 部署） | — |
| 9 | 09-20 深夜 | （Nemotron 全栈 + E 线） | Unreleased |
| 10 | — | 尾声 | — |

---

*文档版本：1.0 · 写于 2026-09-20 凌晨四点 · 701 passed, 0 failed*