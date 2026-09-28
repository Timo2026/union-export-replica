"""context_engine.py — L8 全链路唯一业务上下文 (Context Engine).

每个业务实例一个 context_id, 全链路共享。遵循 PRD 第 6 节 Context assembly policy:
只把"当前决策需要的信息"注入模型, 不无差别塞全文。

Context 承载: Customer / RFQ / Conversation / Documents / Geometry / Manufacturing /
Commercial / Retrieved Evidence / Risk / Decision / Human Actions / Events。
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Evidence:
    """Canonical evidence object (PRD 5.1)."""
    evidence_id: str
    source_type: str          # email|pdf|step|audio|video|crm|rag
    source_ref: str
    content: Any
    context_id: str
    timestamp: float = field(default_factory=time.time)
    confidence: float = 0.95
    claims: List[Dict[str, Any]] = field(default_factory=list)
    checksum: str = ""
    mock: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d["claims"] = list(self.claims)
        return d


class Context:
    def __init__(self, context_id: Optional[str] = None, prefix: str = "RFQ"):
        if context_id:
            self.context_id = context_id
        else:
            day = time.strftime("%Y%m%d")
            self.context_id = f"{prefix}-{day}-{uuid.uuid4().hex[:6].upper()}"
        self.customer: Dict[str, Any] = {}
        self.rfq: Dict[str, Any] = {}
        self.conversation_summary: str = ""
        self.documents: List[Dict[str, Any]] = []
        self.geometry: Dict[str, Any] = {}
        self.manufacturing: Dict[str, Any] = {}     # DFM 结果
        self.commercial: Dict[str, Any] = {}        # 报价/运费/毛利
        self.evidence: List[Evidence] = []
        self.risk: Dict[str, Any] = {}
        self.decision: Dict[str, Any] = {}
        self.human_actions: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []
        self.state: str = "NEW"
        # ===== v6.1 飞轮层新增 2 区 (T6.8) =====
        self.flywheel_state: Dict[str, Any] = {}
        # {
        #   customer_id, health_score, churn_risk, follow_ups_due,
        #   price_bias_pct, price_bias_confidence, preference_tags,
        #   tolerance_bias, price_sensitivity, last_outcome,
        #   _escalate_to_HITL, _escalate_reason
        # }
        self.sandbox_ref: str = ""
        # 指向 CustomerSandbox 标识 (customer_id)

    # ---------- evidence ----------
    def add_evidence(self, source_type: str, content: Any, source_ref: str = "",
                     confidence: float = 0.95, claims: Optional[List[Dict]] = None,
                     mock: bool = False) -> Evidence:
        ev = Evidence(
            evidence_id=f"EV-{uuid.uuid4().hex[:8].upper()}",
            source_type=source_type,
            source_ref=source_ref or f"mem://{self.context_id}/{source_type}/{len(self.evidence)}",
            content=content,
            context_id=self.context_id,
            confidence=confidence,
            claims=claims or [],
            checksum=_sha(json.dumps(content, ensure_ascii=False, default=str)),
            mock=mock,
        )
        self.evidence.append(ev)
        self.events.append({"ts": ev.timestamp, "event": "evidence_added",
                            "evidence_id": ev.evidence_id, "source_type": source_type, "mock": mock})
        return ev

    def evidence_of(self, source_type: str) -> List[Evidence]:
        return [e for e in self.evidence if e.source_type == source_type]

    # ---------- context compilation (PRD 6: 只注入当前决策所需) ----------
    def compile_for(self, task: str) -> Dict[str, Any]:
        """按任务裁剪上下文, 而非全量拼接。"""
        base = {
            "context_id": self.context_id,
            "state": self.state,
            "task": task,
            "rfq": self.rfq,
            "conversation_summary": self.conversation_summary,
        }
        if task in ("dfm", "quote", "manufacturing"):
            base["geometry"] = self.geometry
            base["manufacturing"] = self.manufacturing
            base["evidence"] = [e.to_dict() for e in self.evidence
                                if e.source_type in ("step", "pdf", "email", "audio")]
        if task in ("verify", "commercial"):
            base["commercial"] = self.commercial
            base["risk"] = self.risk
            base["evidence"] = [e.to_dict() for e in self.evidence]
        if task in ("reply", "crm"):
            base["decision"] = self.decision
            base["commercial"] = self.commercial
        return base

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context_id": self.context_id, "state": self.state,
            "customer": self.customer, "rfq": self.rfq,
            "conversation_summary": self.conversation_summary,
            "documents": self.documents, "geometry": self.geometry,
            "manufacturing": self.manufacturing, "commercial": self.commercial,
            "evidence": [e.to_dict() for e in self.evidence],
            "risk": self.risk, "decision": self.decision,
            "human_actions": self.human_actions, "events": self.events,
            "flywheel_state": self.flywheel_state,
            "sandbox_ref": self.sandbox_ref,
        }

    def save(self, dirpath: str) -> str:
        p = Path(dirpath) / f"{self.context_id}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str),
                     encoding="utf-8")
        return str(p)


class ContextEngine:
    """管理多个 Context 实例 (Working memory)."""
    def __init__(self, store_dir: str = "data/contexts", prefix: str = "RFQ"):
        self.store_dir = store_dir
        self.prefix = prefix
        self._live: Dict[str, Context] = {}

    def create(self, context_id: Optional[str] = None) -> Context:
        ctx = Context(context_id=context_id, prefix=self.prefix)
        self._live[ctx.context_id] = ctx
        return ctx

    def get(self, context_id: str) -> Optional[Context]:
        return self._live.get(context_id)

    def persist(self, ctx: Context) -> str:
        return ctx.save(self.store_dir)
