---
name: submit-feedback
description: 把用户反馈（评分/评论/标签）写入 SQLite feedback_store，带速率限制与 IP 去重。v2.4.0 能力。当用户在 webui 反馈邮箱提交意见、或系统需要记录人工审批意见时调用。
version: 1
backend: services/feedback_store.py:submit
tool_contract:
  openai_function:
    name: submit_feedback
    description: 提交用户反馈到 SQLite
    parameters:
      type: object
      properties:
        payload:
          type: object
          description: 反馈内容（rating / comment / tags / context_id）
        ip:
          type: string
          description: 提交者 IP（用于速率限制，缺省 "unknown"）
      required: [payload]
---

# submit-feedback

## 何时用
用户在反馈邮箱 tab 提交；或 HITL 审批意见需要落盘留痕。

## 输入 / 输出
- 入：`payload`（rating 1-5 / comment / tags[] / context_id）+ 可选 `ip`
- 出：`{ok, id, stored_at, rate_limited}`

## 契约与失败策略
- 速率限制：同 IP 每窗口上限，超限 → `rate_limited: true`，仍返回 200（不抛异常）。
- `init_db()` 幂等，首次调用自动建表。
- 反馈与 `context_id` 关联，可被 postmortem 复盘召回。

## 示例
`{rating: 5, comment: "报价很快", context_id: "ctx_abc"}` → `ok: true, id: 42, stored_at: "2026-09-18T14:30Z"`。
