"""skill_pack_adapter.py — 外部 Module Skill → livekernel 执行桥.

铁律:
  - 禁止写 unit_price / final_price 权威字段
  - 外部引擎价格只进 payload.proposed_price
  - 离线/缺失依赖时 _mock=True, 黄金链不中断
  - catalog/quarantined 永不从此适配器热调度
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parent.parent
_REGISTRY = _ROOT / "config" / "skill_registry.yaml"
_CATALOG = _ROOT / "skill_catalog" / "index.json"

_PRICE_FIELDS = {"unit_price", "final_price", "total_price", "price"}


def load_registry() -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
        return yaml.safe_load(_REGISTRY.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def pack_skill_meta(skill_id: str) -> Optional[Dict[str, Any]]:
    reg = load_registry()
    packs = reg.get("packs") or {}
    for pack_id, pack in packs.items():
        for sk in (pack.get("skills") or []):
            if sk.get("id") == skill_id:
                out = dict(sk)
                out["pack_id"] = pack_id
                return out
    return None


def allowed_pack_skill_ids() -> set[str]:
    reg = load_registry()
    ids = set()
    for pack in (reg.get("packs") or {}).values():
        if not pack.get("enabled", True):
            continue
        for sk in pack.get("skills") or []:
            if sk.get("status") == "pack_enabled":
                ids.add(sk["id"])
    return ids


def _safe_payload(raw: Any) -> Dict[str, Any]:
    """剥离价格权威字段, 只保留 proposal 区."""
    if not isinstance(raw, dict):
        return {"text": str(raw)[:2000]}
    payload: Dict[str, Any] = {}
    proposed: Dict[str, Any] = {}
    for k, v in raw.items():
        if k in _PRICE_FIELDS:
            proposed[f"proposed_{k}"] = v
        elif k.startswith("_"):
            continue
        else:
            payload[k] = v
    if proposed:
        payload["proposed_prices"] = proposed
        payload["cannot_override_price"] = True
    return payload


def run(ctx: Any = None, skill_id: str = "", **args) -> Dict[str, Any]:
    """统一 pack skill 入口."""
    if skill_id not in allowed_pack_skill_ids():
        return {
            "ok": False,
            "skill_id": skill_id,
            "role": "denied",
            "error": "skill not pack_enabled in skill_registry.yaml",
            "_source": f"skill_pack:{skill_id}",
            "_mock": True,
            "cannot_override_price": True,
            "ts": time.time(),
        }
    meta = pack_skill_meta(skill_id) or {}
    source = Path(str(meta.get("source") or ""))
    mock = True
    payload: Dict[str, Any] = {"args_keys": sorted(list(args.keys()))[:20]}
    note = "offline stub"

    if source.exists():
        # 只读取 SKILL.md 摘要作为证据; 不 import 未审计外部执行体
        sk = source / "SKILL.md"
        if sk.exists():
            text = sk.read_text(encoding="utf-8", errors="replace")
            payload["skill_md_head"] = text[:500]
            payload["source_path"] = str(source)
            note = "source present; external runtime not executed (P0 safety)"
        mock = True

    # 查询类: 可查本地 catalog
    if skill_id == "knowledge-index-lookup":
        return run_lookup(ctx, **args)

    return {
        "ok": True,
        "skill_id": skill_id,
        "pack_id": meta.get("pack_id", ""),
        "role": "proposal" if "quote" in skill_id else "evidence",
        "iron_rule": meta.get("iron_rule", "llm_proposal"),
        "payload": _safe_payload(payload),
        "notes": meta.get("notes", note),
        "_source": f"skill_pack:{skill_id}",
        "_mock": mock,
        "cannot_override_price": True,
        "ts": time.time(),
    }


def run_lookup(ctx: Any = None, query: str = "", **args) -> Dict[str, Any]:
    """知识目录检索: 只返回 catalog 命中, 不执行脚本."""
    q = (query or args.get("q") or args.get("intent") or "").strip().lower()
    hits = []
    if _CATALOG.exists() and q:
        try:
            data = json.loads(_CATALOG.read_text(encoding="utf-8"))
            for it in data.get("items") or []:
                if it.get("proposed_status") == "quarantined":
                    continue
                name = (it.get("id") or "").lower()
                if q in name or any(t in name for t in q.split()):
                    if it.get("proposed_status") in ("catalog_only", "pack_candidate", "core"):
                        hits.append({
                            "id": it["id"],
                            "status": it["proposed_status"],
                            "reason": it.get("reason", ""),
                            "path": it.get("path", ""),
                        })
                if len(hits) >= 10:
                    break
        except Exception as e:
            return {"ok": False, "skill_id": "knowledge-index-lookup",
                    "error": repr(e), "_mock": True, "role": "lookup",
                    "cannot_override_price": True}
    return {
        "ok": True,
        "skill_id": "knowledge-index-lookup",
        "role": "lookup",
        "payload": {"query": q, "hits": hits, "n": len(hits)},
        "_source": "skill_pack:knowledge-index-lookup",
        "_mock": not hits,
        "cannot_override_price": True,
        "ts": time.time(),
    }
