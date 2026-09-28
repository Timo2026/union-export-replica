"""reid-os skill tool — v5.0.0 Reid 决策操作系统 (简化版, 离线可跑).

完整版 (reid-operating-system 1.0.0) 在 skills_extracted, 含分诊台 + 协议执行 + 价值观校准.
本实现关键词分诊 + mock 协议模板.
"""
from __future__ import annotations

from typing import Any, Dict, List


# 工作域关键词
_WORK_KEYWORDS = [
    "工作", "客户", "订单", "报价", "项目", "合同", "工单",
    "任务", "同事", "老板", "业务", "流程", "交付", "验收",
]
# 家庭域关键词
_FAMILY_KEYWORDS = [
    "家庭", "孩子", "老人", "配偶", "父母", "生活", "健康",
    "情感", "关系", "陪伴", "家人", "亲戚", "婚姻", "感情",
]
# 拉闸检测
_DANGER_KEYWORDS = [
    "紧急", "危险", "不可逆", "投诉到总部", "撤资", "破产",
    "诉讼", "牢狱", "违法", "致命", "危及生命",
]
# 价值观正向
_VALUE_POSITIVE = ["利他", "共赢", "长期", "信任", "承诺", "诚信", "善意"]


def _triage_domain(request: str) -> str:
    """分诊: work / family / unknown."""
    work_count = sum(1 for kw in _WORK_KEYWORDS if kw in request)
    family_count = sum(1 for kw in _FAMILY_KEYWORDS if kw in request)
    if work_count > family_count and work_count > 0:
        return "work"
    if family_count > work_count and family_count > 0:
        return "family"
    if work_count > 0 and family_count > 0:
        return "work"  # 都命中 → 工作优先 (工业场景)
    return "unknown"


def _check_intervention(request: str) -> str:
    """检测拉闸关键词."""
    for kw in _DANGER_KEYWORDS:
        if kw in request:
            return f"warning: 关键词 '{kw}' 触发拉闸, 建议人工介入"
    return ""


def _check_values(request: str) -> bool:
    """价值观校准: 至少 1 个正向关键词 → aligned."""
    return any(kw in request for kw in _VALUE_POSITIVE)


def _execute_protocol(domain: str, request: str) -> str:
    """协议执行: mock 模板返 action 描述."""
    if domain == "work":
        if "投诉" in request:
            return "走 COPC 协议 (Customer Opinion Protocol & Care): 记录 → 道歉 → 根因分析 → 补偿 → 闭环"
        if "报价" in request or "价格" in request:
            return "走 RCF 协议 (Request for Quote): 拆需求 → 选材料 → 算成本 → 报价 → 跟进"
        return "走 RWP 协议 (Request for Work Process): 任务分解 → 派工 → 执行 → 验收"
    elif domain == "family":
        if "健康" in request:
            return "走 FMH 协议 (Family Member Health): 评估紧急度 → 挂号/急诊 → 陪伴 → 后续"
        return "走 FRT 协议 (Family Relationship Triage): 倾听 → 共情 → 协商 → 共识"
    return "走 GEN 协议 (General): 待人工分流"


def run(ctx, request: str = "", **kwargs) -> Dict[str, Any]:
    """Reid 决策: 分诊 → 协议 → 价值观校准 → 拉闸检测."""
    if not request:
        return {"ok": False, "skill": "reid-os", "iron_rule": "llm_proposal",
                "error": "request required"}

    domain = _triage_domain(request)
    intervention = _check_intervention(request)
    values_aligned = _check_values(request)
    action = _execute_protocol(domain, request)
    reason = (
        f"分诊: {domain} 域; " +
        f"价值观校准: {'✓ 对齐' if values_aligned else '✗ 未对齐 (含利己/短期关键词)'}; " +
        (f"拉闸: {intervention}" if intervention else "无拉闸风险")
    )

    # LLM 在线扩展: 可让 planner 润色 reason
    try:
        ctrl = ctx.get_ctrl() if hasattr(ctx, "get_ctrl") else None
        if ctrl is not None and getattr(ctrl, "planner", None) is not None and ctrl.planner.online():
            pass  # 未来扩展
    except Exception:
        pass

    return {
        "ok": True,
        "skill": "reid-os",
        "iron_rule": "llm_proposal",
        "domain": domain,
        "action": action,
        "reason": reason,
        "values_aligned": values_aligned,
        "intervention": intervention or None,
        "source": "mock",  # 离线 mock; 未来 LLM 在线改 "llm"
    }
