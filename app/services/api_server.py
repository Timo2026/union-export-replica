"""api_server.py — 全模态数据上传端口 + PRD §13 API 契约 (L9/L10).

"补上所有数据都设置功能上传端口功能模块":
  每种数据都有独立上传端口, 且有一个统一 intake 端口一次收全模态并跑黄金链。

上传端口 (multipart/form-data, 字段名=file):
  POST /v1/upload/email    .eml/.msg/.txt   → stdlib email 解析
  POST /v1/upload/step     .step/.stp       → 真实 OCP 几何 (bbox/体积/重量) + C1 特征
  POST /v1/upload/audio    .wav/.mp3/...    → funasr ASR 转写 (离线显式 MOCK)
  POST /v1/upload/pdf      .pdf             → pypdf 文本 (缺库显式 skipped)
  POST /v1/upload/excel    .xlsx/.csv       → openpyxl/csv 行 (缺库显式 skipped)
  POST /v1/upload/image    .png/.jpg        → VLM 感知接口 (未接线显式 MOCK)
  POST /v1/upload/auto     任意             → 按扩展名自动路由

业务契约 (PRD §13):
  POST /v1/rfq/intake            多文件一次收全 (email/audio/step/pdf/excel + 客户字段) → 跑黄金链
  GET  /v1/rfq/{cid}             读取已存 context 结果
  POST /v1/rfq/{cid}/analyze     RFQ + DFM + missing
  POST /v1/rfq/{cid}/quote       确定性报价
  POST /v1/rfq/{cid}/verify      辟牟援推止 → PASS/HITL/BLOCKED
  POST /v1/rfq/{cid}/approve     人工授权 (HITL → HUMAN_APPROVAL → REPLY), 落审计
  POST /v1/rfq/{cid}/reply-draft 英文回复草稿
  POST /v1/rfq/{cid}/crm-sync    写业务事实 + 记忆引用
  GET  /health
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bootstrap import build_controller           # noqa: E402
from services import file_intake as fi           # noqa: E402
from services import security as sec             # noqa: E402

# LINK-3 (E1 #34): 邮件无人值守后台 — puller(IMAP 拉信→pending) + orchestrator(pending→黄金链).
# 门禁双层: env UEA_MAIL_AUTOSTART=0 可整体关闭 (pytest conftest 默认置 0);
# 即便开启, puller.is_enabled() 仍要求 gmail_settings.enabled=true + 凭据存在, 否则 noop。
_mail_bg: Dict[str, Any] = {}


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    if os.environ.get("UEA_MAIL_AUTOSTART", "1") != "0":
        try:
            from services.mail_orchestrator import MailOrchestrator
            from services.mail_puller import MailPuller
            puller = MailPuller(root=_ROOT)
            _mail_bg["puller"] = puller
            if puller.is_enabled():
                orch = MailOrchestrator(root=_ROOT, puller=puller,
                                        cat=build_controller(root=_ROOT))
                _mail_bg["orchestrator"] = orch
                puller.start()
                orch.start_loop()
                logging.getLogger("api_server").info(
                    "[lifespan] mail autostart: puller+orchestrator running")
        except Exception:
            logging.getLogger("api_server").exception(
                "[lifespan] mail autostart failed (服务继续可用)")
    yield
    for key in ("orchestrator", "puller"):
        obj = _mail_bg.pop(key, None)
        if obj is not None:
            try:
                obj.stop()
            except Exception:
                logging.getLogger("api_server").exception(
                    "[lifespan] stop %s failed", key)


app = FastAPI(title="Union Manufacturing Export Agent — Upload & RFQ API",
              version="6.1.0-livekernel",
              lifespan=_lifespan)

# v6.1.0 B1 修复: 挂载 v6 融合 UI 的静态资源 (css/js), 否则 /css/workbench.css 404
for _sub in ("css", "js"):
    _dir = _ROOT / _sub
    if _dir.is_dir():
        app.mount(f"/{_sub}", StaticFiles(directory=str(_dir)), name=_sub)

# v3.0 #34: 邮件台 7 区聚合 API
from services.mailbox_api import router as mailbox_router
app.include_router(mailbox_router)
# v3.0 Gmail IMAP (App Password, 默认禁用)
from services.gmail_api import router as gmail_router
app.include_router(gmail_router)
# v3.0 V12 内核仪表板
from services.v12_api import router as v12_router
app.include_router(v12_router)
# E1 #34: 飞轮客户沙箱统计 API (此前从未挂载, AUDIT-v7 F2)
from services.flywheel_api import router as flywheel_router
app.include_router(flywheel_router)


@app.get("/v1/mail/puller/status")
def mail_puller_status():
    """LINK-3 可观测: 后台邮件链路是否运行 + pending 概览 (诚实报告, 不冒充)."""
    running_puller = _mail_bg.get("puller")
    return {
        "autostart_enabled": os.environ.get("UEA_MAIL_AUTOSTART", "1") != "0",
        "running": running_puller is not None and bool(_mail_bg.get("orchestrator")),
        "puller": running_puller.status() if running_puller is not None else None,
    }


# E-03 (E1 #34): config_reload 生产接线 — 热载单例挂载 + /reload 触发 (校验回滚)
@app.post("/v1/config/reload")
def config_reload():
    """强制重读 settings/skills 热载配置。坏配置 → 保留上一份有效 + 如实上报。"""
    from services import config_reload as cr
    cr.hot_settings()   # 确保两个单例已注册 (reload_all 只遍历已存在的)
    cr.hot_skills()
    raw = cr.reload_all()
    configs = {k.split(":", 1)[0]: v for k, v in raw.items()}
    return {"ok": all(v["ok"] for v in configs.values()), "configs": configs}


@app.get("/v1/config/status")
def config_status():
    """热载配置当前状态 (不触发重读)."""
    from services import config_reload as cr
    out = {}
    for name, hc in (("settings", cr.hot_settings()), ("skills", cr.hot_skills())):
        out[name] = {"loaded": hc.last_valid is not None,
                     "reload_count": hc.reload_count, "last_error": hc.last_error}
    return out


# v5.0.0 SparkSkillsHub dashboard
@app.get("/v1/spark/dashboard")
def spark_dashboard():
    """返当前 spark-output STATE JSON (供前端 dashboard.html 增量更新)."""
    from services import spark_writer
    state = spark_writer.get_state()
    return JSONResponse(state)


@app.post("/v1/spark/refresh")
def spark_refresh():
    """强制重新生成 spark-output/dashboard.html."""
    from services import spark_writer
    ok = spark_writer.update_dashboard()
    return JSONResponse({"ok": ok, "contexts": len(spark_writer.build_state().get("contexts", {}))})


# v5.1.0 AgentCache 统计 (前端 init 时拉取)
@app.get("/v1/cache/stats")
def cache_stats():
    """返 AgentCache 当前状态 + 命中率."""
    try:
        from services.agent_cache import get_cache
        return JSONResponse(get_cache().stats())
    except Exception as e:
        return JSONResponse({"error": repr(e), "size": 0, "hit_rate": 0.0})


@app.post("/v1/cache/invalidate")
def cache_invalidate(skill_id: Optional[str] = None):
    """失效缓存 (skill_id=None 全部)."""
    try:
        from services.agent_cache import get_cache
        n = get_cache().invalidate(skill_id)
        return JSONResponse({"ok": True, "invalidated": n})
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)})


# v6.0.0 NIM 探活 (云端 build.nvidia.com 或 mock fallback, 缓存 AgentCache)
@app.get("/v1/nim/health")
def nim_health(force_refresh: bool = False):
    """返 NIM (build.nvidia.com 或自配 UEA_NIM_BASE) 探活结果. 缓存到 AgentCache (nvidia:health 键)."""
    from services import nim_health as nh
    return JSONResponse(nh.nim_health(force_refresh=force_refresh))


@app.post("/v1/nim/invalidate")
def nim_invalidate():
    """失效 NIM 缓存 (下次查时重新探活)."""
    from services import nim_health as nh
    return JSONResponse({"ok": nh.invalidate_nim_cache()})

_ART = _ROOT / "data" / "artifacts"
_ART.mkdir(parents=True, exist_ok=True)

# 单例控制器 + context 结果注册表 (Working memory)
_CTRL = None
_STORE: Dict[str, Dict[str, Any]] = {}
# P1 安全: 上传限流 (令牌桶, per-client)
_LIMITER = sec.RateLimiter(capacity=60, refill_rate=10.0)


def ctrl():
    global _CTRL
    if _CTRL is None:
        _CTRL = build_controller()
    return _CTRL


def _save_upload(upload: UploadFile, subdir: str) -> str:
    d = _ART / subdir
    d.mkdir(parents=True, exist_ok=True)
    safe = sec.safe_filename(upload.filename)         # 防路径穿越
    dest = d / f"{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}_{safe}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(upload.file, fh)
    try:
        sec.size_guard(dest.stat().st_size)            # 大小上限
    except ValueError:
        dest.unlink(missing_ok=True)
        raise HTTPException(413, "upload exceeds size limit")
    return str(dest)


def _parse_saved(kind: str, path: str, material: str = "6061",
                 mock_text: Optional[str] = None) -> Dict[str, Any]:
    c = ctrl()
    if kind == "auto":
        kind = fi.classify(path)
    if kind == "email":
        return fi.parse_email_file(path) | {"kind": "email", "path": path}
    if kind == "step":
        return fi.parse_step(path, c.timo, material=material, with_features=True) | {"kind": "step", "path": path}
    if kind == "audio":
        return fi.parse_audio(path, c.funasr, mock_text=mock_text) | {"kind": "audio", "path": path}
    if kind == "pdf":
        return fi.parse_pdf(path) | {"kind": "pdf", "path": path}
    if kind == "excel":
        return fi.parse_excel(path) | {"kind": "excel", "path": path}
    if kind == "image":
        return fi.parse_image(path, c.funasr) | {"kind": "image", "path": path}
    if kind == "zip":
        return fi.parse_any(path, extract_dir=str(Path(path).parent / (Path(path).name + "_ex"))) \
            | {"kind": "zip", "path": path}
    return {"ok": False, "kind": kind, "reason": "unsupported", "path": path}


# ---------------- health ----------------
@app.get("/health")
def health():
    c = ctrl()
    return {"status": "ok", "service": "union-export-agent",
            "version": "v6.1.0-livekernel",
            "engine": c.timo.source_label(), "multimodal": c.funasr.source_label(),
            "contexts": len(_STORE)}


# ---------------- 单模态上传端口 ----------------
def _single_upload_endpoint(kind: str):
    async def _ep(file: UploadFile = File(...), material: str = Form("6061"),
                  mock_text: Optional[str] = Form(None)):
        path = _save_upload(file, kind)
        res = _parse_saved(kind, path, material=material, mock_text=mock_text)
        return JSONResponse(res)
    return _ep


app.post("/v1/upload/email")(_single_upload_endpoint("email"))
app.post("/v1/upload/step")(_single_upload_endpoint("step"))
app.post("/v1/upload/audio")(_single_upload_endpoint("audio"))
app.post("/v1/upload/pdf")(_single_upload_endpoint("pdf"))
app.post("/v1/upload/excel")(_single_upload_endpoint("excel"))
app.post("/v1/upload/image")(_single_upload_endpoint("image"))
app.post("/v1/upload/auto")(_single_upload_endpoint("auto"))


# ---------------- 黄金场景一键装载 (T1 UI 全接线, 修 #35 死按钮) ----------------
@app.post("/v1/demo/scenario/{sid}")
def demo_scenario(sid: str):
    """golden_scenarios.json → mailbox .eml → pending(driver=email) → 同步跑黄金链.

    UI 邮件台 S1-S5/M1 按钮的后端; 返回 mail_id 供 openMail 直接展开。
    """
    from email.message import EmailMessage
    from services.mail_orchestrator import MailOrchestrator
    from services.mail_puller import MailPuller

    scen_file = _ROOT / "data" / "golden_scenarios.json"
    if not scen_file.exists():
        raise HTTPException(503, "golden_scenarios.json missing")
    scenarios = json.loads(scen_file.read_text(encoding="utf-8"))["scenarios"]
    sc = next((s for s in scenarios if s.get("id") == sid), None)
    if sc is None:
        raise HTTPException(404, f"unknown scenario: {sid}")

    cust = sc.get("customer") or {}
    mail_id = f"DEMO-{sid}-{int(time.time() * 1000)}"
    mbox = _ROOT / "data" / "mailbox"
    mbox.mkdir(parents=True, exist_ok=True)
    msg = EmailMessage()
    msg["From"] = f'{cust.get("contact_name") or cust.get("name") or "Demo"} <demo-{sid.lower()}@union.local>'
    msg["To"] = "sales@union-export.local"
    msg["Subject"] = f'[DEMO {sid}] {sc.get("desc") or "RFQ"}'
    msg.set_content(sc.get("email") or "")
    (mbox / f"{mail_id}.eml").write_bytes(bytes(msg))
    (mbox / f"{mail_id}.meta.json").write_text(json.dumps({
        "badges": ["NEW"], "scenario": sid,
        "customer_id": cust.get("customer_id"),
        "from": msg["From"], "subject": msg["Subject"],
        "message_id": mail_id,
    }, ensure_ascii=False), encoding="utf-8")

    puller = _mail_bg.get("puller") or MailPuller(root=_ROOT)
    puller._enqueue_pending_from_mailbox()
    # 先占租约 (PROCESSING) 再同步跑 — 否则后台 orchestrator loop 或 pending 里
    # 陈年 NEW 条目会让 claim_next_new(FIFO) 拿错信 (claim race)。
    entry_state = (puller.pending_index().get(mail_id) or {}).get("state")
    if entry_state == "NEW":
        puller.mark_state(mail_id, "PROCESSING", consumer="demo-scenario")
        orch = _mail_bg.get("orchestrator") or MailOrchestrator(root=_ROOT, puller=puller, cat=ctrl())
        res = orch.run_pipeline(mail_id)
        return JSONResponse({
            "ok": res.ok, "scenario": sid, "mail_id": mail_id,
            "state": res.state, "context_id": res.context_id,
            "driver": res.driver, "reason": res.reason,
            "elapsed_ms": round(res.elapsed_ms, 1),
        })
    # 已被后台 loop 抢先 claim → 等它的终态 (诚实报告, 不重复跑 CAT)
    for _ in range(240):
        time.sleep(0.5)
        idx = puller.pending_index().get(mail_id) or {}
        st = idx.get("state")
        if st in ("DONE", "HITL", "BLOCKED", "FAILED", "DEAD"):
            return JSONResponse({
                "ok": st in ("DONE", "HITL", "BLOCKED"), "scenario": sid, "mail_id": mail_id,
                "state": st, "context_id": idx.get("context_id"),
                "driver": idx.get("driver") or "email",
                "reason": "processed by background orchestrator",
                "elapsed_ms": None,
            })
    return JSONResponse({
        "ok": False, "scenario": sid, "mail_id": mail_id, "state": entry_state,
        "context_id": None, "driver": "email",
        "reason": "timeout waiting for background orchestrator", "elapsed_ms": None,
    })


# ---------------- C2 上传→RAG ingestion ----------------
@app.post("/v1/rag/ingest")
async def rag_ingest(file: UploadFile = File(...),
                     customer_id: Optional[str] = Form(None),
                     tags: Optional[str] = Form(None)):
    """任意文件 (含 zip/嵌套/GBK 名) → 抽文本 → 向量化入 ingest_docs 集合。"""
    g = ctrl().rag_gateway
    if g is None:
        raise HTTPException(503, "rag gateway 未启用 (settings.rag_layers.enabled=false?)")
    path = _save_upload(file, "rag_ingest")
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    res = g.ingest_file(path, customer_id=customer_id or None, tags=tag_list,
                        doc_name=file.filename or None)
    res["filename"] = file.filename
    return JSONResponse(res)


@app.get("/v1/rag/search")
def rag_search(q: str, customer_id: Optional[str] = None, limit: int = 5):
    """检索已入库文档 (L2.5 ingest_docs)。"""
    g = ctrl().rag_gateway
    if g is None:
        raise HTTPException(503, "rag gateway 未启用")
    hits = g.search_ingested(q, customer_id=customer_id or None, limit=limit)
    return JSONResponse({"query": q, "hits": hits,
                         "embed_source": g.embedder.source})


@app.get("/v1/rag/docs")
def rag_docs_list(customer_id: Optional[str] = None):
    """已入库文档清单 (元数据, 不含全文)。"""
    g = ctrl().rag_gateway
    if g is None:
        raise HTTPException(503, "rag gateway 未启用")
    docs = g.list_ingested_docs(customer_id=customer_id or None)
    return JSONResponse({"count": len(docs), "docs": docs})


@app.delete("/v1/rag/docs/{doc_id}")
def rag_docs_delete(doc_id: str):
    g = ctrl().rag_gateway
    if g is None:
        raise HTTPException(503, "rag gateway 未启用")
    if not g.delete_ingested_doc(doc_id):
        raise HTTPException(404, f"doc not found: {doc_id}")
    return JSONResponse({"deleted": True, "id": doc_id})


# ---------------- 统一 intake: 一次收全模态 → 黄金链 ----------------
@app.post("/v1/rfq/intake")
async def rfq_intake(
    email_file: Optional[UploadFile] = File(None),
    email_text: Optional[str] = Form(None),
    audio_file: Optional[UploadFile] = File(None),
    voice_transcript: Optional[str] = Form(None),
    step_file: Optional[UploadFile] = File(None),
    pdf_file: Optional[UploadFile] = File(None),
    excel_file: Optional[UploadFile] = File(None),
    image_file: Optional[UploadFile] = File(None),
    customer_name: Optional[str] = Form(None),
    contact_name: Optional[str] = Form(None),
    customer_email: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    material_hint: Optional[str] = Form("6061"),
    incoterm: Optional[str] = Form(None),
    shipping_mode: Optional[str] = Form(None),
    hs_code: Optional[str] = Form(None),
    use_llm: Optional[bool] = Form(False),
):
    # P1 安全: 限流 (per-customer 粗粒度)
    rl_key = (customer_name or customer_email or "anon")
    if not _LIMITER.allow(rl_key):
        raise HTTPException(429, "rate limit exceeded; retry later")
    cid = f"RFQ-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    art = _ART / cid
    art.mkdir(parents=True, exist_ok=True)
    parsed: Dict[str, Any] = {}

    def _loc(uf: UploadFile) -> str:
        dest = art / sec.safe_filename(uf.filename)        # 防路径穿越
        with dest.open("wb") as fh:
            shutil.copyfileobj(uf.file, fh)
        try:
            sec.size_guard(dest.stat().st_size)
        except ValueError:
            dest.unlink(missing_ok=True)
            raise HTTPException(413, "upload exceeds size limit")
        return str(dest)

    # email
    body_text = email_text or ""
    if email_file is not None:
        p = _loc(email_file)
        em = fi.parse_email_file(p)
        parsed["email"] = em | {"path": p}
        if not body_text:
            body_text = f"{em.get('subject','')}\n{em.get('body','')}"
    # audio
    vt = voice_transcript
    if audio_file is not None:
        p = _loc(audio_file)
        au = fi.parse_audio(p, ctrl().funasr, mock_text=voice_transcript)
        parsed["audio"] = au | {"path": p}
        if not vt:
            vt = au.get("text")
    # step
    step_facts = None
    if step_file is not None:
        p = _loc(step_file)
        st = fi.parse_step(p, ctrl().timo, material=material_hint or "6061", with_features=True)
        parsed["step"] = st | {"path": p}
        step_facts = st
    # pdf
    if pdf_file is not None:
        p = _loc(pdf_file)
        pd = fi.parse_pdf(p)
        parsed["pdf"] = pd | {"path": p}
        if not body_text and pd.get("text"):
            body_text = pd["text"]
    # excel
    if excel_file is not None:
        p = _loc(excel_file)
        parsed["excel"] = fi.parse_excel(p) | {"path": p}
    # image (VLM 图纸感知; 只出感知事实, 非 MOCK 时并入上下文供抽取)
    if image_file is not None:
        p = _loc(image_file)
        im = fi.parse_image(p, ctrl().funasr)
        parsed["image"] = im | {"path": p}
        if im.get("perception") and not im.get("_mock"):
            body_text = f"{body_text}\n[Drawing perception]: {im['perception']}"

    if not body_text:
        raise HTTPException(400, "需要 email_file 或 email_text 或含文本的 pdf_file")

    customer = {"name": customer_name, "contact_name": contact_name,
                "email": customer_email, "country": country}
    customer = {k: v for k, v in customer.items() if v}

    result = ctrl().run(email_text=body_text, customer=customer,
                        voice_transcript=vt, step_facts=step_facts, context_id=cid,
                        destination_country=country, shipping_mode=shipping_mode,
                        incoterm=incoterm, hs_code=hs_code, use_llm=bool(use_llm))
    _STORE[cid] = {"inputs": parsed, "result": result, "customer": customer,
                   "email_text": body_text, "voice_transcript": vt, "step_facts": step_facts}
    return JSONResponse({"context_id": cid, "parsed_uploads": {k: v.get("_source") for k, v in parsed.items()},
                         "result": result})


# ---------------- staged 契约端点 ----------------
def _rehydrate_from_disk(cid: str) -> Optional[Dict[str, Any]]:
    """data/contexts/{cid}.json → _STORE 条目 (T2: 邮件驱动/重启后 RFQ 管线可用).

    持久化 context 是 RFQContext dump, 形状与 intake result 不同 — 在此重建:
    decision→verification/reply, manufacturing→dfm, risk→conflicts, commercial→quote/margin.
    """
    p = _ROOT / "data" / "contexts" / f"{cid}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    dec = d.get("decision") or {}
    com = d.get("commercial") or {}
    risk = d.get("risk") or {}
    result = {
        "context_id": cid,
        "state": d.get("state"),
        "verification_status": dec.get("status"),
        "reasons": dec.get("reasons") or [],
        "next_action": dec.get("next_action"),
        "reply": dec.get("reply") or {},
        "dfm": (d.get("manufacturing") or {}).get("dfm") or {},
        "multimodal_conflicts": risk.get("multimodal_conflicts") or [],
        "quote": com.get("quote") or {},
        "margin_pct": com.get("margin_pct"),
        "commercial": com or None,
        "engine_source": com.get("source") or "persisted",
        "audit_valid": None,
        "customer": d.get("customer") or {},
        "_rehydrated": True,
    }
    return {"inputs": {}, "result": result, "customer": d.get("customer") or {},
            "email_text": (d.get("rfq") or {}).get("raw_text") or "",
            "voice_transcript": None, "step_facts": None}


def _need(cid: str) -> Dict[str, Any]:
    if cid not in _STORE:
        ent = _rehydrate_from_disk(cid)
        if ent is None:
            raise HTTPException(404, f"context {cid} not found; call /v1/rfq/intake first")
        _STORE[cid] = ent
    return _STORE[cid]


@app.get("/v1/rfq/{cid}")
def get_rfq(cid: str):
    return JSONResponse(_need(cid)["result"])


@app.post("/v1/rfq/{cid}/analyze")
def analyze(cid: str):
    r = _need(cid)["result"]
    return JSONResponse({"context_id": cid, "dfm": r["dfm"],
                         "multimodal_conflicts": r["multimodal_conflicts"],
                         "state": r["state"]})


@app.post("/v1/rfq/{cid}/quote")
def quote(cid: str):
    r = _need(cid)["result"]
    return JSONResponse({"context_id": cid, "quote": r["quote"], "margin_pct": r["margin_pct"]})


@app.post("/v1/rfq/{cid}/verify")
def verify(cid: str):
    r = _need(cid)["result"]
    return JSONResponse({"context_id": cid, "status": r["verification_status"],
                         "reasons": r["reasons"], "next_action": r["next_action"]})


@app.post("/v1/rfq/{cid}/approve")
def approve(cid: str, approver: str = Form("human"), comment: Optional[str] = Form(None)):
    """人工授权: HITL → HUMAN_APPROVAL → REPLY (真实推进状态机, 落审计)."""
    from services.rfq_state_machine import RFQStateMachine, IllegalTransition
    ent = _need(cid)
    r = ent["result"]
    sm = RFQStateMachine(cid, initial=r["state"])
    try:
        if sm.state == "HITL":
            sm.transition("HUMAN_APPROVAL", reason=f"approved by {approver}: {comment or ''}", actor=approver)
            sm.transition("REPLY", reason="human approved")
            sm.transition("CRM_MEM", reason="write facts")
            sm.transition("DONE", reason="approved golden path complete")
        elif sm.state in ("BLOCKED", "ARCHIVED"):
            raise IllegalTransition("BLOCKED 不可人工直接放行, 需修正参数后重新 intake")
        r["state"] = sm.state
        r["human_approved"] = {"approver": approver, "comment": comment, "ts": time.time()}
        ent["result"] = r
        return JSONResponse({"context_id": cid, "state": sm.state, "approved": True,
                             "history": sm.history[-4:]})
    except IllegalTransition as e:
        raise HTTPException(409, str(e))


@app.post("/v1/rfq/{cid}/reply-draft")
def reply_draft(cid: str):
    r = _need(cid)["result"]
    return JSONResponse({"context_id": cid, "reply": r["reply"], "state": r["state"]})


@app.post("/v1/rfq/{cid}/crm-sync")
def crm_sync(cid: str):
    ent = _need(cid)
    c = ctrl()
    if c.crm is None:
        raise HTTPException(503, "CRM disabled")
    c.crm.upsert_customer(ent.get("customer") or {})
    c.crm.write_rfq({"context_id": cid, "rfq": {}, "state": ent["result"]["state"]})
    c.crm.write_quote({"context_id": cid, "commercial": {"quote": ent["result"]["quote"],
                                                         "margin_pct": ent["result"]["margin_pct"]}},
                      {"status": ent["result"]["verification_status"]},
                      {"subject": ent["result"]["reply"]["subject"],
                       "auto_send": ent["result"]["reply"]["auto_send"]})
    return JSONResponse({"context_id": cid, "synced": True, "crm_stats": c.crm.stats()})


@app.post("/v1/rfq/{cid}/commercial")
def commercial(cid: str):
    """P1 商业层: freight/customs/Incoterms → landed cost (确定性, 已在 intake 计算)."""
    r = _need(cid)["result"]
    if not r.get("commercial"):
        raise HTTPException(409, "该 context 无商业计算 (可能 DFM BLOCKED 未报价)")
    return JSONResponse({"context_id": cid, "commercial": r["commercial"]})


@app.post("/v1/rfq/{cid}/postmortem")
def postmortem(cid: str, outcome: str = Form(...), actual_cost: Optional[float] = Form(None),
               actual_leadtime_days: Optional[int] = Form(None), note: Optional[str] = Form(None)):
    """P3 闭环: 记录 Won/Lost + 实际成本/交期 → 偏差分析 + 知识回流建议."""
    from services.postmortem import record_outcome
    ent = _need(cid)
    c = ctrl()
    if c.crm is None:
        raise HTTPException(503, "CRM disabled")
    try:
        analysis = record_outcome(c.crm, cid, outcome, actual_cost=actual_cost,
                                  actual_leadtime_days=actual_leadtime_days, note=note or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"context_id": cid, "postmortem": analysis})


# ---------------- P2 平台层端点 ----------------
@app.get("/v1/model-router/status")
def model_router_status():
    """L3 Model Mesh 路由状态 (FAST/VISION/REASON/EMBED/ASR/DETERMINISTIC)."""
    return JSONResponse(ctrl().router.status())


# ---------------- v2.4.0 STEP 缩略图 (UI `🎨3D` tab 后端) ----------------
@app.post("/v1/upload/step-with-thumbnail")
async def upload_step_with_thumbnail(file: UploadFile = File(...)):
    """上传 .step/.stp → 真实几何摘要 + SVG 缩略图 (bbox + 体积 + 特征数)."""
    name = file.filename or "uploaded.step"
    ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    if ext not in ("step", "stp"):
        raise HTTPException(400, f"unsupported ext: {ext}, 仅 .step/.stp")
    saved = _save_upload(file, "step3d")
    try:
        from services.step_thumbnail import make_thumbnail
        out = make_thumbnail(ctrl().timo, saved)
    except Exception as e:
        raise HTTPException(500, f"thumbnail failed: {e!r}")
    if not out.get("ok"):
        raise HTTPException(400, out.get("reason", "thumbnail failed"))
    return JSONResponse({
        "filename": name,
        "bbox": out.get("bbox"),
        "volume_cm3": out.get("volume_cm3"),
        "mass_g": out.get("mass_g"),
        "features_count": out.get("features_count"),
        "sha256_16": out.get("sha256_16"),
        "cached": out.get("cached"),
        "svg": out.get("svg"),
        "_source": out.get("_source"),
    })


# ---------------- v2.4.0 用户反馈邮箱 (UI `🆘反馈` tab 后端) ----------------
@app.post("/v1/feedback")
async def feedback_submit(request: Request):
    """提交一条反馈 (json body 含 type/title/body/email/honeypot/source)."""
    from services import feedback_store as fs
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "invalid json body")
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")
    res = fs.submit(payload, ip=ip, user_agent=ua)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "submit failed"))
    return JSONResponse({"id": res["id"], "created_at": res["created_at"]})


@app.get("/v1/feedback")
def feedback_list(limit: int = 20, status: Optional[str] = None):
    """列出最近 N 条反馈 (header badge 与侧栏共用)."""
    from services import feedback_store as fs
    items = fs.list_recent(limit=limit, status=status)
    return JSONResponse({"items": items, "count": len(items)})


@app.get("/v1/feedback/unread")
def feedback_unread():
    """未读反馈计数, header badge 显示."""
    from services import feedback_store as fs
    return JSONResponse({"unread": fs.count_unread()})


@app.get("/v1/agent-spec")
def agent_spec():
    """nemo-agents-spec-v1 部署契约 + 自洽校验结果."""
    from services.agent_spec import load_agent_spec, validate
    spec = load_agent_spec(_ROOT)
    return JSONResponse({"validation": validate(spec), "spec": spec})


@app.get("/v1/skills")
def skills_registry():
    """Agent Skills 注册表: skills/*/SKILL.md → 摘要 + OpenAI function-calling 工具描述 + allow-list 交叉校验."""
    from services import skill_registry as sr
    from services.guardrails import TOOL_ALLOWLIST
    from skills import _runtime as rt
    return JSONResponse({"registry": sr.summary(),
                         "cross_check": sr.cross_check_allowlist(TOOL_ALLOWLIST),
                         "runtime_skills": rt.list_skills()})


# ---------------- v3.0.0 NemoClaw: Skill Dispatcher + 设置 ----------------
@app.get("/v1/skills/config")
def skills_config_get():
    """Skill / OpenShell / Dispatcher 设置 (UI 第 6 tab 后端)."""
    from services import skill_config as sc
    from services.openshell import OpenShell, load_policies
    from skills import _runtime as rt
    cfg = sc.load()
    try:
        shell = OpenShell(cfg=cfg)
        os_status = shell.status()
    except Exception as e:  # noqa
        os_status = {"error": repr(e), "policies": []}
    return JSONResponse({
        "config": cfg,
        "summary": sc.summary(cfg),
        "runtime_skills": rt.list_skills(),
        "openshell": os_status,
        "iron_rule_1_locked": True,
    })


@app.post("/v1/skills/config")
async def skills_config_set(payload: Dict[str, Any]):
    """保存 Skill 配置。iron-rule-1 强制 locked=true; 校验失败 400."""
    from services import skill_config as sc
    from services.skill_dispatcher import reset_dispatcher
    try:
        saved = sc.save(payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    reset_dispatcher()
    return JSONResponse({"saved": True, "summary": sc.summary(saved), "config": saved})


@app.post("/v1/agent/task")
async def agent_task(request: Request):
    """NemoClaw 混合调度入口: intent/files → Skill 序列执行 + OpenShell 门禁."""
    from services.skill_dispatcher import get_dispatcher
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "invalid json body")
    intent = payload.get("intent") or payload.get("text") or ""
    files = payload.get("files") or []
    if isinstance(files, str):
        files = [files]
    args = payload.get("args") or {}
    # 顶层便利字段并入 args
    for k in ("customer", "material", "quantity", "surface", "tolerance_grade",
              "type", "title", "body", "email", "use_llm", "destination_country",
              "shipping_mode", "incoterm", "rfq", "top_n", "path", "ctx_dict"):
        if k in payload and k not in args:
            args[k] = payload[k]
    if not intent and not files and not payload.get("skills"):
        raise HTTPException(400, "intent/files/skills 至少提供一个")
    # P0 标记 (方案 D): driver=驱动来源; 本端点是 agent 平面入口, 默认 agent,
    # 控制台 / 调度器 / 邮件驱动调用方显式传 driver=console/scheduler/email
    driver = str(payload.get("driver") or "agent")
    if driver not in ("email", "agent", "console", "scheduler"):
        raise HTTPException(400, f"invalid driver: {driver}")
    disp = get_dispatcher()
    try:
        resp = disp.dispatch(
            intent=intent,
            files=list(files),
            context_id=payload.get("context_id"),
            skills=payload.get("skills"),
            args=args,
            driver=driver,
        )
    except Exception as e:  # noqa
        raise HTTPException(500, f"dispatch failed: {e!r}")
    return JSONResponse(resp)


@app.get("/v1/agent/openshell")
def agent_openshell():
    """OpenShell 策略状态 + 最近审计."""
    from services.skill_dispatcher import get_dispatcher
    from services import skill_config as sc
    disp = get_dispatcher()
    return JSONResponse({
        "openshell": disp.shell.status(),
        "audit": disp.recent_audit(20),
        "config_summary": sc.summary(),
    })


@app.post("/v1/agent/route")
async def agent_route(request: Request):
    """仅做意图路由预览, 不执行 Skill."""
    from services.skill_dispatcher import get_dispatcher
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "invalid json body")
    intent = payload.get("intent") or ""
    files = payload.get("files") or []
    disp = get_dispatcher()
    return JSONResponse(disp.route(intent, files))


# ---------------- 模型设置工具 (UI 后端): LLM/VLM/Embedding/OCR/ASR ----------------
@app.get("/v1/models/config")
def models_config_get():
    """读取模型注册表 (config/models.yaml) + 当前在线探测结果。"""
    from services import model_config as mc
    cfg = mc.load()
    return JSONResponse({"config": cfg, "probe": mc.probe_all(cfg)})


@app.post("/v1/models/config")
async def models_config_set(payload: Dict[str, Any]):
    """保存模型注册表 (UI 编辑端点/模型名/启用)。校验失败 400; deterministic 锁定不可禁用。"""
    from services import model_config as mc
    try:
        saved = mc.save(payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # 让运行中的控制器下次重建时读到新配置 (清空单例缓存)
    global _CTRL
    if _CTRL is not None and _CTRL.crm is not None:
        _CTRL.crm.close()
    _CTRL = None
    return JSONResponse({"saved": True, "config": saved, "probe": mc.probe_all(saved)})


@app.post("/v1/models/probe")
def models_probe(key: Optional[str] = Form(None)):
    """测试连接: 探测全部或单个模型端点, 返回 online/时延/错误。"""
    from services import model_config as mc
    cfg = mc.load()
    if key:
        entry = mc.get_model(cfg, key)
        if not entry:
            raise HTTPException(404, f"unknown model key: {key}")
        return JSONResponse({key: {"label": entry.get("label"), **mc.probe_one(entry)}})
    return JSONResponse(mc.probe_all(cfg))


@app.get("/", include_in_schema=False)
def webui():
    """v6.0.0 融合版 UI (根 index.html, 真接线 5 endpoints).
    legacy webui/index.html 保留为 /v5 或 /webui fallback.
    """
    from fastapi.responses import FileResponse
    # v6 优先: 根 index.html (融合版, 真接线 5 endpoints)
    root_idx = _ROOT / "index.html"
    if root_idx.exists():
        return FileResponse(str(root_idx))
    # legacy fallback: webui/index.html
    legacy = _ROOT / "webui" / "index.html"
    if legacy.exists():
        return FileResponse(str(legacy))
    return JSONResponse({"hint": "index.html + webui/index.html 都缺失", "docs": "/docs"})


@app.get("/webui", include_in_schema=False)
def webui_legacy():
    """v5.0.0 legacy 单文件 UI (webui/index.html, 含三栏 + 黄金链 + 3D)."""
    from fastapi.responses import FileResponse
    idx = _ROOT / "webui" / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse({"hint": "webui/index.html 缺失", "docs": "/docs"})


@app.post("/v1/guardrails/check")
def guardrails_check(text: str = Form(...), stage: str = Form("input")):
    """独立护栏检查端点 (input/tool/output), 供联调与审计。"""
    g = ctrl().guard
    if stage == "input":
        return JSONResponse(g.check_input(text))
    if stage == "tool":
        return JSONResponse(g.check_tool(text))
    if stage == "output":
        return JSONResponse(g.check_output(text))
    raise HTTPException(400, "stage must be input|tool|output")


@app.get("/v1/traces/{cid}")
def get_trace(cid: str):
    """读取某 context 的 OTEL 风格 trace (JSONL)。"""
    ent = _STORE.get(cid)
    if ent and ent["result"].get("observability"):
        return JSONResponse(ent["result"]["observability"])
    p = _ROOT / "data" / "traces" / f"{cid}.jsonl"
    if p.exists():
        spans = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        return JSONResponse({"context_id": cid, "spans": spans, "span_count": len(spans)})
    raise HTTPException(404, f"trace for {cid} not found")


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8900
    print(f"Union Export Agent API on http://127.0.0.1:{port}  (docs: /docs)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
