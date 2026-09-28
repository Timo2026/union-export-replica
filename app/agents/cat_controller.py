"""cat_controller.py — Control Loop A: CAT (Context → Action → Test) 编排器.

Supervisor 角色: 拆解任务、路由技能、推进状态机, **不负责业务数字**。
业务数字来自 TimoAdapter (确定性引擎); 裁决来自 Verification (policy)。

黄金链 (对齐冻结 PRD P0):
  Email(/Voice/PDF/STEP) → Intake → Context → RFQ → DFM → Quote → Verify(辟牟援推止)
    → HITL/BLOCKED/REPLY → CRM+Memory → Audit
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from services.audit import AuditChain
from services.commercial import compute_commercial
from services.context_engine import Context, ContextEngine
from services.crm_memory import CRMMemory
from services.guardrails import Guardrails
from services.intake import (detect_multimodal_conflict, extract_rfq,
                             extract_voice_claims)
from services.model_router import ModelRouter
from services.observability import Tracer
from services.postmortem import recall_customer_memory
from services.rag import RAGEvidence
from services.reply import build_reply
from services.rfq_state_machine import RFQStateMachine
from services.verification import Verification
from services import schema_validator as sv


class CATController:
    def __init__(self, timo, funasr, policy: Dict[str, Any], settings: Dict[str, Any],
                 crm: Optional[CRMMemory] = None, commercial_cfg: Optional[Dict[str, Any]] = None,
                 planner=None, rag_gateway=None):
        self.timo = timo
        self.funasr = funasr
        self.policy = policy
        self.settings = settings
        self.commercial_cfg = commercial_cfg or {}
        self.planner = planner
        self.ctx_engine = ContextEngine(
            store_dir=settings.get("storage", {}).get("contexts_dir", "data/contexts"),
            prefix=settings.get("context_id_prefix", "RFQ"))
        self.verify = Verification(policy)
        self.rag = RAGEvidence(funasr)
        self.crm = crm
        # ===== B3 分层 RAG 网关 (任务 #25): L2 报价锚点 + L4 工艺证据 =====
        # crm 存在时自动构建 (离线 → HashEmbedder 确定性降级); 失败降级为 None 走旧路径
        self.rag_gateway = rag_gateway
        if self.rag_gateway is None and crm is not None:
            try:
                from services.flywheel.vector_store import get_vector_store
                from services.rag_layers import HybridEmbedder, LayeredRAGGateway
                cfg = settings.get("rag_layers", {}) or {}
                if cfg.get("enabled", True):
                    # embed_url 单一来源: 显式 rag_layers.embed_url 优先, 否则派生 funasr.embed_url
                    fu = str((settings.get("funasr", {}) or {}).get("embed_url",
                                                                    "http://127.0.0.1:1278")).rstrip("/")
                    emb = HybridEmbedder(url=cfg.get("embed_url") or f"{fu}/v1",
                                         timeout=float(cfg.get("timeout_s", 3.0)),
                                         degrade_cooldown_s=float(cfg.get("degrade_cooldown_s", 60.0)))
                    store = get_vector_store(backend=cfg.get("vector_backend", "memory"))
                    self.rag_gateway = LayeredRAGGateway(store=store, crm=crm,
                                                         funasr=funasr, rag=self.rag,
                                                         embedder=emb)
                    if store.count("quote_history") == 0:
                        self.rag_gateway.index_all_quotes()
            except Exception as e:
                log = logging.getLogger(__name__)
                log.warning("[cat] rag_gateway 自动构建失败, 回退 rag.py: %r", e)
                self.rag_gateway = None
        # P2 平台层: 护栏 + 模型路由 (可观测 Tracer 按 context 在 run() 内创建)
        self.guard = Guardrails(policy, backend=(settings.get("guardrails", {}) or {}).get("backend", "builtin"))
        self.router = ModelRouter(settings, timo=timo)
        self._trace_dir = settings.get("storage", {}).get("traces_dir", "data/traces")
        self._otlp = (settings.get("observability", {}) or {}).get("otlp_endpoint")
        # ===== v6.1 飞轮层 (T6.9) =====
        # 飞轮是工具, 非业务逻辑 (铁律⑥保持); CRM 缺失时降级为 no-op
        self.flywheel = None
        if crm is not None:
            try:
                from services.customer_health import CustomerHealthEngine
                from services.quote_calibration import QuoteCalibration
                from services.customer_flywheel import CustomerFlywheel
                heal = CustomerHealthEngine(crm)
                cal = QuoteCalibration(crm)
                self.flywheel = CustomerFlywheel(crm, heal, cal, funasr_adapter=funasr)
            except Exception as e:
                self.flywheel = None

    # ---------- CAT primitive ----------
    def _action(self, audit: AuditChain, name: str, fn, *a,
                tracer: Optional[Tracer] = None, guard_params: Optional[Dict[str, Any]] = None, **kw):
        """Action → Test: 工具护栏 → 执行技能 (span) → 落审计。"""
        # 工具护栏 (tool allow-list + 参数 schema)
        g = self.guard.check_tool(name, guard_params or {})
        if tracer:
            tracer.bump("tool_calls")
        if not g["pass"]:
            if tracer:
                tracer.bump("tool_errors")
            audit.log("guardrail_tool_block", {"tool": name, "flags": g["flags"]}, actor="guardrails")
            raise PermissionError(f"tool guardrail blocked '{name}': {g['flags']}")
        t0 = time.time()
        span = tracer.start_span(f"skill:{name}", kind="client") if tracer else None
        try:
            res = fn(*a, **kw)
            if span:
                span.set(ok=True, source=(res.get("_source") if isinstance(res, dict) else None))
                span.end = time.time(); span.status = "OK"; span.attrs["ms"] = round((span.end - span.start) * 1000, 2)
            audit.log("action", {"skill": name, "ok": True,
                                 "ms": round((time.time() - t0) * 1000, 1),
                                 "source": (res.get("_source") if isinstance(res, dict) else None)},
                      actor="supervisor")
            return res
        except Exception as e:
            if span:
                span.end = time.time(); span.status = "ERROR"; span.attrs["error"] = repr(e)
            if tracer:
                tracer.bump("tool_errors")
            audit.log("action", {"skill": name, "ok": False, "error": repr(e)}, actor="supervisor")
            raise

    # ---------- main golden path ----------
    def run(self, email_text: str, customer: Optional[Dict[str, Any]] = None,
            voice_transcript: Optional[str] = None, audio_path: Optional[str] = None,
            step_facts: Optional[Dict[str, Any]] = None,
            context_id: Optional[str] = None,
            destination_country: Optional[str] = None,
            shipping_mode: Optional[str] = None,
            incoterm: Optional[str] = None,
            hs_code: Optional[str] = None,
            use_llm: bool = False,
            driver: str = "email") -> Dict[str, Any]:
        customer = customer or {}
        ctx: Context = self.ctx_engine.create(context_id)
        sm = RFQStateMachine(ctx.context_id)
        audit = AuditChain(ctx.context_id,
                           path=f"{self.settings.get('storage',{}).get('contexts_dir','data/contexts')}/{ctx.context_id}.audit.json")
        ctx.state = sm.state
        audit.log("context_created", {"context_id": ctx.context_id,
                                      "customer": customer.get("name"),
                                      "driver": driver or "email"}, actor="supervisor")

        # ===== v6.1 飞轮 before_run 钩子 (T6.9) =====
        # 加载客户飞轮状态 (健康分/价格偏移/待办) 注入 Context
        if self.flywheel is not None:
            try:
                ctx.flywheel_state = self.flywheel.before_run(customer)
                ctx.sandbox_ref = ctx.flywheel_state.get("customer_id", "") or \
                                  customer.get("customer_id", "")
                # 健康分过低 → 升级 HITL (非 BLOCKED 时)
                if ctx.flywheel_state.get("_escalate_to_HITL"):
                    audit.log("flywheel_escalate",
                              {"reason": ctx.flywheel_state.get("_escalate_reason")},
                              actor="flywheel")
            except Exception as e:
                audit.log("flywheel_before_error", {"error": repr(e)}, actor="flywheel")

        # --- P2 可观测: 每个 context 一条 trace, root span = agent_run ---
        tracer = Tracer(ctx.context_id, export_dir=self._trace_dir, otlp_endpoint=self._otlp)
        root = tracer.start_span("agent_run", kind="server", context_id=ctx.context_id)
        root.start = root.start  # noqa
        tracer._push(root)

        # --- NEW → INTAKE: 邮件证据 ---
        sm.transition("INTAKE", reason="email received")
        ctx.state = sm.state
        # P2 输入护栏: prompt injection / 数据外泄 / 危险内容 / 凭证泄露
        in_guard = self.guard.check_input(email_text, source="email")
        guard_escalate = not in_guard["pass"]
        audit.log("guardrail_input", {"pass": in_guard["pass"],
                                      "flags": [f.get("type") for f in in_guard["flags"]]},
                  actor="guardrails")
        with tracer.start_span("guardrail:input") as sp:
            sp.set(passed=in_guard["pass"], flags=[f.get("type") for f in in_guard["flags"]])
        ev_email = ctx.add_evidence("email", email_text, confidence=0.98,
                                    claims=[{"field": "raw", "value": email_text[:200]}])
        audit.log("intake", {"evidence_id": ev_email.evidence_id, "source": "email"})

        # --- INTAKE → STRUCTURING: 结构化 RFQ 抽取 ---
        sm.transition("STRUCTURING", reason="extract canonical RFQ")
        rfq = self._action(audit, "rfq-extraction", extract_rfq, email_text, customer,
                           tracer=tracer, guard_params={"_text_only": True})
        rfq["customer"] = {"customer_id": customer.get("customer_id"),
                           "name": customer.get("name"), "contact_name": customer.get("contact_name")}
        ctx.rfq = rfq
        ctx.customer = customer
        audit.log("rfq_structured", {"material": rfq.get("material"), "surface": rfq.get("surface"),
                                     "quantity": rfq.get("quantity"),
                                     "tolerance": rfq.get("tolerance_grade"),
                                     "missing": rfq.get("missing_information")})

        # --- P0 LLM Planner (opt-in): LLM 提议补全缺字段, 正则/引擎值仍权威 (LLM 提议→引擎裁决) ---
        llm_info: Dict[str, Any] = {"enabled": bool(use_llm), "used": False}
        if use_llm and self.planner is not None and self.planner.online():
            with tracer.start_span("llm:rfq-extraction", kind="client") as sp:
                lr = self.planner.extract_rfq(email_text)
                sp.set(ok=lr.get("ok"), source=lr.get("_source"))
            data = lr.get("data") or {}
            filled = []
            if isinstance(data, dict):
                # 只用 LLM 填补正则未抽到的空字段; 不覆盖已有确定性值
                for k_src, k_dst in [("material", "material"), ("surface", "surface"),
                                     ("quantity", "quantity"), ("tolerance_grade", "tolerance_grade"),
                                     ("tolerance_mm", "tolerance_mm"), ("dimensions_mm", "dimensions_mm")]:
                    if rfq.get(k_dst) in (None, "", []) and data.get(k_src) not in (None, "", []):
                        rfq[k_dst] = data[k_src]
                        filled.append(k_dst)
                # 重算缺失项
                miss = []
                if not rfq.get("material"):
                    miss.append("material")
                if rfq.get("quantity") is None:
                    miss.append("quantity")
                if not rfq.get("surface"):
                    miss.append("surface_finish")
                if not rfq.get("tolerance_grade"):
                    miss.append("tolerance")
                rfq["missing_information"] = miss
                tracer.bump("model_calls")
            llm_info = {"enabled": True, "used": True, "source": lr.get("_source"),
                        "ok": lr.get("ok"), "filled_fields": filled}
            audit.log("llm_extraction", {"source": lr.get("_source"), "filled": filled,
                                         "schema_errors": lr.get("schema_errors")}, actor="llm-planner")
            ctx.rfq = rfq

        # --- 语音证据 + 多模态冲突 (M1) ---
        mm_conflicts: List[Dict[str, Any]] = []
        if voice_transcript or audio_path:
            if audio_path and self.funasr is not None:
                tr = self._action(audit, "asr", self.funasr.transcribe, audio_path,
                                  mock_text=voice_transcript, tracer=tracer)
                voice_transcript = tr.get("text", voice_transcript)
                ev_voice = ctx.add_evidence("audio", voice_transcript, confidence=0.85,
                                            mock=tr.get("_mock", False))
            else:
                ev_voice = ctx.add_evidence("audio", voice_transcript, confidence=0.85, mock=True)
            claims = extract_voice_claims(voice_transcript or "")
            ev_voice.claims = claims
            mm_conflicts = detect_multimodal_conflict(
                rfq, claims, self.policy.get("multimodal", {}).get("tolerance_delta_mm", 0.005))
            audit.log("voice_evidence", {"claims": claims,
                                         "conflicts": [c["type"] for c in mm_conflicts],
                                         "mock": ev_voice.mock})

        # STEP / geometry facts (几何驱动报价: 用真实 OCP 体积/重量覆盖默认值)
        if step_facts:
            ctx.geometry = step_facts
            ctx.add_evidence("step", step_facts, confidence=0.99)
            geo = step_facts.get("geometry", step_facts) if isinstance(step_facts, dict) else {}
            if isinstance(geo, dict):
                if geo.get("weight_kg") is not None:
                    rfq["weight_kg"] = geo["weight_kg"]
                if geo.get("surface_area_dm2") is not None:
                    rfq["surface_area_dm2"] = geo["surface_area_dm2"]
                if geo.get("max_dim_mm") is not None:
                    rfq["max_dim_mm"] = geo["max_dim_mm"]
                if geo.get("bbox_mm"):
                    rfq["dimensions_mm"] = geo["bbox_mm"]
                feats = step_facts.get("features") if isinstance(step_facts, dict) else None
                if isinstance(feats, dict) and feats.get("ok") and feats.get("hole_count"):
                    rfq["thread_count"] = feats.get("thread_suspect") or 0
                rfq["_geometry_driven"] = True
                audit.log("geometry_enriched", {"weight_kg": rfq.get("weight_kg"),
                                                "max_dim_mm": rfq.get("max_dim_mm"),
                                                "volume_source": geo.get("volume_source")})

        ctx.risk["multimodal_conflicts"] = mm_conflicts

        # --- STRUCTURING → DFM: 工艺冲突检测 (辟) ---
        # 信息缺失或有硬冲突可能, 仍先进 DFM 让引擎裁决
        sm.transition("DFM", reason="dfm check")
        dfm = self._action(audit, "dfm-conflict", self.timo.conflict_check,
                           rfq.get("material", ""), rfq.get("surface") or "无",
                           rfq.get("tolerance_grade", ""),
                           tracer=tracer,
                           guard_params={"material": rfq.get("material"),
                                         "tolerance_grade": rfq.get("tolerance_grade")})
        ctx.manufacturing["dfm"] = dfm
        audit.log("dfm_result", {"valid": dfm.get("valid"),
                                 "conflicts": [c.get("message") for c in dfm.get("conflicts", [])],
                                 "source": dfm.get("_source")})

        # --- DFM → QUOTING or BLOCKED ---
        quote: Dict[str, Any] = {}
        if dfm.get("valid"):
            sm.transition("QUOTING", reason="dfm passed")
            quote = self._action(audit, "cnc-quote", self.timo.quote, rfq,
                                 tracer=tracer,
                                 guard_params={"material": rfq.get("material"),
                                               "quantity": rfq.get("quantity"),
                                               "tolerance_grade": rfq.get("tolerance_grade")})
            ctx.commercial["quote"] = quote
            ctx.commercial["source"] = quote.get("_source")
            # 毛利 = profit / final_price
            profit = quote.get("profit")
            final = quote.get("final_price") or quote.get("total_price")
            if profit is not None and final:
                ctx.commercial["margin_pct"] = round(float(profit) / float(final) * 100, 1)
            ctx.commercial["lead_time_days"] = quote.get("lead_time_days")
            audit.log("quote", {"unit_price": quote.get("unit_price"),
                                "final_price": final, "margin_pct": ctx.commercial.get("margin_pct"),
                                "source": quote.get("_source")})
            # --- P1 商业层: freight/customs/incoterms → landed cost (确定性) ---
            if self.commercial_cfg:
                comm = self._action(
                    audit, "freight-customs", compute_commercial,
                    quote, rfq, self.commercial_cfg,
                    destination_country=(customer.get("country") or destination_country),
                    shipping_mode=shipping_mode, incoterm=incoterm, hs_code=hs_code,
                    tracer=tracer)
                ctx.commercial["freight_customs"] = comm
                ctx.commercial["landed_cost"] = comm.get("landed_cost")
                ctx.commercial["seller_quote_price"] = comm.get("seller_quote_price")
                ctx.commercial["incoterm"] = comm.get("incoterm")
                ctx.commercial["total_lead_time_days"] = comm.get("lead_time", {}).get("total_days")
                audit.log("commercial", {"incoterm": comm.get("incoterm"),
                                         "landed_cost": comm.get("landed_cost"),
                                         "seller_quote_price": comm.get("seller_quote_price"),
                                         "total_lead_days": comm.get("lead_time", {}).get("total_days")})
            # --- 飞轮: 记录报价 + 客户交互 ---
            cid = customer.get("customer_id", "")
            if cid and self.flywheel is not None:
                try:
                    from services.sandbox import get_sandbox
                    sandbox = get_sandbox(cid)
                    sandbox.write_rfq(ctx.context_id, rfq)
                    sandbox.write_quote(ctx.context_id, quote)
                    sandbox.add_followup("quote_sent", ctx.context_id,
                                         f"margin_{quote.get('margin_pct', 'N/A')}%")
                    sandbox.close()
                except Exception:
                    pass
        else:
            sm.transition("BLOCKED", reason="DFM hard conflict")
            ctx.state = sm.state
            audit.log("blocked", {"reason": "dfm_hard_conflict"})

        # --- 援: RAG 证据检索 (带 customer_id 过滤) ---
        cid = customer.get("customer_id", "")
        rag_q = f"{rfq.get('material','')} {rfq.get('surface','')} {rfq.get('tolerance_grade','')} 工艺"
        quote_anchor: Optional[Dict[str, Any]] = None
        if self.rag_gateway is not None:
            # B3: 分层网关 — quotes(L2 锚点, 仅证据不改引擎数字) + craft(L4 工艺)
            layered = self.rag_gateway.search(rag_q, customer_id=cid or None,
                                              layers=("quotes", "craft"), top_k=3)
            craft_lay = layered["layers"]["craft"]
            rag = {"hits": craft_lay["hits"], "_source": craft_lay["source"],
                   "_mock": bool(craft_lay.get("degraded"))}
            quotes_lay = layered["layers"]["quotes"]
            quote_anchor = {
                "hits": [{"quote_id": h["payload"].get("quote_id"),
                          "customer_id": h["payload"].get("customer_id"),
                          "unit_price": h["payload"].get("unit_price"),
                          "score": round(float(h["score"]), 4)}
                         for h in quotes_lay["hits"]],
                "source": quotes_lay["source"],
                "embed_source": quotes_lay.get("embed_source"),
                "degraded": bool(quotes_lay.get("degraded"))}
            if quote_anchor["hits"]:
                ctx.add_evidence("quote_anchor", quote_anchor["hits"], confidence=0.75,
                                 mock=quote_anchor["degraded"])
        else:
            rag = self.rag.search(rag_q, limit=3, customer_id=cid or None)
        tracer.bump("retrievals")
        ctx.add_evidence("rag", rag.get("hits", []), confidence=0.7, mock=rag.get("_mock", True))
        audit.log("rag_evidence", {"hits": len(rag.get("hits", [])), "source": rag.get("_source")})
        audit.log("quote_anchor", {"n": len(quote_anchor["hits"]) if quote_anchor else 0,
                                   "source": quote_anchor["source"] if quote_anchor else None})

        # --- 援: 客户记忆召回 (Fact memory → 证据 + 风险信号) ---
        mem = recall_customer_memory(self.crm, customer)
        if mem.get("recall"):
            ctx.customer["customer_id"] = mem.get("customer_id") or ctx.customer.get("customer_id")
            ctx.customer["is_new"] = mem.get("is_new", True)
            ctx.risk["customer_signals"] = mem.get("signals", [])
            ctx.add_evidence("crm", {"recall": mem.get("signals", []),
                                     "history_n": mem.get("history", {}).get("n", 0)},
                             confidence=0.8, mock=False)
            audit.log("customer_memory_recall", {"is_new": mem.get("is_new"),
                                                 "signals": [s.get("type") for s in mem.get("signals", [])]})

        # --- P1 运行时 Schema 校验 (让 schemas/*.json 生效; 不致命, 记录并供审计) ---
        sch_rfq = sv.validate_rfq(rfq)
        sch_quote = sv.validate_quote(quote or None)
        ctx.risk["schema"] = {"rfq_valid": sch_rfq["valid"], "rfq_errors": sch_rfq["errors"][:3],
                              "quote_valid": sch_quote["valid"], "quote_errors": sch_quote["errors"][:3]}
        audit.log("schema_validation", {"rfq_valid": sch_rfq["valid"], "quote_valid": sch_quote["valid"],
                                        "rfq_errors": sch_rfq["errors"][:3]}, actor="schema")
        with tracer.start_span("schema:validate") as sp:
            sp.set(rfq_valid=sch_rfq["valid"], quote_valid=sch_quote["valid"])

        # --- VERIFY (辟牟援推止) ---
        ctx_dict = ctx.to_dict()
        ctx_dict["risk"]["multimodal_conflicts"] = mm_conflicts
        if dfm.get("valid"):
            sm.transition("VERIFY", reason="run verification loop")
        ctx.state = sm.state
        verification = self._action(audit, "verification", self.verify.run, ctx_dict, tracer=tracer)

        # --- P2 输入护栏升级: 命中注入/外泄/危险/凭证 → 强制 HITL (BLOCKED 除外) ---
        if guard_escalate and verification["status"] != "BLOCKED":
            verification["status"] = "HITL"
            verification["reasons"] = (["输入护栏命中: " +
                                        ",".join(f.get("type", "") for f in in_guard["flags"])]
                                       + verification["reasons"])
            verification["next_action"] = "HUMAN_REVIEW"
            audit.log("guardrail_escalate", {"to": "HITL",
                                             "flags": [f.get("type") for f in in_guard["flags"]]},
                      actor="guardrails")
        ctx.decision = verification
        audit.log("verification", {"status": verification["status"],
                                   "reasons": verification["reasons"],
                                   "next_action": verification["next_action"]})
        with tracer.start_span("verification") as sp:
            sp.set(status=verification["status"], reasons=verification["reasons"])
        if verification["status"] == "HITL":
            tracer.bump("hitl_triggers")

        # --- route by status ---
        status = verification["status"]
        reply: Dict[str, Any] = {}
        if sm.state == "BLOCKED":
            # 已是 BLOCKED (DFM 硬冲突); 生成不可发送的澄清草稿
            reply = build_reply(ctx.to_dict(), verification)
            sm.transition("ARCHIVED", reason="blocked, alternative suggested")
        elif status == "BLOCKED":
            sm.transition("BLOCKED", reason="verification block (margin/redline)")
            reply = build_reply(ctx.to_dict(), verification)
            sm.transition("ARCHIVED", reason="blocked archived")
        elif status == "HITL":
            sm.transition("HITL", reason="; ".join(verification["reasons"])[:120])
            reply = build_reply(ctx.to_dict(), verification)
            # 停在 HITL, 等待人工授权 (不自动发送)
        else:  # PASS
            sm.transition("REPLY", reason="auto reply draft")
            reply = build_reply(ctx.to_dict(), verification)
            sm.transition("CRM_MEM", reason="write facts + memory")

        # --- P0 LLM Planner (opt-in): LLM 起草回复, 仍过输出护栏 (数字来自引擎, LLM 只措辞) ---
        if use_llm and self.planner is not None and self.planner.online() and status != "BLOCKED":
            with tracer.start_span("llm:reply-draft", kind="client") as sp:
                lr = self.planner.draft_reply({
                    "status": status, "material": rfq.get("material"), "quantity": rfq.get("quantity"),
                    "surface": rfq.get("surface"), "unit_price": (quote or {}).get("unit_price"),
                    "final_price": (quote or {}).get("final_price"),
                    "lead_time_days": (quote or {}).get("lead_time_days"),
                    "currency": (quote or {}).get("currency", "CNY"),
                    "reasons": verification.get("reasons", [])})
                sp.set(ok=lr.get("ok"), source=lr.get("_source"))
            d = lr.get("data") or {}
            if lr.get("ok") and isinstance(d, dict) and d.get("body"):
                cand = self.guard.check_output(d.get("body", ""), quote or None, status, False)
                if cand["pass"]:                       # LLM 草稿必须过输出护栏才采用
                    reply["subject"] = d.get("subject") or reply.get("subject")
                    reply["body"] = d["body"]
                    reply["draft_source"] = "llm-planner"
                    llm_info["reply_drafted"] = True
                    tracer.bump("model_calls")
                    audit.log("llm_reply_draft", {"source": lr.get("_source"), "adopted": True},
                              actor="llm-planner")
                else:
                    llm_info["reply_rejected_by_guard"] = [f.get("type") for f in cand["flags"]]
                    audit.log("llm_reply_draft", {"adopted": False,
                                                  "guard_flags": [f.get("type") for f in cand["flags"]]},
                              actor="guardrails")

        # --- P2 输出护栏: quote schema / 禁止承诺 / 外发策略 (命中强制不发送 + 记录) ---
        out_guard = self.guard.check_output(reply.get("body", ""), quote or None,
                                            verification["status"], reply.get("auto_send", False))
        if out_guard["force_no_send"]:
            reply["auto_send"] = False
        reply["guardrail_output"] = {"pass": out_guard["pass"],
                                     "flags": [f.get("type") for f in out_guard["flags"]]}
        audit.log("guardrail_output", {"pass": out_guard["pass"],
                                       "flags": [f.get("type") for f in out_guard["flags"]]},
                  actor="guardrails")

        ctx.state = sm.state
        ctx.decision["reply"] = reply

        # --- CRM + Memory ---
        if self.crm is not None:
            self.crm.upsert_customer(customer)
            self.crm.write_rfq(ctx.to_dict())
            self.crm.write_quote(ctx.to_dict(), verification, reply)

        # ===== v6.1 飞轮 after_run 钩子 (T6.9) =====
        # 落沙箱 + 跟进调度 + 健康分重算
        flywheel_result: Dict[str, Any] = {"_skipped": "no flywheel"}
        if self.flywheel is not None:
            try:
                flywheel_result = self.flywheel.after_run(
                    ctx.to_dict(), verification, reply
                )
                audit.log("flywheel_after", flywheel_result, actor="flywheel")
            except Exception as e:
                audit.log("flywheel_after_error", {"error": repr(e)}, actor="flywheel")

        # --- REPLY → DONE (仅 PASS 路径) ---
        if sm.state == "CRM_MEM":
            sm.transition("DONE", reason="golden path complete")
        ctx.state = sm.state

        audit.log("final_state", {"state": sm.state, "status": status})
        audit_path = audit.save()
        ctx.events.append({"event": "audit_saved", "path": audit_path})
        self.ctx_engine.persist(ctx)

        # --- P2 可观测: 收口 root span 并导出 trace ---
        root.set(final_state=sm.state, status=status)
        root.end = time.time(); root.status = "OK"
        tracer._pop(root)
        trace_doc = tracer.export()

        return {
            "context_id": ctx.context_id,
            "state": sm.state,
            "verification_status": status,
            "next_action": verification["next_action"],
            "reasons": verification["reasons"],
            "dfm": {"valid": dfm.get("valid"),
                    "conflicts": [c.get("message") for c in dfm.get("conflicts", [])],
                    "source": dfm.get("_source")},
            "quote": {k: quote.get(k) for k in
                      ("unit_price", "final_price", "total_price", "profit",
                       "lead_time_days", "_source")} if quote else {},
            "margin_pct": ctx.commercial.get("margin_pct"),
            "commercial": {
                "incoterm": ctx.commercial.get("incoterm"),
                "landed_cost": ctx.commercial.get("landed_cost"),
                "seller_quote_price": ctx.commercial.get("seller_quote_price"),
                "total_lead_time_days": ctx.commercial.get("total_lead_time_days"),
                "breakdown": (ctx.commercial.get("freight_customs") or {}).get("breakdown"),
                "region": (ctx.commercial.get("freight_customs") or {}).get("region"),
                "shipping_mode": (ctx.commercial.get("freight_customs") or {}).get("shipping_mode"),
                "chargeable_kg": ((ctx.commercial.get("freight_customs") or {}).get("weight") or {}).get("chargeable_kg"),
            } if ctx.commercial.get("freight_customs") else None,
            "customer_memory": {"is_new": ctx.customer.get("is_new"),
                                "signals": [s.get("type") for s in ctx.risk.get("customer_signals", [])]},
            "multimodal_conflicts": [c["type"] for c in mm_conflicts],
            "reply": {"subject": reply.get("subject"), "auto_send": reply.get("auto_send"),
                      "mode": reply.get("mode"),
                      "guardrail_output": reply.get("guardrail_output")},
            "engine_source": self.timo.source_label(),
            "rag_source": rag.get("_source"),
            "quote_anchor": quote_anchor,
            "audit_valid": audit.verify(),
            "audit_head": audit.head,
            "audit_path": audit_path,
            "guardrails": {"input": {"pass": in_guard["pass"],
                                     "flags": [f.get("type") for f in in_guard["flags"]]},
                           "output": reply.get("guardrail_output"),
                           "escalated": guard_escalate},
            "llm_planner": llm_info,
            "schema": ctx.risk.get("schema"),
            "observability": {"trace_id": tracer.trace_id,
                              "span_count": len(tracer.spans),
                              "metrics": tracer.metrics,
                              "export_path": trace_doc.get("export_path"),
                              "correlation": tracer.correlation()},
            "state_history": sm.history,
            "flywheel": flywheel_result,  # v6.1 飞轮层 (T6.9)
            "driver": driver or "email",  # P0 标记 (方案 D): 驱动来源透传到 return
        }
