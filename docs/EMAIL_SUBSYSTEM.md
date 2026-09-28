# EMAIL SUBSYSTEM — 邮件子系统（draft-only · data-stays-local）

> 邮件子系统让智能体能**被动接收**询盘（IMAP 拉取）并**草稿回复**，但**默认全关、默认只草稿、默认不外发**。
> 这是铁律①（data-stays-local）在邮件域的集中体现。以下依据源码（`app/services/*.py`）如实记录。

## 模块总览（`app/services/`）

| 模块 | 职责 | 默认态 |
|------|------|--------|
| `mail_puller.py` | 后台 **30s 轮询** Gmail IMAP（imap_tools）；落 `.eml`+`.meta.json`+追加 `pending.jsonl`(state=NEW)；失败退避 30s→2min→5min(封顶5min)；`MailOrchestrator(T2)` 订阅 NEW 行触发 `CATController.run` | **禁用**（须 `settings.gmail.enabled=true` 且凭据存在才启动） |
| `gmail_imap.py` | Gmail/QQ IMAP 拉信封装（`imap.gmail.com:993` / `imap.qq.com:993`）；拉信只写本地 `data/mailbox/*.eml` | 禁用（双重门禁：skill_config + settings） |
| `gmail_api.py` | `/v1/gmail/*` 端点：连接 + 拉信 + 设置；`enabled=False` 需显式 `POST /settings {enabled:true}` | 禁用 |
| `egress_gate.py` | **集中式外发主闸（egress kill-switch）**：smtp/imap/webhook 任一真实外发必过此闸 | **默认 DENY（fail-safe）** |
| `reply.py` | 英文回复**草稿**生成（`build_reply(ctx, verification)`），分 PASS/HITL/BLOCKED | `draft_only`，`auto_send=False` |

## 核心铁律

1. **egress 默认 DENY**：`egress_gate.check(channel)` 对任何真实外发（smtp/imap/webhook）默认拒绝；
   仅当 `settings.yaml` `egress.allow=true` + `channels.<ch>=true`**且/或**`UEA_EGRESS_ALLOW="smtp,webhook"|"all"` 才放行。
   总开关 `allow=false` 时逐通道 `true` 也拒（主闸优先）。被拒尝试写审计 `data/egress_gate.jsonl`（best-effort）。
2. **只草稿、LLM 不产最终数字**：`reply.py` 的回复只反映**确定性引擎**产出的事实（报价/交期/冲突/替代）；
   LLM 负责措辞，**不生成最终价格**（价格一律来自 Timo 内核）。默认 `draft_only`，高风险不自动发送。
3. **凭据不落明文**：邮箱凭据经 `services/credentials.py` 以 **Fernet 加密**存储与解密加载（`CRED_FILE`），不在代码/配置中明文，不外发。
4. **默认禁用 + 显式日志**：IMAP 不可达 → 返回 error，**不静默冒充成功**；轮询/发送失败显式记录，不造假。

## 状态机（mail_puller）

`NEW → PROCESSING → DONE / HITL / BLOCKED / FAILED / DEAD`（DEAD=重试超限死信，不再自动重回队列）。
原子写（文件锁 + 临时文件 + rename）；重试上限 3，`PROCESSING` 租约超时 300s 可被 reclaim。

## 开启（本地，非默认）

```bash
# 1) 存凭据（Fernet 加密，本地）
# 2) 开 gmail 设置：POST /v1/gmail/settings {"enabled": true, host, port, folder}
# 3) 仅当你确实要外发时，才授权 egress（默认保持 DENY）：
#    settings.yaml: egress.allow=true, channels.{smtp:true}
export UEA_EGRESS_ALLOW="smtp"    # 或在 settings 里开
```

> **复刻注意**：凭据文件（`credentials*`、`data/gmail_settings.json`、`data/mailbox/`）**不入库**，见 `.gitignore`。
> 默认状态下邮件子系统**只读草稿、不发送**，符合 data-stays-local。
