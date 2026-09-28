"""rfq_state_machine.py — Control Loop B: 业务状态机 (business state is authoritative).

对齐冻结 PRD 第 2/9 节:
  NEW → INTAKE → STRUCTURING → DFM → QUOTING → VERIFY → REPLY → CRM_MEM → DONE
  QUOTING/VERIFY → BLOCKED | HITL
  HITL → HUMAN_APPROVAL → REPLY | BLOCKED
  BLOCKED → ARCHIVED

只有 State Machine 能推进状态; Agent 不能绕过 policy 直接标记 DONE。
非法转移抛 IllegalTransition (被测试断言拦截)。
"""
from __future__ import annotations

from typing import Dict, List, Set


class IllegalTransition(Exception):
    pass


# 合法转移表
TRANSITIONS: Dict[str, Set[str]] = {
    "NEW":            {"INTAKE"},
    "INTAKE":         {"STRUCTURING", "BLOCKED"},
    "STRUCTURING":    {"DFM", "HITL", "BLOCKED"},      # 信息缺失/冲突 → HITL
    "DFM":            {"QUOTING", "BLOCKED", "HITL"},   # 硬冲突 → BLOCKED
    "QUOTING":        {"VERIFY", "BLOCKED", "HITL"},
    "VERIFY":         {"REPLY", "HITL", "BLOCKED"},
    "HITL":           {"HUMAN_APPROVAL", "BLOCKED"},
    "HUMAN_APPROVAL": {"REPLY", "BLOCKED"},
    "REPLY":          {"CRM_MEM", "DONE"},
    "CRM_MEM":        {"DONE"},
    "BLOCKED":        {"ARCHIVED", "HITL"},             # BLOCKED 可给人工解锁路径
    "DONE":           set(),
    "ARCHIVED":       set(),
}

TERMINAL = {"DONE", "ARCHIVED"}
ALL_STATES = set(TRANSITIONS.keys())


class RFQStateMachine:
    def __init__(self, context_id: str, initial: str = "NEW"):
        if initial not in ALL_STATES:
            raise ValueError(f"unknown state {initial}")
        self.context_id = context_id
        self.state = initial
        self.history: List[Dict] = [{"from": None, "to": initial, "reason": "init"}]

    def can(self, target: str) -> bool:
        return target in TRANSITIONS.get(self.state, set())

    def transition(self, target: str, reason: str = "", actor: str = "system") -> str:
        if target not in ALL_STATES:
            raise IllegalTransition(f"unknown target state: {target}")
        if not self.can(target):
            raise IllegalTransition(
                f"[{self.context_id}] illegal transition {self.state} -> {target} (reason={reason})")
        prev, self.state = self.state, target
        self.history.append({"from": prev, "to": target, "reason": reason, "actor": actor})
        return self.state

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL

    def allowed_next(self) -> Set[str]:
        return set(TRANSITIONS.get(self.state, set()))
