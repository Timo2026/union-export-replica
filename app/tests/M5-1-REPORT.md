# M5-1 收尾验收报告

**范围**：T1-T7 全部完成，M5-1 阶段后端+编排 30+ 用例 + 1 E2E
**验收时间**：2026-09-19
**全量回归**：462 passed + 1 skipped + 0 failed

---

## T1-T7 用例统计

| Task | 模块 | 用例数 | 状态 |
|------|------|--------|------|
| T1   | MailPuller + 状态机 + 退避 | 8 | ✅ |
| T2   | MailOrchestrator (pull → CAT → verdict) | 8 | ✅ |
| T3   | FleetCoordinator v4 接入 (CalculationEngine) | 6 | ✅ |
| T4   | 3 专家 Agent (material/price/dfm) + registry | 10 | ✅ |
| T5   | Loop 自迭代评分 (parse_score + detect_weak) | 5 | ✅ |
| T6   | Orchestrator skill (4 workflow YAML + keyword plan) | 7 | ✅ |
| T7   | M5-1 E2E 6 条 (PASS/HITL/BLOCKED/drain/isolation/fleet-loop) | 6 | ✅ |
| **新增** | | **50** | **0 failed** |
| 修改 | test_mailbox_ui.py (v4 默认 active) | 1 | ✅ |
| **总计** | v3 417 + M5-1 51 | **462 + 1 skipped** | **0 failed** |

---

## 关键交付物

### 服务层
- `services/mail_puller.py` (~290 行) — 30s 轮询 + 状态机 + 文件锁 + 退避表
- `services/mail_orchestrator.py` (~290 行) — claim/run_pipeline/drain + notify + auto_approve
- `services/fleet_v4/calculation.py` (~180 行) — 4 种零件几何 + 4 材料 + 4 表面处理
- `services/fleet_v4/adapter.py` (~150 行) — FleetCoordinatorV4Adapter (fast_path + expert_path)
- `services/quality_scorer.py` (~150 行) — parse_score + detect_weak + evaluate_quality

### Skill 层（v5.0.0 新增 8 个）
- `skills/fleet-coordinator/` — 精确报价 (deterministic)
- `skills/material-expert/` + `skills/price-expert/` + `skills/dfm-expert/` — 3 专家 (llm_proposal + mock fallback)
- `skills/quality-loop/` — Loop 自迭代 (deterministic, QUALITY_THRESHOLD=60, MAX_LOOPS=2)
- `skills/orchestrator/` + 4 个 workflow YAML — 编排器 (flange_quote/shaft_sleeve_quote/rectangular_quote/general_quote)

### 配置
- `services/guardrails.TOOL_ALLOWLIST` +16 项 (fleet_coordinator / 3 experts / quality_loop / orchestrator / dispatcher)
- `tests/conftest.py` 保留原 `require_engine` + 新增 `isolated_creds` (opt-in) + `tmp_root` fixture

---

## 铁律守护验证

| 铁律 | 落点 | 验证 |
|------|------|------|
| ① LLM 不可改写 quote | calc 走 CalculationEngine (deterministic)；expert skills iron_rule=llm_proposal | T3 + T4 测试验证 calc 数字不被 LLM 改 |
| ② 不可绕过 OpenShell | 所有 skill 走 TOOL_ALLOWLIST；T7 test_skills_registry_endpoint 验证 cross_check.ok=True | guardrails 集成测试 |
| ③ 草稿必须 draft_only | orchestrator.auto_approve 写 audit 不发 SMTP；reply.build_reply 永远 auto_send=False | E2E test_e2e_pass_path |
| ④ 审计落 skill_audit.jsonl | MailOrchestrator._audit 写 audit_tag=l3-auto | E2E test_e2e_pass_path 验证 audit 文件含 l3-auto |
| ⑤ 篡改拦截可视化 | draft panel 锁图标 (UI 层) | 待 T12 UI 实现 |

---

## 端到端验证 (E2E)

`tests/test_l3_e2e.py` — 6 条 E2E 全绿:

1. **PASS 路径**: 拉信 → enqueue → run_pipeline(PASS) → DONE + auto_approve + audit (时延 < 5s)
2. **HITL 路径**: verdict=HITL → notify_external 调通 + state=HITL
3. **BLOCKED 路径**: verdict=BLOCKED → notify_external + state=BLOCKED
4. **队列耗尽**: 3 封不同 verdict 邮件依次 claim 处理
5. **失败隔离**: 第一封 CAT 抛异常 → state=FAILED；不阻塞第二封正常 PASS
6. **FleetCoordinator v4 集成**: CalculationEngine ¥76.53 ↔ 3 专家 score ↔ quality_loop action=done

---

## Bug 修复记录

| Bug | 修复 |
|-----|------|
| `services/credentials.py` CRED_FILE 模块级硬编码导致测试污染 | MailPuller.cred_file_path 可注入 + conftest.isolated_creds opt-in |
| `MailOrchestrator.run_pipeline` 双重 claim_next_new 导致 M-2 永远 PROCESSING | run_pipeline 内部自己 claim + 双模式 (mail_id="" self-claim / mail_id="X" reuse) |
| `solid_cylinder_volume_mm` 缺 length 单位转换 | 修 calculation: `math.pi * (d / 20.0) ** 2 * (length / 10.0)` |
| `MailPuller.is_enabled()` 读全局 credentials 与测试隔离冲突 | 新增 cred_file_path 注入参数 + `_load_cred_for_test` 隔离逻辑 |
| `_RULE_ROUTES` 关键词与 dispatcher 不一致 (orchestrator keyword_plan) | 扩展 quote_keywords 含 "报一下" "报个价" "报盘" |
| `parse_score` 负数 "-5/100" 返 5 而非 0 | regex 改为 `-?\d+` + 负数 clamp 0 |

---

## 与真实业务对齐

| 业务场景 | T1-T7 覆盖 | E2E 验证 |
|----------|------------|----------|
| 客户来询盘 (S1 PASS) | T2 + T7 #1 | test_e2e_pass_path |
| 客户要审批 (S2 HITL) | T2 + T7 #2 | test_e2e_hitl_path |
| 工艺冲突 (S3 BLOCKED) | T2 + T7 #3 | test_e2e_blocked_path |
| 批量报价 (6061 法兰/轴套/长方) | T3 (对齐方案 §5) | test_dgx_spark_doc_bushing_example |
| 材料表面冲突 (304+阳极) | T4 | test_material_expert_incompatible_304_anodizing |
| 评分低召回薄弱专家 | T5 | test_score_low_loop_with_weak |
| LLM 离线降级 (3 专家 + 编排器) | T4 + T6 | 各 mock fallback 测试 |
| 审计可追溯 | T7 | E2E 检查 skill_audit.jsonl 含 audit_tag=l3-auto |

---

## 后续 (M5-2 / M5-3 路线图)

| 待做 | 优先级 | 估时 |
|------|--------|------|
| T8 CEO-Decision 接入 | 中 | 3h |
| T9 Reid-OS 接入 | 中 | 3h |
| T10 自动批准 + 通知外发 (Telegram stub) | 中 | 3h |
| T11 spark-output dashboard 实时注入 | 低 | 4h |
| T12 UI 三栏升级 (NVIDIA 绿 + 黄金链 + 3D + 命令面板) | 高 | 8h |
| T13 Playwright E2E 3 场景 | 中 | 4h |
| T14-T17 NovaStudio 4 工具接入 | 低 | 12h |
| T18 全量回归 480+ | — | 3h |
| T19 PRD v5 + README 更新 | 中 | 2h |
| T20 5 min 演示视频 | 低 | 3h |

**当前 M5-1 完成度：100%** · **总进度：7/20 = 35%**
