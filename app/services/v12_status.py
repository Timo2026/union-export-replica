"""v12_status.py — Timo_CNC-AI-Brain v12 内核实时状态聚合.

供 #tab-v12 webui 仪表板用. 数据源:
- adapters.timo_adapter.TimoAdapter: online / health / source_label
- data/traces/*.jsonl: 实时 span 聚合 (calc_quote 吞吐 + C1-C6 DFM + 审计 hash)

字段: kernel_online / version / calc_quote_total / p50 / p95 / dfm C1-C6 / sha256 链 /
recent_spans (近 10 个). 离线时 online=False, 但 span 聚合仍可跑.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

V12_VERSION = "v12.0.0-Fusion"
TRACES_DIR = Path("data/traces")
DFM_BUCKETS = ["C1", "C2", "C3", "C4", "C5", "C6"]


class V12Status:
    def __init__(self, timo=None, traces_dir: Optional[Path] = None):
        self.traces_dir = Path(traces_dir) if traces_dir else TRACES_DIR
        self._timo = timo

    def _ensure_timo(self):
        if self._timo is not None:
            return self._timo
        try:
            from adapters.timo_adapter import TimoAdapter
            from services.config import load_settings
            cfg = load_settings() or {}
            timo_cfg = cfg.get("timo", cfg)
            self._timo = TimoAdapter({"timo": timo_cfg})
        except Exception as e:
            log.warning("v12_status: TimoAdapter init failed: %r", e)
            self._timo = None
        return self._timo

    def status(self) -> Dict[str, Any]:
        timo = self._ensure_timo()
        online = False
        health_ok = False
        source = "unavailable"
        if timo is not None:
            try:
                online = bool(timo.health())
            except Exception:
                online = False
            health_ok = online
            try:
                # health 探测失败时不信 source_label() (它可能来自更早一次成功探测的缓存);
                # 内核可用性单独探测, 三态如实上报: live / byte-identical / absent(UNVERIFIED)。
                if online:
                    source = timo.source_label()
                elif getattr(timo, "kernel_available", False):
                    source = "offline:vendored-kernel(byte-identical)"
                else:
                    source = "offline:kernel-absent(UNVERIFIED)"
            except Exception:
                source = "offline:kernel-absent(UNVERIFIED)"

        agg = self._aggregate_traces()
        return {
            "version": V12_VERSION,
            "kernel_online": online,
            "kernel_health_ok": health_ok,
            "kernel_available": bool(timo is not None and timo.kernel_available),
            "source_label": source,
            "calc_quote_total": agg["calc_quote_total"],
            "calc_quote_p50_ms": agg["calc_quote_p50_ms"],
            "calc_quote_p95_ms": agg["calc_quote_p95_ms"],
            "dfm_c1_c6_counts": agg["dfm_c1_c6_counts"],
            "dfm_conflicts_total": agg["dfm_conflicts_total"],
            "span_count": agg["span_count"],
            "trace_count": agg["trace_count"],
            "recent_spans": agg["recent_spans"][:10],
        }

    def audit(self, limit: int = 10) -> Dict[str, Any]:
        if not self.traces_dir.exists():
            return {"version": V12_VERSION, "hashes": [], "count": 0}
        hashes: List[Dict[str, Any]] = []
        for jf in sorted(self.traces_dir.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                lines = jf.read_text(encoding="utf-8", errors="ignore").splitlines()
                if not lines:
                    continue
                rec = json.loads(lines[0])
                tid = str(rec.get("trace_id", ""))
                if len(tid) >= 16:
                    hashes.append({
                        "trace_id": tid,
                        "context_id": rec.get("context_id", jf.stem),
                        "start_time": rec.get("start_time"),
                        "sha256_16": tid[:16],
                    })
                if len(hashes) >= limit:
                    break
            except Exception:
                continue
        return {"version": V12_VERSION, "hashes": hashes, "count": len(hashes)}

    def dfm(self) -> Dict[str, Any]:
        agg = self._aggregate_traces()
        return {
            "version": V12_VERSION,
            "dfm_c1_c6_counts": agg["dfm_c1_c6_counts"],
            "dfm_conflicts_total": agg["dfm_conflicts_total"],
            "span_count": agg["span_count"],
        }

    def _aggregate_traces(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "calc_quote_total": 0,
            "calc_quote_p50_ms": 0,
            "calc_quote_p95_ms": 0,
            "calc_quote_durations": [],
            "dfm_c1_c6_counts": {b: 0 for b in DFM_BUCKETS},
            "dfm_conflicts_total": 0,
            "span_count": 0,
            "trace_count": 0,
            "recent_spans": [],
        }
        if not self.traces_dir.exists():
            return out
        files = list(self.traces_dir.glob("*.jsonl"))
        out["trace_count"] = len(files)
        for jf in files:
            try:
                content_text = jf.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for raw in content_text.splitlines()[-300:]:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    span = json.loads(raw)
                except Exception:
                    continue
                out["span_count"] += 1
                name = str(span.get("name", ""))
                attrs = span.get("attributes", {}) or {}
                if "calc_quote" in name or "cnc-quote" in name:
                    out["calc_quote_total"] += 1
                    dur = span.get("duration_ms")
                    if isinstance(dur, (int, float)):
                        out["calc_quote_durations"].append(float(dur))
                if "conflict" in name or "dfm" in name:
                    out["dfm_conflicts_total"] += 1
                    rule = str(attrs.get("rule") or attrs.get("code") or attrs.get("category") or "")
                    for b in DFM_BUCKETS:
                        if b in rule:
                            out["dfm_c1_c6_counts"][b] += 1
                            break
                if len(out["recent_spans"]) < 50:
                    out["recent_spans"].append({
                        "trace_id": str(span.get("trace_id", ""))[:16],
                        "name": name,
                        "duration_ms": span.get("duration_ms"),
                        "status": span.get("status"),
                        "context_id": attrs.get("context_id", ""),
                    })
        ds = sorted(out["calc_quote_durations"])
        if ds:
            out["calc_quote_p50_ms"] = round(ds[len(ds) // 2], 2)
            out["calc_quote_p95_ms"] = round(
                ds[int(len(ds) * 0.95)] if len(ds) >= 20 else ds[-1], 2
            )
        else:
            out["calc_quote_p50_ms"] = 0
            out["calc_quote_p95_ms"] = 0
        out.pop("calc_quote_durations", None)
        return out


def get_status(traces_dir: Optional[Path] = None) -> Dict[str, Any]:
    return V12Status(traces_dir=traces_dir).status()