---
name: dfm-conflict
description: 检测材料×表面处理×公差的工艺硬冲突（如 304+阳极氧化、钛+镀锌、铝+镀锌）。当需要在报价前做工艺可行性裁决时调用。硬冲突→BLOCKED，警告→HITL。
version: 1
backend: adapters/timo_adapter.py:TimoAdapter.conflict_check  (在线 :7862 /api/conflict-check · 离线 import ConflictChecker)
tool_contract:
  openai_function:
    name: dfm_conflict
    description: DFM 工艺冲突检测
    parameters:
      type: object
      properties:
        material: {type: string}
        surface: {type: string}
      required: [material, surface]
---

# dfm-conflict

## 何时用
报价前的"辟"——材料/表面/热处理/公差的禁忌矩阵裁决。

## 输入 / 输出
- 入：material、surface（归一后）
- 出：`{valid, conflicts[], warnings[], total_issues, _source}`

## 契约与失败策略
- 冲突来自真实 `ConflictChecker._RULES`（在线=离线一致）。
- `valid=false`（error 级）→ 状态机 BLOCKED，给出替代方案草稿，不可人工直接放行（approve→409）。
- 仅 warning → HITL 人工确认。

## 示例
304+阳极氧化 → `valid=false, conflicts=["304不锈钢自然钝化，不进行阳极氧化"]`（S3 BLOCKED）。
