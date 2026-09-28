"""skill_dispatcher.py — v3.0.0 NemoClaw 混合架构的 Skill 调度器.

职责:
  1. 接收自然语言 intent + files + 可选 args
  2. 意图 → Skill 序列 (LLM 优先, 规则兜底 / 可强制 rules_only)
  3. OpenShell 门禁: 白名单 / 路径沙箱 / 铁律①锁定 / HITL
  4. 顺序执行, 返回 trace + result + hitl_required + violations

铁律:
  - LLM 只决定调用哪些 Skill, 不决定 Skill 输出
  - iron-rule-1 不可关闭; 确定性输出 dispatch 后不可改写
  - 比赛现场 LLM 离线 → 规则路由, 不阻断
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services import skill_config as sc
from services.openshell import OpenShell, sha256_obj
from skills import _runtime as rt

_ROOT = Path(__file__).resolve().parent.parent
_AUDIT_PATH = _ROOT / "data" / "skill_audit.jsonl"

# 规则路由: (pattern, skill_sequence builder key)
_RULE_ROUTES: List[Tuple[str, List[str]]] = [
    (r"黄金链|golden\s*chain|端到端|全流程|e2e|完整报价", ["golden_chain"]),
    (r"反馈|feedback|bug|缺陷|建议", ["submit_feedback"]),
    (r"缩略图|thumbnail|3d|三维|预览|svg", ["render_thumbnail"]),
    (r"供应商|supplier|外协|分派|工厂", ["supplier_match"]),
    (r"报价|quote|价格|price|cost|多少钱",
     ["parse_rfq", "extract_specs", "check_dfm", "calc_quote", "verify_gate", "write_reply"]),
    (r"dfm|冲突|工艺|可行性|conflict", ["parse_rfq", "check_dfm", "verify_gate"]),
    (r"回复|reply|邮件草稿|draft", ["parse_rfq", "write_reply"]),
    (r"验证|verify|审核|验收|hitl", ["parse_rfq", "verify_gate"]),
    (r"询盘|rfq|解析|extract|parse", ["parse_rfq", "extract_specs"]),
]

_DEFAULT_QUOTE_SEQ = ["parse_rfq", "extract_specs", "check_dfm", "calc_quote",
                      "verify_gate", "write_reply"]


def _infer_file_skills(files: Optional[List[str]]) -> List[str]:
    extra: List[str] = []
    for f in files or []:
        low = str(f).lower()
        if low.endswith((".step", ".stp")):
            if "render_thumbnail" not in extra:
                extra.append("render_thumbnail")
    return extra


def rule_route(intent: str, files: Optional[List[str]] = None) -> Dict[str, Any]:
    text = (intent or "").lower()
    seq: List[str] = []
    matched_rule = ""
    for pat, skills in _RULE_ROUTES:
        if re.search(pat, text, re.I):
            seq = list(skills)
            matched_rule = pat
            break
    if not seq:
        # 默认: 有 STEP → 带分析的报价链; 否则 golden chain 轻量前缀
        seq = list(_DEFAULT_QUOTE_SEQ)
        matched_rule = "default_quote_chain"
    for s in _infer_file_skills(files):
        if s not in seq:
            seq.append(s)
    return {"skills": seq, "source": "rules", "matched_rule": matched_rule}


def llm_route(intent: str, files: Optional[List[str]] = None,
              planner: Any = None) -> Dict[str, Any]:
    """LLM 意图分类 → skill 序列。失败时返回 ok=False 交给规则兜底."""
    if planner is None or not getattr(planner, "online", lambda: False)():
        return {"ok": False, "reason": "llm_offline", "skills": []}
    catalog = [
        "parse_rfq", "extract_specs", "check_dfm", "calc_quote",
        "verify_gate", "write_reply", "submit_feedback", "render_thumbnail",
        "supplier_match", "golden_chain",
    ]
    prompt = (
        "You are a skill router for a manufacturing export agent. "
        "Choose an ordered list of skills to handle the user intent. "
        f"Allowed skills: {catalog}. "
        "Return JSON only: {\"skills\": [\"skill_id\", ...], \"thought\": \"...\"}. "
        "Do not invent skills. Prefer golden_chain for full RFQ quote flows.\n"
        f"Intent: {intent}\nFiles: {files or []}"
    )
    try:
        # 复用 planner 的 chat_json 机制需要模板; 直接用底层
        if hasattr(planner, "_post_chat"):
            payload = {
                "model": planner.model,
                "messages": [
                    {"role": "system", "content": "You output strict JSON for skill routing."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
                "max_tokens": 400,
                "response_format": {"type": "text"},
            }
            raw = planner._post_chat(payload)
            content = raw["choices"][0]["message"]["content"]
        else:
            return {"ok": False, "reason": "planner_no_chat", "skills": []}
        from services.llm_planner import _extract_json
        data = _extract_json(content)
        if not isinstance(data, dict) or not data.get("skills"):
            return {"ok": False, "reason": "parse_failed", "skills": [], "raw": content[:200]}
        skills = [str(s) for s in data["skills"] if str(s) in catalog]
        if not skills:
            return {"ok": False, "reason": "empty_skills", "skills": []}
        return {"ok": True, "skills": skills, "source": "llm",
                "thought": data.get("thought", ""), "model": planner.model}
    except Exception as e:  # noqa
        return {"ok": False, "reason": repr(e), "skills": []}


class SkillDispatcher:
    def __init__(self, cfg: Optional[Dict[str, Any]] = None, ctrl: Any = None,
                 planner: Any = None, openshell: Optional[OpenShell] = None):
        self.cfg = cfg if cfg is not None else sc.load()
        self._ctrl = ctrl
        self._planner = planner
        self.shell = openshell or OpenShell(cfg=self.cfg)
        rt.discover(force=True)
        self._audit: List[Dict[str, Any]] = []

    def _ensure_ctrl(self):
        if self._ctrl is None:
            from bootstrap import build_controller
            self._ctrl = build_controller()
        return self._ctrl

    def _ensure_planner(self):
        if self._planner is not None:
            return self._planner
        try:
            ctrl = self._ensure_ctrl()
            self._planner = getattr(ctrl, "planner", None)
        except Exception:
            self._planner = None
        return self._planner

    def route(self, intent: str, files: Optional[List[str]] = None) -> Dict[str, Any]:
        strategy = sc.dispatcher_strategy(self.cfg)
        disp = self.cfg.get("dispatcher") or {}
        if strategy == "rules_only":
            r = rule_route(intent, files)
            r["strategy"] = "rules_only"
            return r
        if strategy == "llm":
            planner = self._ensure_planner()
            r = llm_route(intent, files, planner)
            r["strategy"] = "llm"
            if not r.get("ok"):
                if disp.get("fallback_rules", True):
                    fb = rule_route(intent, files)
                    fb["strategy"] = "llm→rules_fallback"
                    fb["llm_error"] = r.get("reason")
                    return fb
                return r
            return r
        # auto
        planner = self._ensure_planner()
        r = llm_route(intent, files, planner)
        if r.get("ok"):
            r["strategy"] = "auto:llm"
            return r
        fb = rule_route(intent, files)
        fb["strategy"] = "auto:rules"
        fb["llm_error"] = r.get("reason")
        return fb

    def _skill_meta(self, skill_id: str) -> Dict[str, Any]:
        meta = (self.cfg.get("skills") or {}).get(skill_id) or {}
        return {
            "iron_rule": meta.get("iron_rule", ""),
            "label": meta.get("label", skill_id),
        }

    def _build_args(self, skill_id: str, task_args: Dict[str, Any],
                    ctx: rt.SkillContext) -> Dict[str, Any]:
        """按 skill 提取参数; 从 task_args + ctx.scratch 取."""
        files = task_args.get("files") or []
        step_path = ""
        for f in files:
            if str(f).lower().endswith((".step", ".stp")):
                step_path = str(f)
                break
        # v6.1.0 修复: 显式 email_text 优先于 intent (intent 是路由指令, 不是邮件正文;
        # 仅当调用方未传 email_text 时才把 intent 当正文兜底 — UI 聊天直发场景)
        body = task_args.get("email_text") or task_args.get("intent") or ""
        common = {
            "email_text": body,
            "text": body,
            "customer": task_args.get("customer"),
            "rfq": task_args.get("rfq") or ctx.scratch.get("rfq"),
            "use_llm": bool(task_args.get("use_llm", False)),
        }
        if skill_id == "parse_rfq":
            return {k: common[k] for k in ("email_text", "text", "customer") if common[k] is not None}
        if skill_id == "extract_specs":
            return {"email_text": common["email_text"], "rfq": common["rfq"]}
        if skill_id == "check_dfm":
            a = {"rfq": common["rfq"]}
            for k in ("material", "surface", "process", "tolerance_grade"):
                if task_args.get(k):
                    a[k] = task_args[k]
            return a
        if skill_id == "calc_quote":
            a: Dict[str, Any] = {"rfq": common["rfq"]}
            for k in ("material", "quantity", "surface", "weight_kg", "max_dim_mm",
                      "tolerance_grade", "step_facts"):
                if task_args.get(k) is not None:
                    a[k] = task_args[k]
            return a
        if skill_id == "verify_gate":
            return {"ctx_dict": task_args.get("ctx_dict")}
        if skill_id == "write_reply":
            return {"use_llm": common["use_llm"]}
        if skill_id == "submit_feedback":
            return {k: task_args[k] for k in
                    ("type", "title", "body", "email", "honeypot", "source")
                    if k in task_args}
        if skill_id == "render_thumbnail":
            return {"path": step_path or task_args.get("path") or task_args.get("file") or ""}
        if skill_id == "supplier_match":
            return {"rfq": common["rfq"], "top_n": task_args.get("top_n", 3)}
        if skill_id == "golden_chain":
            return {
                "email_text": common["email_text"],
                "customer": common["customer"],
                "use_llm": common["use_llm"],
                "destination_country": task_args.get("destination_country") or "",
                "shipping_mode": task_args.get("shipping_mode") or "",
                "incoterm": task_args.get("incoterm") or "",
                "voice_transcript": task_args.get("voice_transcript") or "",
            }
        return dict(task_args)

    def dispatch(self, intent: str = "", files: Optional[List[str]] = None,
                 context_id: Optional[str] = None,
                 skills: Optional[List[str]] = None,
                 args: Optional[Dict[str, Any]] = None,
                 driver: str = "console") -> Dict[str, Any]:
        t0 = time.time()
        dispatch_id = f"disp_{uuid.uuid4().hex[:12]}"
        task_args = dict(args or {})
        if intent:
            task_args.setdefault("intent", intent)
        if files:
            task_args.setdefault("files", list(files))
        route_info = self.route(intent, files) if skills is None else {
            "skills": list(skills), "source": "explicit", "strategy": "explicit"}
        planned = [s for s in (route_info.get("skills") or [])]
        max_n = int((self.cfg.get("dispatcher") or {}).get("max_skills_per_task", 8) or 8)
        planned = planned[:max_n]

        # filter disabled + allowlist
        allowed_seq: List[str] = []
        skipped: List[Dict[str, Any]] = []
        for sid in planned:
            viols = self.shell.precheck(sid, task_args)
            if viols:
                skipped.append({"skill": sid, "violations": viols})
                continue
            if not sc.skill_enabled(self.cfg, sid):
                skipped.append({"skill": sid, "violations": [{"reason": "disabled in skills.yaml"}]})
                continue
            allowed_seq.append(sid)

        ctx = rt.SkillContext(
            ctrl=self._ctrl, planner=self._planner,
            policy=(self._ctrl.policy if self._ctrl is not None else {}) or {},
            dispatch_id=dispatch_id,
            skill_cfg=self.cfg,
        )
        if context_id:
            ctx.scratch["context_id"] = context_id

        trace: List[Dict[str, Any]] = []
        hitl_required = False
        hitl_reasons: List[Dict[str, Any]] = []
        result: Dict[str, Any] = {}
        last_output: Dict[str, Any] = {}

        for sid in allowed_seq:
            meta = self._skill_meta(sid)
            call_args = self._build_args(sid, task_args, ctx)
            # 再次 precheck with concrete args (路径)
            viols = self.shell.precheck(sid, call_args)
            if viols:
                trace.append({"skill": sid, "ok": False, "skipped": True,
                              "violations": viols, "ts": time.time()})
                continue
            out = rt.execute(sid, call_args, ctx)
            iron = out.get("iron_rule") or meta.get("iron_rule") or ""
            post = self.shell.postcheck(sid, out, iron_rule=iron, args=call_args)
            # 铁律①: 若 violation 且是确定性改写 → 拒绝采用该输出
            if not post.get("ok") and post.get("violations"):
                trace.append({
                    "skill": sid, "ok": False, "error": "openshell_violation",
                    "violations": post.get("violations"), "ts": time.time(),
                    "iron_rule": iron,
                })
                continue
            if post.get("hitl_required"):
                hitl_required = True
                hitl_reasons.extend(post.get("hitl_reasons") or [])
            if out.get("hitl_required"):
                hitl_required = True
            # quote amount gate
            if sid == "calc_quote" and (out.get("amount_gate_unit") or out.get("amount_gate_total")):
                hitl_required = True
                hitl_reasons.append({"policy": "amount_gate", "skill": sid,
                                     "unit": out.get("amount_gate_unit"),
                                     "total": out.get("amount_gate_total")})
            entry = {
                "skill": sid,
                "label": meta.get("label"),
                "ok": bool(out.get("ok")),
                "iron_rule": iron,
                "iron_rule_applied": bool(post.get("iron_locked")),
                "output_sha256": post.get("output_sha256"),
                "input": {k: v for k, v in call_args.items()
                          if k not in ("email_text", "text", "body") or True},
                "output": out,
                "ts": time.time(),
                "_latency_ms": out.get("_latency_ms"),
            }
            # 精简 trace 中的超大字段
            if isinstance(entry["output"], dict) and "svg" in entry["output"] and len(str(entry["output"].get("svg") or "")) > 2000:
                entry["output"] = dict(entry["output"])
                entry["output"]["svg"] = f"<svg truncated {len(str(out.get('svg')))} chars>"
            if isinstance(entry["input"], dict):
                for k, v in list(entry["input"].items()):
                    if isinstance(v, str) and len(v) > 500:
                        entry["input"][k] = v[:500] + "…"
            trace.append(entry)
            last_output = out
            result = out
            self._audit_append(entry)

        # 模拟 LLM 试图改写确定性输出 (审计演示, 不改变 result)
        override_attempt = None
        if self.shell.locks:
            any_sid = next(iter(self.shell.locks))
            tampered = dict(last_output) if isinstance(last_output, dict) else {"tampered": True}
            if isinstance(tampered, dict):
                tampered = dict(tampered)
                tampered["_llm_override"] = True
                if "unit_price" in tampered:
                    try:
                        tampered["unit_price"] = float(tampered["unit_price"]) * 2
                    except (TypeError, ValueError):
                        pass
                override_attempt = {
                    "skill": any_sid,
                    **self.shell.attempt_override(any_sid, tampered),
                }

        # MEDIA 富输出协议 (workshop 复刻): skill 输出 media 列表聚合 + MEDIA: 行
        media: List[Dict[str, Any]] = []
        for t in trace:
            out = t.get("output") or {}
            for m in (out.get("media") or []):
                if isinstance(m, dict) and m.get("path"):
                    media.append(m)
        media_lines = [f"MEDIA:{m['path']}" for m in media if m.get("path")]

        resp = {
            "dispatch_id": dispatch_id,
            "context_id": context_id or ctx.scratch.get("context_id"),
            "route": route_info,
            "planned_skills": planned,
            "executed_skills": [t["skill"] for t in trace if t.get("ok")],
            "skipped": skipped,
            "trace": trace,
            "result": result,
            "hitl_required": hitl_required,
            "hitl_reasons": hitl_reasons,
            "openshell_violations": list(self.shell.violations),
            "openshell": self.shell.status(),
            "iron_rule_override_blocked": override_attempt,
            "latency_ms": round((time.time() - t0) * 1000, 1),
            "strategy": route_info.get("strategy"),
            "driver": driver or "console",
            "media": media,
            "media_lines": media_lines,
        }
        self._write_audit(resp)
        return resp

    def _audit_append(self, entry: Dict[str, Any]) -> None:
        max_n = int((self.cfg.get("dispatcher") or {}).get("audit_max", 50) or 50)
        self._audit.append({
            "skill": entry.get("skill"),
            "ok": entry.get("ok"),
            "ts": entry.get("ts"),
            "iron_rule": entry.get("iron_rule"),
            "output_sha256": entry.get("output_sha256"),
        })
        if len(self._audit) > max_n:
            self._audit = self._audit[-max_n:]

    def _write_audit(self, resp: Dict[str, Any]) -> None:
        try:
            _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
            line = {
                "dispatch_id": resp.get("dispatch_id"),
                "ts": time.time(),
                "skills": resp.get("executed_skills"),
                "hitl_required": resp.get("hitl_required"),
                "violations": len(resp.get("openshell_violations") or []),
                "strategy": resp.get("strategy"),
                "driver": resp.get("driver") or "console",
            }
            with _AUDIT_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def recent_audit(self, limit: int = 20) -> List[Dict[str, Any]]:
        items = list(self._audit[-limit:])
        # 也读磁盘
        if _AUDIT_PATH.exists():
            try:
                lines = _AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
                disk = [json.loads(l) for l in lines if l.strip()]
                return disk[-limit:] or items
            except Exception:
                return items
        return items


# 进程内单例 (API 屁)
_DISPATCHER: Optional[SkillDispatcher] = None


def get_dispatcher(reset: bool = False) -> SkillDispatcher:
    global _DISPATCHER
    if _DISPATCHER is None or reset:
        _DISPATCHER = SkillDispatcher(cfg=sc.load())
    return _DISPATCHER


def reset_dispatcher() -> None:
    global _DISPATCHER
    _DISPATCHER = None
