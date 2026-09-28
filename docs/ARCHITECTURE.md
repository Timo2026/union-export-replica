# ARCHITECTURE — 架构与数据流

```
                    ┌───────────────────────────────────────────────────────────┐
   RFQ 邮件/图纸 ─▶ │  OpenClaw  union-export 桥接 skill (v6.3.2, 只转发不估价)  │
   (STEP/CAD,       └───────────────────────────┬───────────────────────────────┘
    图片, 语音)                                   │ UEA_LIVEKERNEL_URL
                                                 ▼
                    ┌───────────────────────────────────────────────────────────┐
                    │  livekernel  FastAPI 编排器  :8888  (对内；线上 UI=webui-dist)   │
                    │  ┌─────────────── intent router / skills dispatcher ─────┐  │
                    │  │  auto + fallback_rules, max 8 skills/task             │  │
                    │  └───────┬───────────────┬───────────────┬───────────────┘  │
                    │          ▼               ▼               ▼                 │
                    │   step-analysis/   material-expert/   supplier-match/      │
                    │   extract-specs    rag-ingest         freight-customs      │
                    └──────────┬───────────────┬─────────────────────┬──────────┘
                               │ LLM 提议       │ LLM 提议/检索        │ LLM 提议
                               ▼               ▼                     ▼
   ┌───────────────────────────────┐   ┌──────────────────┐   ┌──────────────────┐
   │ VISION/ASR/LLM  Omni-30B:8002 │   │ EMBED Embed-1B   │   │ Qwen3-0.6B :8902 │
   │ (Nemotron NVFP4, any-to-any)  │   │      :8011       │   │ (轻量辅助)        │
   └───────────────┬───────────────┘   └──────────────────┘   └──────────────────┘
                   │ 提议(不改价)
                   ▼
   ┌───────────────────────────────────────────────────────────────────────────┐
   │  DETERMINISTIC  Timo CNC 引擎 :7862   铁律① — 价格唯一权威, sha256 锁定      │
   │   calc_quote(定价) · ConflictChecker(DFM/冲突) · 毛利 · 状态机               │
   │   裁决: PASS / HITL / BLOCKED（不静默通过）                                 │
   └───────────────────────────────┬───────────────────────────────────────────┘
                                   ▼
                       草稿回复（auto_send=False，仅草稿，egress DENY）
```

## 前端与线上拓扑（如实）

- **线上对外 `:8051`**：React/Vite 编译工作台（`v7.1.0`），编译产物 = 本包 [`app/webui-dist/`](webui-dist/)（md5 核对一致），资源 base `/B/`、同源相对 `/v1/*` 访问后端。`:8051` 在**另一节点**（50 节点共用公网 IP），本机不监听 `:8051`。
- **本节点 `:8888`**：livekernel FastAPI 编排器（`api_server.py` 版本 `6.1.0-livekernel`），对内默认服务**遗留静态 Workbench**；编排/技能/确定性引擎在此真实运行。
- 二者是同一产品（Union Export Agent · livekernel）的**前端编译产物**与**后端**，本包分别如实纳入。

## 铁律与隔离

1. **LLM 不定价**：所有最终价格由 Timo 计算并 sha256 校验；LLM 仅意图/抽取/拟写。
2. **数据不出本机**：egress 全 DENY，HF 离线，邮件只草稿；SPARK 公网仅放行 Workbench 端口。
3. **人工在环**：HITL/BLOCKED 强制升级；能力边界外显式 MOCK 降级、绝不冒充在线。
4. **飞轮只提案**：价格修正产"系数提案"（COLD 5%/WARM 10%/HOT 15% 上限），不改 `final_price`，
   双层沙箱保证 A 的报价历史不被租户 B 召回。

## 编排入口与健康

- 主编排：`node_services.sh`（tmux，幂等，采用已在监听者）。子命令 `start|status|stop|restart`。
- 健康：`curl -s http://127.0.0.1:8888/health`（同时探活 livekernel 与确定性引擎）。
