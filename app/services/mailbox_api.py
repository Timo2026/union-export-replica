"""mailbox_api.py — v3.0 #34 邮件台 7 区聚合 API.

实现 (凭代码核对，全部复用现有函数，不发明):
  GET  /v1/mail/inbox                      → 列出 data/mailbox/*.eml
  GET  /v1/mail/{mail_id}                  → 单信详情 (raw + parsed + 附件)
  GET  /v1/mail/{mail_id}/context/customer       → B-1 客户区
  GET  /v1/mail/{mail_id}/context/geometry       → B-2 图纸区
  GET  /v1/mail/{mail_id}/context/rag            → B-3 RAG 区
  GET  /v1/mail/{mail_id}/context/pending        → B-4 未办区
  GET  /v1/mail/{mail_id}/context/verification   → B-5 门禁区
  GET  /v1/mail/{mail_id}/context/postmortem     → B-6 复盘区
  GET  /v1/mail/{mail_id}/context/commercial     → B-7 落地成本区
  GET  /v1/mail/{mail_id}/context/trace          → B-8 Trace 区 (optional)

mail_id 格式: <sha256_16>_<timestamp> (来自 data/mailbox 文件名 stem)
或直接传文件名 stem.

数据来源全部走 controller.* 现有函数, 0 发明.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from services import file_intake as fi
from services import commercial as commercial_mod
from services.crm_memory import CRMMemory

_MAILBOX_DIR = Path("data/mailbox")
_DRAFTS_DIR = Path("data/drafts")
_CONTEXTS_DIR = Path("data/contexts")
_TRACES_DIR = Path("data/traces")


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _mailbox_path(mail_id: str) -> Path:
    """mail_id → data/mailbox/{mail_id}.eml (兼容 _<ts> 后缀)."""
    # 先直接匹配
    p = _MAILBOX_DIR / f"{mail_id}.eml"
    if p.exists():
        return p
    # 兼容 stem (去掉 .eml 后再传进来的情况)
    for cand in _MAILBOX_DIR.glob(f"{mail_id}*.eml"):
        return cand
    raise HTTPException(404, f"mail not found: {mail_id}")


def _parse_mail(mail_id: str) -> Dict[str, Any]:
    path = _mailbox_path(mail_id)
    parsed = fi.parse_email_file(str(path))
    parsed["mail_id"] = mail_id
    parsed["path"] = str(path)
    parsed["size_bytes"] = path.stat().st_size
    parsed["received_at"] = path.stat().st_mtime
    # 列出附件
    attachments = parsed.get("attachments") or []
    parsed["attachments_detail"] = []
    for name in attachments:
        if not name:
            continue
        ext = Path(name).suffix.lower()
        kind = fi.classify(name)
        parsed["attachments_detail"].append({
            "name": name, "ext": ext, "kind": kind,
            "preview_path": str(_MAILBOX_DIR / f"{mail_id}_att_{name}") if False else None,
        })
    return parsed


def _context_id_for(mail_id: str) -> Optional[str]:
    """从 mail_id 反查 context_id (优先用 metadata, 否则按主体 hash 匹配)."""
    meta = _MAILBOX_DIR / f"{mail_id}.meta.json"
    if meta.exists():
        try:
            return json.loads(meta.read_text(encoding="utf-8")).get("context_id")
        except Exception:
            pass
    return None


# ---------------- 路由注册 ----------------
router = APIRouter()


@router.get("/v1/mail/inbox")
def mail_inbox(limit: int = 50) -> Dict[str, Any]:
    """列出本地 mailbox 中所有 .eml (按 mtime DESC).

    P0 标记 (方案 D): 每项附带 pending ledger 摘要 (state + driver + attempts),
    控制台据此渲染"Agent 处理 / 邮件驱动 / 待人工"徽标; 不在 ledger 的邮件
    (mock 上传 / 历史预置) pending=None.
    """
    _MAILBOX_DIR.mkdir(parents=True, exist_ok=True)
    from services.mail_puller import MailPuller
    try:
        pending_index = MailPuller(root=Path(".")).pending_index()
    except Exception:
        pending_index = {}
    items: List[Dict[str, Any]] = []
    for p in sorted(_MAILBOX_DIR.glob("*.eml"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        stem = p.stem
        parsed = fi.parse_email_file(str(p))
        meta_path = _MAILBOX_DIR / f"{stem}.meta.json"
        badges = []
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                badges = meta.get("badges", [])
            except Exception:
                pass
        items.append({
            "mail_id": stem,
            "from": parsed.get("from", ""),
            "subject": parsed.get("subject", ""),
            "received_at": p.stat().st_mtime,
            "size_bytes": p.stat().st_size,
            "badges": badges,
            "pending": pending_index.get(stem),
            "attachments_count": len(parsed.get("attachments") or []),
        })
    return {"items": items, "count": len(items), "source": "local"}


@router.get("/v1/mail/{mail_id}/context/customer")
def mail_context_customer(mail_id: str) -> Dict[str, Any]:
    """B-1 客户区: from 字段 → crm.customer_id_by_name → list_customer_history."""
    from bootstrap import build_controller
    c = build_controller()
    parsed = _parse_mail(mail_id)
    sender = parsed.get("from", "") or ""
    # 抽取邮箱 local part 作为客户名兜底
    name = sender.split("<")[0].strip() or sender
    cid = c.crm.customer_id_by_name(name) if name else None
    if not cid:
        return {"name": name, "customer_id": None, "is_new": True,
                "signals": [], "history": {"quotes": [], "postmortems": [], "n": 0}}
    hist = c.crm.list_customer_history(cid)
    # signals 由 postmortem.recall_customer_memory 给 (从 history 推导简化版)
    signals = []
    if hist.get("quotes"):
        signals.append({"type": "repeat_customer", "severity": "info",
                        "detail": f"历史 {len(hist['quotes'])} 条报价"})
        margins = [q.get("margin_pct") for q in hist["quotes"] if q.get("margin_pct") is not None]
        if margins:
            avg_m = round(sum(margins) / len(margins), 1)
            signals.append({"type": "historical_margin", "severity": "info",
                            "detail": f"历史平均毛利 {avg_m}%"})
    lost = [p for p in hist.get("postmortems", []) if p.get("outcome") == "lost"]
    if lost:
        signals.append({"type": "past_loss", "severity": "warning",
                        "detail": f"{len(lost)} 次丢单"})
    return {"name": name, "customer_id": cid, "is_new": False,
            "signals": signals, "history": hist}


@router.get("/v1/mail/{mail_id}/context/geometry")
def mail_context_geometry(mail_id: str) -> Dict[str, Any]:
    """B-2 图纸区: 附件 .step → parse_step (bbox/volume/weight/features)."""
    from bootstrap import build_controller
    c = build_controller()
    parsed = _parse_mail(mail_id)
    for att in parsed.get("attachments_detail", []):
        if att["kind"] == "step":
            # 附件路径推断: data/artifacts/step/<ts>_<hash>_<safe>
            # demo 文件直接落在 mailbox 旁
            cand = _MAILBOX_DIR / f"{mail_id}_att_{att['name']}"
            if cand.exists():
                try:
                    geo = c.timo.step_geometry(str(cand), material="6061")
                    return {"thumb_url": None,
                            "bbox": geo.get("bbox"),
                            "volume_cm3": geo.get("volume_cm3"),
                            "weight_kg": geo.get("weight_kg"),
                            "features": geo.get("features", {}),
                            "source": geo.get("_source"),
                            "ok": not geo.get("error")}
                except Exception as e:
                    return {"ok": False, "error": repr(e)}
    return {"ok": False, "reason": "no STEP attachment",
            "thumb_url": None, "bbox": None, "volume_cm3": None, "weight_kg": None,
            "features": {}, "source": None}


@router.get("/v1/mail/{mail_id}/context/rag")
def mail_context_rag(mail_id: str, top_k: int = 4) -> Dict[str, Any]:
    """B-3 RAG 区: subject+body → rag.search."""
    from bootstrap import build_controller
    c = build_controller()
    parsed = _parse_mail(mail_id)
    query = (parsed.get("subject", "") + " " + (parsed.get("body", "") or "")[:500]).strip()
    if not query:
        return {"query": "", "hits": [], "mock": True}
    res = c.rag.search(query, limit=top_k)
    return {"query": query[:200], "hits": res.get("hits", []),
            "mock": res.get("_mock", True),
            "source": res.get("_source")}


@router.get("/v1/mail/{mail_id}/context/pending")
def mail_context_pending(mail_id: str, limit: int = 20) -> Dict[str, Any]:
    """B-4 未办区: crm.pending_for (按 mail 关联客户过滤, 若能解析)."""
    from bootstrap import build_controller
    c = build_controller()
    parsed = _parse_mail(mail_id)
    sender = parsed.get("from", "") or ""
    name = sender.split("<")[0].strip() or sender
    cid = c.crm.customer_id_by_name(name) if name else None
    tasks = c.crm.pending_for(customer_id=cid, limit=limit)
    return {"customer_id": cid, "tasks": tasks, "count": len(tasks)}


@router.get("/v1/mail/{mail_id}/context/verification")
def mail_context_verification(mail_id: str) -> Dict[str, Any]:
    """B-5 门禁区: verification.run (status + reasons + conflicts)."""
    from bootstrap import build_controller
    c = build_controller()
    cid = _context_id_for(mail_id)
    if not cid:
        return {"status": "UNKNOWN", "reasons": [], "conflicts": [],
                "risk_score": 0.0, "gate_history": [],
                "note": "no context_id bound; 运行 quote+verify 后重试"}
    ctx_path = _CONTEXTS_DIR / f"{cid}.json"
    if not ctx_path.exists():
        return {"status": "UNKNOWN", "reasons": [], "conflicts": [],
                "risk_score": 0.0, "gate_history": [],
                "note": f"context file missing: {cid}"}
    ctx_dict = json.loads(ctx_path.read_text(encoding="utf-8"))
    res = c.verify.run(ctx_dict)
    return {
        "status": res.get("status", "UNKNOWN"),
        "reasons": res.get("reasons", []),
        "conflicts": res.get("conflicts", []),
        "risk_score": res.get("risk_score", 0.0),
        "gate_history": res.get("gate_history", []),
        "checks": res.get("checks", []),
    }


@router.get("/v1/mail/{mail_id}/context/postmortem")
def mail_context_postmortem(mail_id: str) -> Dict[str, Any]:
    """B-6 复盘区: crm.postmortems 表聚合 + 知识回流."""
    from bootstrap import build_controller
    c = build_controller()
    parsed = _parse_mail(mail_id)
    sender = parsed.get("from", "") or ""
    name = sender.split("<")[0].strip() or sender
    cid = c.crm.customer_id_by_name(name) if name else None
    # 全局 postmortems (limit 20), 按 cid 聚合
    pms_rows = c.crm._conn.execute(
        "SELECT context_id,outcome,actual_cost,note,created_at FROM postmortems "
        "ORDER BY created_at DESC LIMIT ?", (20,)
    ).fetchall()
    cols = ["context_id", "outcome", "actual_cost", "note", "created_at"]
    pms = [dict(zip(cols, r)) for r in pms_rows]
    won = sum(1 for p in pms if p.get("outcome") == "won")
    lost = sum(1 for p in pms if p.get("outcome") == "lost")
    cost_dev = [p for p in pms if p.get("actual_cost") is not None]
    lead_over = [p for p in pms if (p.get("note") or "").find("超") >= 0]
    return {
        "customer_id": cid, "won_count": won, "lost_count": lost,
        "past_cost_deviations": cost_dev[:5],
        "past_leadtime_overruns": lead_over[:5],
        "knowledge_updates": [],
        "total": len(pms),
    }


@router.get("/v1/mail/{mail_id}/context/commercial")
def mail_context_commercial(mail_id: str) -> Dict[str, Any]:
    """B-7 落地成本区: commercial.compute_commercial."""
    from bootstrap import build_controller
    c = build_controller()
    cid = _context_id_for(mail_id)
    if not cid:
        return {"ok": False, "reason": "no context_id bound; 运行 quote 后重试",
                "unit_price": None, "total_price": None, "margin_pct": None,
                "freight_cny": None, "duty_cny": None, "landed_cost": None,
                "incoterms": None}
    ctx_path = _CONTEXTS_DIR / f"{cid}.json"
    if not ctx_path.exists():
        return {"ok": False, "reason": f"context file missing: {cid}"}
    ctx_dict = json.loads(ctx_path.read_text(encoding="utf-8"))
    rfq = ctx_dict.get("rfq", {})
    com = ctx_dict.get("commercial", {})
    quote = com.get("quote", com)
    if not quote:
        return {"ok": False, "reason": "no quote in context"}
    try:
        landed = commercial_mod.compute_commercial(
            quote=quote, rfq=rfq, cfg=c.commercial_cfg,
            destination_country=rfq.get("destination_country"),
            shipping_mode=rfq.get("shipping_mode"),
            incoterm=rfq.get("incoterm"),
            hs_code=rfq.get("hs_code"),
        )
        landed["ok"] = True
        return landed
    except Exception as e:
        return {"ok": False, "error": repr(e)}


@router.get("/v1/mail/{mail_id}/context/trace")
def mail_context_trace(mail_id: str) -> Dict[str, Any]:
    """B-8 Trace 区: data/traces/*.jsonl (observability.Tracer 输出)."""
    # 简单扫 traces 目录, 不绑定到具体 cid
    _TRACES_DIR.mkdir(parents=True, exist_ok=True)
    events = []
    for jf in sorted(_TRACES_DIR.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True)[:3]:
        try:
            for line in jf.read_text(encoding="utf-8", errors="ignore").splitlines()[-50:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
        except Exception:
            continue
    return {"events": events[-50:], "count": len(events[-50:])}


# ---- 必须放最后: {mail_id} 会贪婪吃掉 /context/* 子路径 ----
@router.get("/v1/mail/{mail_id}")
def mail_detail(mail_id: str) -> Dict[str, Any]:
    """邮件详情: 仅当所有 /context/* 都不匹配时才落到这里."""
    return _parse_mail(mail_id)


# ---------------- v3.0 HITL 审批面板数据 ----------------
def _write_draft(cid: str, draft: Dict[str, Any]) -> Path:
    """写草稿到 data/drafts/{cid}.json (原子覆盖)."""
    _DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    p = _DRAFTS_DIR / f"{cid}.json"
    p.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


@router.get("/v1/mail/{mail_id}/context/hitl")
def mail_context_hitl(mail_id: str) -> Dict[str, Any]:
    """B-9 HITL 面板: 草稿全文 + 报价 sha256 锁 + 是否可批准.

    iron-rule-1 可视化: quote_sha256_locked = 草稿生成时的报价 hash;
    若实际 context 报价被篡改, locked=false, UI 显示红字拦截.
    """
    cid = _context_id_for(mail_id)
    if not cid:
        return {"ok": False, "reason": "no context_id", "can_approve": False,
                "draft": None, "quote": None, "quote_sha16": None,
                "quote_sha16_locked": None, "locked": False,
                "verification_status": "UNKNOWN"}
    from services.reply import build_reply
    from bootstrap import build_controller
    c = build_controller()
    ctx_path = _CONTEXTS_DIR / f"{cid}.json"
    if not ctx_path.exists():
        return {"ok": False, "reason": f"context file missing: {cid}",
                "can_approve": False, "draft": None, "quote": None,
                "quote_sha16": None, "quote_sha16_locked": None, "locked": False,
                "verification_status": "UNKNOWN"}
    ctx_dict = json.loads(ctx_path.read_text(encoding="utf-8"))
    verification = c.verify.run(ctx_dict)
    draft = build_reply(ctx_dict, verification)
    # 锁住 sha16 = 草稿生成时报价的数字指纹
    quote = (ctx_dict.get("commercial", {}) or {}).get("quote", {}) or {}
    current_hash = _sha16(json.dumps({
        "unit_price": quote.get("unit_price"),
        "final_price": quote.get("final_price"),
        "currency": quote.get("currency"),
        "lead_time_days": quote.get("lead_time_days"),
    }, ensure_ascii=False, sort_keys=True))
    # iron-rule-1 持久锁定: 先查已有 draft 中的锁; 没有则用 current_hash 初始化
    existing_locked = None
    draft_path = _DRAFTS_DIR / f"{cid}.json"
    if draft_path.exists():
        try:
            existing_locked = json.loads(draft_path.read_text(encoding="utf-8")).get("quote_sha16_locked")
        except Exception:
            pass
    if existing_locked:
        locked_hash = existing_locked
    else:
        locked_hash = current_hash  # 首次锁定 = 当前 hash
    locked = locked_hash == current_hash
    # 只有 HITL 状态 + 锁未破 才允许"批准"
    can_approve = (verification.get("status") == "HITL") and locked
    out_draft = dict(draft)
    out_draft["quote_sha16_locked"] = locked_hash
    _write_draft(cid, out_draft)
    return {
        "ok": True,
        "context_id": cid,
        "mail_id": mail_id,
        "draft": out_draft,
        "quote": quote,
        "quote_sha16": current_hash,
        "quote_sha16_locked": locked_hash,
        "locked": locked,
        "can_approve": can_approve,
        "verification_status": verification.get("status"),
        "reasons": verification.get("reasons", []),
    }
