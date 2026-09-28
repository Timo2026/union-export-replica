"""state_machine.py — v2.3.0 供应商流水线子状态机。

状态：
  PENDING → DESENSITIZED → MATCHED → QUOTED → SELECTED → PO_SENT → CONFIRMED
分支：任意 → FAILED（终态）

契约：
  - 非法转移抛 IllegalTransitionError
  - 持久化为 JSON（data/supplier_pipelines/{context_id}.json）
  - 历史 transitions 列表保留审计
"""
from __future__ import annotations

import enum
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


class State(enum.Enum):
    PENDING = "PENDING"
    DESENSITIZED = "DESENSITIZED"
    MATCHED = "MATCHED"
    QUOTED = "QUOTED"
    SELECTED = "SELECTED"
    PO_SENT = "PO_SENT"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


# 合法转移表（白名单）
_LEGAL: Dict[State, List[State]] = {
    State.PENDING:      [State.DESENSITIZED, State.FAILED],
    State.DESENSITIZED: [State.MATCHED, State.FAILED],
    State.MATCHED:      [State.QUOTED, State.FAILED],
    State.QUOTED:       [State.SELECTED, State.FAILED],
    State.SELECTED:     [State.PO_SENT, State.FAILED],
    State.PO_SENT:      [State.CONFIRMED, State.FAILED],
    State.CONFIRMED:    [],
    State.FAILED:       [],
}

# 允许"任意 → FAILED"，动态加进去
for _src in State:
    if State.FAILED not in _LEGAL[_src] and _src not in (State.FAILED, State.CONFIRMED):
        _LEGAL[_src].append(State.FAILED)


class IllegalTransitionError(Exception):
    """非法状态转移。"""


@dataclass
class SupplierPipeline:
    context_id: str
    state: State = State.PENDING
    payload: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: int = field(default_factory=lambda: int(time.time()))

    def transition(self, new_state: State) -> None:
        if new_state not in _LEGAL[self.state]:
            raise IllegalTransitionError(
                f"illegal transition: {self.state.name} → {new_state.name}"
            )
        self.history.append({
            "from": self.state.name,
            "to": new_state.name,
            "at": int(time.time()),
        })
        self.state = new_state


def save_pipeline(p: SupplierPipeline, path: Path) -> None:
    d = asdict(p)
    d["state"] = p.state.value
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def load_pipeline(path: Path) -> SupplierPipeline:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    d["state"] = State(d["state"])
    return SupplierPipeline(**d)