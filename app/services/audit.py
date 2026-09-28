"""audit.py — SHA-256 链式审计 (tamper-evident).

对齐冻结 PRD 第 11 节: 链式事件日志只保证"记录不可篡改", 不证明决策正确。
每个事件哈希 = sha256(prev_hash + canonical_json(event))。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


class AuditChain:
    GENESIS = "0" * 64

    def __init__(self, context_id: str, path: Optional[str] = None):
        self.context_id = context_id
        self.events: List[Dict[str, Any]] = []
        self.prev_hash = self.GENESIS
        self.path = Path(path) if path else None

    def log(self, event_type: str, payload: Dict[str, Any], actor: str = "system") -> Dict[str, Any]:
        ev = {
            "seq": len(self.events),
            "ts": round(time.time(), 3),
            "context_id": self.context_id,
            "actor": actor,
            "event": event_type,
            "payload": payload,
            "prev_hash": self.prev_hash,
        }
        h = hashlib.sha256((self.prev_hash + _canon(ev)).encode("utf-8")).hexdigest()
        ev["hash"] = h
        self.prev_hash = h
        self.events.append(ev)
        return ev

    def verify(self) -> bool:
        prev = self.GENESIS
        for ev in self.events:
            rec = {k: v for k, v in ev.items() if k != "hash"}
            if rec.get("prev_hash") != prev:
                return False
            calc = hashlib.sha256((prev + _canon(rec)).encode("utf-8")).hexdigest()
            if calc != ev.get("hash"):
                return False
            prev = ev["hash"]
        return True

    def save(self) -> str:
        if not self.path:
            return ""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(_canon({"context_id": self.context_id,
                                     "valid": self.verify(), "events": self.events}),
                             encoding="utf-8")
        return str(self.path)

    @property
    def head(self) -> str:
        return self.prev_hash
