"""observability.py — OTEL 风格可观测 (trace/span + metrics), 本地可运行.

对齐冻结 PRD 第 14 节: trace 关联
  context_id → agent_run → skill → tool_call → model request → retrieval → verification → human action。

实现: 每个 context 一条 trace (trace_id), 每个阶段一个 span (span_id + parent)。
导出: 缺省写 JSONL 到 data/traces/{context_id}.jsonl (W3C trace-context 风格字段);
      若配置 OTLP endpoint 则同时尝试上报 (失败显式降级, 不阻断业务)。
指标: 计数 tool 调用/错误/HITL 触发/检索, 累计时延。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


def _hex(n: int) -> str:
    return uuid.uuid4().hex[:n]


class Span:
    def __init__(self, tracer: "Tracer", name: str, parent: Optional["Span"] = None,
                 kind: str = "internal"):
        self.tracer = tracer
        self.name = name
        self.kind = kind
        self.span_id = _hex(16)
        self.parent_id = parent.span_id if parent else None
        self.trace_id = tracer.trace_id
        self.start = time.time()
        self.end: Optional[float] = None
        self.attrs: Dict[str, Any] = {}
        self.status = "UNSET"
        self.events: List[Dict[str, Any]] = []

    def set(self, **kw):
        self.attrs.update(kw)
        return self

    def event(self, name: str, **kw):
        self.events.append({"ts": round(time.time(), 6), "name": name, **kw})
        return self

    def __enter__(self):
        self.tracer._push(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.end = time.time()
        self.status = "ERROR" if exc_type else "OK"
        if exc:
            self.attrs["error"] = repr(exc)
        self.tracer._pop(self)
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id, "span_id": self.span_id, "parent_id": self.parent_id,
            "name": self.name, "kind": self.kind,
            "start_time": round(self.start, 6),
            "end_time": round(self.end, 6) if self.end else None,
            "duration_ms": round((self.end - self.start) * 1000, 2) if self.end else None,
            "status": self.status, "attributes": self.attrs, "events": self.events,
        }


class Tracer:
    def __init__(self, context_id: str, service: str = "union-export-agent",
                 export_dir: Optional[str] = "data/traces", otlp_endpoint: Optional[str] = None):
        self.context_id = context_id
        self.service = service
        self.trace_id = _hex(32)
        self.spans: List[Span] = []
        self._stack: List[Span] = []
        self.export_dir = export_dir
        self.otlp_endpoint = otlp_endpoint
        self.metrics: Dict[str, Any] = {"tool_calls": 0, "tool_errors": 0, "hitl_triggers": 0,
                                        "retrievals": 0, "model_calls": 0}

    @property
    def current(self) -> Optional[Span]:
        return self._stack[-1] if self._stack else None

    def start_span(self, name: str, kind: str = "internal", **attrs) -> Span:
        sp = Span(self, name, parent=self.current, kind=kind)
        sp.set(**attrs)
        self.spans.append(sp)
        return sp

    def _push(self, sp: Span):
        if sp not in self.spans:
            self.spans.append(sp)
        self._stack.append(sp)

    def _pop(self, sp: Span):
        if self._stack and self._stack[-1] is sp:
            self._stack.pop()

    def bump(self, key: str, n: int = 1):
        self.metrics[key] = self.metrics.get(key, 0) + n

    def export(self) -> Dict[str, Any]:
        doc = {"trace_id": self.trace_id, "context_id": self.context_id,
               "service": self.service, "metrics": self.metrics,
               "spans": [s.to_dict() for s in self.spans]}
        if self.export_dir:
            p = Path(self.export_dir) / f"{self.context_id}.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8") as fh:
                for s in self.spans:
                    fh.write(json.dumps(s.to_dict(), ensure_ascii=False) + "\n")
            doc["export_path"] = str(p)
        if self.otlp_endpoint:
            doc["otlp"] = self._push_otlp(doc)
        return doc

    def _push_otlp(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import urllib.request
            data = json.dumps({"resourceSpans": [{
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": self.service}}]},
                "scopeSpans": [{"spans": doc["spans"]}]}]}).encode("utf-8")
            req = urllib.request.Request(self.otlp_endpoint, data=data,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                return {"exported": r.status == 200, "endpoint": self.otlp_endpoint}
        except Exception as e:  # noqa
            return {"exported": False, "endpoint": self.otlp_endpoint,
                    "degraded": f"OTLP push failed: {e!r}"}

    # 关联视图 (PRD 第14节的 trace 关联链)
    def correlation(self) -> List[str]:
        return [f"{s.name}[{s.status}]" for s in self.spans]
