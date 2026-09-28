"""crm_memory.py — L5 Memory Fabric: Fact(SQLite) + Episodic(事件) + CRM 同步.

对齐 PRD 第 7/12 节:
  Fact     : customers / rfqs / quotes / orders (SQLite)
  Episodic : agent_runs / tool_calls / HITL trace (审计链已覆盖, 此处摘要落库)
  Semantic : 通过 funasr RAG 检索历史案例 (见 services/rag.py)
CRM 同步 = 写业务事实 + memory 引用, 不做外部发送。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS customers(
  customer_id TEXT PRIMARY KEY, name TEXT, contact_name TEXT, email TEXT,
  country TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS rfqs(
  context_id TEXT PRIMARY KEY, customer_id TEXT, material TEXT, surface TEXT,
  quantity INTEGER, tolerance TEXT, state TEXT, created_at REAL, payload TEXT);
CREATE TABLE IF NOT EXISTS quotes(
  context_id TEXT PRIMARY KEY, unit_price REAL, final_price REAL, currency TEXT,
  lead_time_days INTEGER, margin_pct REAL, source TEXT, verification_status TEXT,
  reply_subject TEXT, auto_send INTEGER, created_at REAL);
CREATE TABLE IF NOT EXISTS postmortems(
  id INTEGER PRIMARY KEY AUTOINCREMENT, context_id TEXT, outcome TEXT,
  actual_cost REAL, note TEXT, created_at REAL);

-- ===== v6.1 飞轮层 5 张新表 (T6.1) =====
CREATE TABLE IF NOT EXISTS customer_health(
  customer_id TEXT PRIMARY KEY,
  health_score REAL DEFAULT 50.0,
  churn_risk TEXT DEFAULT 'unknown',
  total_quotes INTEGER DEFAULT 0,
  won_quotes INTEGER DEFAULT 0,
  lost_quotes INTEGER DEFAULT 0,
  avg_margin_pct REAL,
  avg_response_days REAL,
  last_contact_at REAL,
  breakdown_json TEXT,
  computed_at REAL
);
CREATE TABLE IF NOT EXISTS follow_ups(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id TEXT, context_id TEXT,
  scheduled_at REAL, sent_at REAL,
  channel TEXT, intent TEXT, condition TEXT,
  status TEXT DEFAULT 'pending',
  response_text TEXT,
  nlg_variant TEXT,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS quote_calibration(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  context_id TEXT, customer_id TEXT,
  material TEXT, surface TEXT, quantity INTEGER,
  quoted_unit_price REAL, actual_unit_cost REAL,
  deviation_pct REAL,
  outcome TEXT,
  calibration_action TEXT,
  confidence REAL DEFAULT 0.5,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS preference_profile(
  customer_id TEXT PRIMARY KEY,
  tolerance_bias TEXT DEFAULT 'standard',
  material_preference TEXT,
  surface_preference TEXT,
  quantity_avg REAL, quantity_std REAL,
  decision_speed_days REAL DEFAULT 7.0,
  price_sensitivity TEXT DEFAULT 'med',
  preferred_incoterms TEXT,
  communication_style TEXT DEFAULT 'formal',
  risk_signals TEXT,
  sample_count INTEGER DEFAULT 0,
  updated_at REAL
);
CREATE TABLE IF NOT EXISTS sandbox_quotes(
  customer_id TEXT, context_id TEXT, quote_id INTEGER,
  quoted_at REAL, material TEXT, surface TEXT,
  unit_price REAL, outcome TEXT,
  ingested_to_rag INTEGER DEFAULT 0,
  PRIMARY KEY (customer_id, context_id)
);

-- ===== T13 飞轮基础设施: 校准聚合 + 互动记录 =====
CREATE TABLE IF NOT EXISTS calibrations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id TEXT, avg_bias REAL, bias_trend REAL,
  adjusted_margin REAL, sample_count INTEGER, created_at REAL
);
CREATE TABLE IF NOT EXISTS interactions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id TEXT, channel TEXT,
  summary TEXT, context_id TEXT, created_at REAL
);
"""

# T13 迁移: customers 表生命周期字段 + follow_ups 表生命周期跟进列
_CUSTOMERS_MIGRATION_COLS = [
    ("lifecycle_state", "TEXT DEFAULT 'NEW'"),
    ("last_interaction_at", "REAL"),
    ("last_order_at", "REAL"),
    ("total_orders", "INTEGER DEFAULT 0"),
    ("total_revenue", "REAL DEFAULT 0"),
    ("health_score", "REAL DEFAULT 1.0"),
]

_FOLLOWUPS_MIGRATION_COLS = [
    ("task_type", "TEXT"),
    ("reason", "TEXT"),
    ("due_at", "REAL"),
]


class CRMMemory:
    def __init__(self, db_path: str = "data/crm.sqlite3"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: FastAPI 在线程池跑同步端点, 需跨线程复用同一连接
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # T13: 增量迁移 (ALTER TABLE ADD COLUMN, 幂等)
        self._migrate_columns("customers", _CUSTOMERS_MIGRATION_COLS)
        self._migrate_columns("follow_ups", _FOLLOWUPS_MIGRATION_COLS)

    def _migrate_columns(self, table: str, cols: list) -> None:
        """幂等 ALTER TABLE ADD COLUMN: 已存在的列跳过 (SQLite 对已存在列会报错)."""
        existing = {row[1] for row in
                    self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col_name, col_def in cols:
            if col_name not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
        self._conn.commit()

    def upsert_customer(self, customer: Dict[str, Any]) -> str:
        import hashlib
        seed = customer.get("name", "") or customer.get("email", "") or "anon"
        cid = customer.get("customer_id") or f"CUST-{hashlib.md5(seed.encode('utf-8')).hexdigest()[:6].upper()}"
        self._conn.execute(
            "INSERT INTO customers(customer_id,name,contact_name,email,country,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(customer_id) DO UPDATE SET "
            "name=excluded.name, contact_name=excluded.contact_name, email=excluded.email,"
            "country=excluded.country, updated_at=excluded.updated_at",
            (cid, customer.get("name"), customer.get("contact_name"),
             customer.get("email"), customer.get("country"), time.time()))
        self._conn.commit()
        return cid

    def write_rfq(self, ctx_dict: Dict[str, Any]) -> None:
        rfq = ctx_dict.get("rfq", {})
        self._conn.execute(
            "INSERT INTO rfqs(context_id,customer_id,material,surface,quantity,tolerance,state,created_at,payload) "
            "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(context_id) DO UPDATE SET "
            "state=excluded.state, payload=excluded.payload",
            (ctx_dict.get("context_id"), rfq.get("customer", {}).get("customer_id"),
             rfq.get("material"), rfq.get("surface"), rfq.get("quantity"),
             rfq.get("tolerance_grade"), ctx_dict.get("state"), time.time(),
             json.dumps(rfq, ensure_ascii=False, default=str)))
        self._conn.commit()

    def write_quote(self, ctx_dict: Dict[str, Any], verification: Dict[str, Any],
                    reply: Dict[str, Any]) -> None:
        com = ctx_dict.get("commercial", {})
        q = com.get("quote", com)
        self._conn.execute(
            "INSERT INTO quotes(context_id,unit_price,final_price,currency,lead_time_days,"
            "margin_pct,source,verification_status,reply_subject,auto_send,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(context_id) DO UPDATE SET "
            "unit_price=excluded.unit_price, final_price=excluded.final_price,"
            "verification_status=excluded.verification_status, reply_subject=excluded.reply_subject",
            (ctx_dict.get("context_id"), q.get("unit_price"),
             q.get("final_price") or q.get("total_price"), q.get("currency", "CNY"),
             q.get("lead_time_days"), com.get("margin_pct"), q.get("_source"),
             verification.get("status"), reply.get("subject"),
             1 if reply.get("auto_send") else 0, time.time()))
        self._conn.commit()

    def postmortem(self, context_id: str, outcome: str, actual_cost: Optional[float] = None,
                   note: str = "") -> None:
        self._conn.execute(
            "INSERT INTO postmortems(context_id,outcome,actual_cost,note,created_at) VALUES(?,?,?,?,?)",
            (context_id, outcome, actual_cost, note, time.time()))
        self._conn.commit()

    def stats(self) -> Dict[str, int]:
        out = {}
        for t in ("customers", "rfqs", "quotes", "postmortems"):
            out[t] = self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return out

    # ---------------- 查询 (客户记忆召回 / 闭环复盘) ----------------
    def get_quote(self, context_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT context_id,unit_price,final_price,currency,lead_time_days,margin_pct,"
            "source,verification_status FROM quotes WHERE context_id=?", (context_id,)).fetchone()
        if not row:
            return None
        cols = ["context_id", "unit_price", "final_price", "currency", "lead_time_days",
                "margin_pct", "source", "verification_status"]
        return dict(zip(cols, row))

    def customer_id_by_name(self, name: str) -> Optional[str]:
        if not name:
            return None
        row = self._conn.execute(
            "SELECT customer_id FROM customers WHERE name=? ORDER BY updated_at DESC LIMIT 1",
            (name,)).fetchone()
        return row[0] if row else None

    def list_customer_history(self, customer_id: str, limit: int = 20) -> Dict[str, Any]:
        """客户历史: 过往 RFQ/报价 + 复盘 (Fact memory 召回)."""
        if not customer_id:
            return {"quotes": [], "postmortems": [], "n": 0}
        quotes = [dict(zip(["context_id", "unit_price", "final_price", "margin_pct",
                            "verification_status", "created_at"], r))
                  for r in self._conn.execute(
                      "SELECT q.context_id,q.unit_price,q.final_price,q.margin_pct,"
                      "q.verification_status,q.created_at FROM quotes q "
                      "JOIN rfqs r ON r.context_id=q.context_id "
                      "WHERE r.customer_id=? ORDER BY q.created_at DESC LIMIT ?",
                      (customer_id, limit)).fetchall()]
        pms = [dict(zip(["context_id", "outcome", "actual_cost", "note", "created_at"], r))
               for r in self._conn.execute(
                   "SELECT p.context_id,p.outcome,p.actual_cost,p.note,p.created_at "
                   "FROM postmortems p JOIN rfqs r ON r.context_id=p.context_id "
                   "WHERE r.customer_id=? ORDER BY p.created_at DESC LIMIT ?",
                   (customer_id, limit)).fetchall()]
        return {"quotes": quotes, "postmortems": pms, "n": len(quotes)}

    def iter_quote_docs(self) -> list:
        """quotes×rfqs 联合行 (供 rag_layers 向量回填; 只读, 不带向量库依赖)."""
        rows = self._conn.execute(
            "SELECT r.customer_id,q.context_id,r.material,r.surface,r.tolerance,"
            "q.unit_price,q.margin_pct,q.created_at FROM quotes q "
            "JOIN rfqs r ON r.context_id=q.context_id ORDER BY q.created_at").fetchall()
        cols = ["customer_id", "context_id", "material", "surface", "tolerance",
                "unit_price", "margin_pct", "created_at"]
        return [dict(zip(cols, row)) for row in rows]

    def pending_for(self, customer_id: Optional[str] = None, limit: int = 20) -> list:
        """未办 RFQ 查询: state NOT IN ('DONE','BLOCKED') ORDER BY created_at DESC.

        可选按 customer_id 过滤 (邮件台侧栏 B-4 用).
        返回 [{context_id,customer_id,state,created_at}, ...]
        """
        sql = ("SELECT context_id,customer_id,state,created_at FROM rfqs "
               "WHERE state NOT IN ('DONE','BLOCKED')")
        args: list = []
        if customer_id:
            sql += " AND customer_id=?"
            args.append(customer_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(int(limit))
        cols = ["context_id", "customer_id", "state", "created_at"]
        return [dict(zip(cols, r)) for r in self._conn.execute(sql, args).fetchall()]

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    # ============= v6.1 飞轮层 5 表 CRUD (T6.1) =============

    # ---- customer_health ----
    def upsert_health(self, customer_id: str, score: float, churn_risk: str,
                      total_quotes: int, won: int, lost: int,
                      avg_margin: Optional[float] = None,
                      avg_response_days: Optional[float] = None,
                      last_contact_at: Optional[float] = None,
                      breakdown: Optional[Dict[str, Any]] = None) -> None:
        import json
        self._conn.execute(
            "INSERT INTO customer_health(customer_id,health_score,churn_risk,"
            "total_quotes,won_quotes,lost_quotes,avg_margin_pct,avg_response_days,"
            "last_contact_at,breakdown_json,computed_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(customer_id) DO UPDATE SET "
            "health_score=excluded.health_score, churn_risk=excluded.churn_risk,"
            "total_quotes=excluded.total_quotes, won_quotes=excluded.won_quotes,"
            "lost_quotes=excluded.lost_quotes, avg_margin_pct=excluded.avg_margin_pct,"
            "avg_response_days=excluded.avg_response_days,"
            "last_contact_at=excluded.last_contact_at,"
            "breakdown_json=excluded.breakdown_json, computed_at=excluded.computed_at",
            (customer_id, score, churn_risk, total_quotes, won, lost,
             avg_margin, avg_response_days, last_contact_at,
             json.dumps(breakdown or {}, ensure_ascii=False), time.time()))
        self._conn.commit()

    def get_health(self, customer_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT customer_id,health_score,churn_risk,total_quotes,won_quotes,"
            "lost_quotes,avg_margin_pct,avg_response_days,last_contact_at,computed_at "
            "FROM customer_health WHERE customer_id=?", (customer_id,)).fetchone()
        if not row:
            return None
        cols = ["customer_id", "health_score", "churn_risk", "total_quotes",
                "won_quotes", "lost_quotes", "avg_margin_pct", "avg_response_days",
                "last_contact_at", "computed_at"]
        return dict(zip(cols, row))

    # ---- follow_ups ----
    def add_followup(self, customer_id: str, context_id: str,
                     scheduled_at: float, channel: str, intent: str,
                     condition: str = "no_response",
                     nlg_variant: str = "default") -> int:
        cur = self._conn.execute(
            "INSERT INTO follow_ups(customer_id,context_id,scheduled_at,channel,"
            "intent,condition,status,nlg_variant,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (customer_id, context_id, scheduled_at, channel, intent,
             condition, "pending", nlg_variant, time.time()))
        self._conn.commit()
        return int(cur.lastrowid)

    def list_pending_followups(self, customer_id: Optional[str] = None,
                               limit: int = 20) -> list:
        sql = "SELECT id,customer_id,context_id,scheduled_at,channel,intent," \
              "condition,status,nlg_variant FROM follow_ups WHERE status='pending'"
        args: list = []
        if customer_id:
            sql += " AND customer_id=?"
            args.append(customer_id)
        sql += " ORDER BY scheduled_at ASC LIMIT ?"
        args.append(limit)
        cols = ["id", "customer_id", "context_id", "scheduled_at", "channel",
                "intent", "condition", "status", "nlg_variant"]
        return [dict(zip(cols, r)) for r in self._conn.execute(sql, args).fetchall()]

    def mark_followup_sent(self, followup_id: int, response_text: str = "") -> None:
        self._conn.execute(
            "UPDATE follow_ups SET sent_at=?, status=?, response_text=? WHERE id=?",
            (time.time(), "sent", response_text, followup_id))
        self._conn.commit()

    def cancel_followups(self, context_id: str) -> int:
        cur = self._conn.execute(
            "UPDATE follow_ups SET status='cancelled' "
            "WHERE context_id=? AND status='pending'", (context_id,))
        self._conn.commit()
        return cur.rowcount

    # ---- quote_calibration ----
    def record_calibration(self, context_id: str, customer_id: str,
                           material: str, surface: str, quantity: int,
                           quoted_unit_price: float, actual_unit_cost: Optional[float],
                           outcome: str,
                           calibration_action: str,
                           deviation_pct: Optional[float] = None,
                           confidence: float = 0.5) -> int:
        cur = self._conn.execute(
            "INSERT INTO quote_calibration(context_id,customer_id,material,surface,"
            "quantity,quoted_unit_price,actual_unit_cost,deviation_pct,outcome,"
            "calibration_action,confidence,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (context_id, customer_id, material, surface, quantity,
             quoted_unit_price, actual_unit_cost, deviation_pct, outcome,
             calibration_action, confidence, time.time()))
        self._conn.commit()
        return int(cur.lastrowid)

    def get_calibrations(self, customer_id: str, material: Optional[str] = None,
                         limit: int = 10) -> list:
        sql = "SELECT id,context_id,customer_id,material,surface,quantity," \
              "quoted_unit_price,actual_unit_cost,deviation_pct,outcome," \
              "calibration_action,confidence,created_at FROM quote_calibration " \
              "WHERE customer_id=?"
        args: list = [customer_id]
        if material:
            sql += " AND material=?"
            args.append(material)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        cols = ["id", "context_id", "customer_id", "material", "surface",
                "quantity", "quoted_unit_price", "actual_unit_cost",
                "deviation_pct", "outcome", "calibration_action",
                "confidence", "created_at"]
        return [dict(zip(cols, r)) for r in self._conn.execute(sql, args).fetchall()]

    # ---- preference_profile ----
    def upsert_profile(self, customer_id: str,
                       tolerance_bias: str = "standard",
                       material_preference: Optional[list] = None,
                       surface_preference: Optional[list] = None,
                       quantity_avg: Optional[float] = None,
                       quantity_std: Optional[float] = None,
                       decision_speed_days: float = 7.0,
                       price_sensitivity: str = "med",
                       preferred_incoterms: Optional[list] = None,
                       communication_style: str = "formal",
                       risk_signals: Optional[list] = None) -> None:
        import json
        self._conn.execute(
            "INSERT INTO preference_profile(customer_id,tolerance_bias,"
            "material_preference,surface_preference,quantity_avg,quantity_std,"
            "decision_speed_days,price_sensitivity,preferred_incoterms,"
            "communication_style,risk_signals,sample_count,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(customer_id) DO UPDATE SET "
            "tolerance_bias=excluded.tolerance_bias,"
            "material_preference=excluded.material_preference,"
            "surface_preference=excluded.surface_preference,"
            "quantity_avg=COALESCE(excluded.quantity_avg,preference_profile.quantity_avg),"
            "quantity_std=COALESCE(excluded.quantity_std,preference_profile.quantity_std),"
            "decision_speed_days=excluded.decision_speed_days,"
            "price_sensitivity=excluded.price_sensitivity,"
            "preferred_incoterms=excluded.preferred_incoterms,"
            "communication_style=excluded.communication_style,"
            "risk_signals=excluded.risk_signals,"
            "sample_count=preference_profile.sample_count+1,"
            "updated_at=excluded.updated_at",
            (customer_id, tolerance_bias,
             json.dumps(material_preference or [], ensure_ascii=False),
             json.dumps(surface_preference or [], ensure_ascii=False),
             quantity_avg, quantity_std,
             decision_speed_days, price_sensitivity,
             json.dumps(preferred_incoterms or [], ensure_ascii=False),
             communication_style,
             json.dumps(risk_signals or [], ensure_ascii=False),
             1, time.time()))
        self._conn.commit()

    def get_profile(self, customer_id: str) -> Optional[Dict[str, Any]]:
        import json
        row = self._conn.execute(
            "SELECT customer_id,tolerance_bias,material_preference,surface_preference,"
            "quantity_avg,quantity_std,decision_speed_days,price_sensitivity,"
            "preferred_incoterms,communication_style,risk_signals,sample_count,updated_at "
            "FROM preference_profile WHERE customer_id=?", (customer_id,)).fetchone()
        if not row:
            return None
        out = dict(zip(
            ["customer_id", "tolerance_bias", "material_preference",
             "surface_preference", "quantity_avg", "quantity_std",
             "decision_speed_days", "price_sensitivity", "preferred_incoterms",
             "communication_style", "risk_signals", "sample_count", "updated_at"],
            row))
        for k in ("material_preference", "surface_preference",
                  "preferred_incoterms", "risk_signals"):
            if out.get(k):
                try:
                    out[k] = json.loads(out[k])
                except Exception:
                    out[k] = []
            else:
                out[k] = []
        return out

    # ---- sandbox_quotes ----
    def add_sandbox_quote(self, customer_id: str, context_id: str,
                          material: str, surface: str,
                          unit_price: float, outcome: str = "",
                          ingested_to_rag: int = 0) -> None:
        self._conn.execute(
            "INSERT INTO sandbox_quotes(customer_id,context_id,quoted_at,material,"
            "surface,unit_price,outcome,ingested_to_rag) "
            "VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(customer_id,context_id) DO UPDATE SET "
            "unit_price=excluded.unit_price, outcome=excluded.outcome,"
            "ingested_to_rag=excluded.ingested_to_rag",
            (customer_id, context_id, time.time(), material, surface,
             unit_price, outcome, ingested_to_rag))
        self._conn.commit()

    def list_sandbox_quotes(self, customer_id: str, limit: int = 50) -> list:
        cols = ["customer_id", "context_id", "quoted_at", "material", "surface",
                "unit_price", "outcome", "ingested_to_rag"]
        return [dict(zip(cols, r)) for r in self._conn.execute(
            "SELECT customer_id,context_id,quoted_at,material,surface,unit_price,"
            "outcome,ingested_to_rag FROM sandbox_quotes WHERE customer_id=? "
            "ORDER BY quoted_at DESC LIMIT ?", (customer_id, limit)).fetchall()]

    def anonymize_customer(self, customer_id: str) -> None:
        """GDPR: 客户撤回 → 软删除 PII, 保留行为痕迹"""
        import hashlib
        anon_id = "ANON-" + hashlib.md5(customer_id.encode()).hexdigest()[:8].upper()
        self._conn.execute(
            "UPDATE customers SET name=?, contact_name=?, email=? "
            "WHERE customer_id=?",
            (anon_id, "REDACTED", "redacted@example.invalid", customer_id))
        # 沙箱与校准数据保留 (聚合统计用), 但 PII 已脱敏
        self._conn.commit()
    # ============= T13 飞轮基础设施: 生命周期/互动/校准/跟进 =============

    # ---- interactions ----
    def record_interaction(self, customer_id: str, channel: str,
                           summary: str, context_id: Optional[str] = None) -> int:
        """记录客户互动 (email/quote/order/reject), 同时更新 last_interaction_at."""
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO interactions(customer_id,channel,summary,context_id,created_at) "
            "VALUES(?,?,?,?,?)",
            (customer_id, channel, summary, context_id, now))
        self._conn.execute(
            "UPDATE customers SET last_interaction_at=?, updated_at=? WHERE customer_id=?",
            (now, now, customer_id))
        self._conn.commit()
        return int(cur.lastrowid)

    # ---- lifecycle ----
    def update_lifecycle(self, customer_id: str, new_state: str) -> None:
        """更新客户生命周期状态 (NEW/INQUIRING/QUOTED/NEGOTIATING/WON/REPEAT/DORMANT/CHURNED/WINBACK)."""
        self._conn.execute(
            "UPDATE customers SET lifecycle_state=?, updated_at=? WHERE customer_id=?",
            (new_state, time.time(), customer_id))
        self._conn.commit()

    def get_lifecycle_state(self, customer_id: str) -> str:
        """获取客户当前生命周期状态, 不存在则返回 'NEW'."""
        row = self._conn.execute(
            "SELECT lifecycle_state FROM customers WHERE customer_id=?",
            (customer_id,)).fetchone()
        return row[0] if row and row[0] else "NEW"

    def update_customer_health(self, customer_id: str, score: float) -> None:
        """更新客户健康分 (0-1 范围, 存 customers.health_score)."""
        self._conn.execute(
            "UPDATE customers SET health_score=?, updated_at=? WHERE customer_id=?",
            (score, time.time(), customer_id))
        self._conn.commit()

    def record_order(self, customer_id: str, revenue: float) -> None:
        """记录成交: total_orders+1, total_revenue+=revenue, last_order_at=now."""
        now = time.time()
        self._conn.execute(
            "UPDATE customers SET total_orders=total_orders+1, "
            "total_revenue=total_revenue+?, last_order_at=?, updated_at=? "
            "WHERE customer_id=?",
            (revenue, now, now, customer_id))
        self._conn.commit()

    # ---- follow_ups (生命周期跟进, 与 v6.1 报价跟进共存) ----
    def create_follow_up(self, customer_id: str, task_type: str,
                         reason: str, due_at: float) -> int:
        """创建生命周期跟进任务 (check_in/win_back/up_sell). status='PENDING' (大写区分)."""
        cur = self._conn.execute(
            "INSERT INTO follow_ups(customer_id,task_type,reason,due_at,status,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (customer_id, task_type, reason, due_at, "PENDING", time.time()))
        self._conn.commit()
        return int(cur.lastrowid)

    def list_follow_ups(self, status: str = "PENDING",
                        customer_id: Optional[str] = None,
                        limit: int = 50) -> list:
        """查询跟进任务 (默认查 PENDING). 返回 [{id,customer_id,task_type,reason,due_at,status,created_at}, ...]."""
        sql = ("SELECT id,customer_id,task_type,reason,due_at,status,created_at "
               "FROM follow_ups WHERE status=? AND task_type IS NOT NULL")
        args: list = [status]
        if customer_id:
            sql += " AND customer_id=?"
            args.append(customer_id)
        sql += " ORDER BY due_at ASC LIMIT ?"
        args.append(limit)
        cols = ["id", "customer_id", "task_type", "reason", "due_at", "status", "created_at"]
        return [dict(zip(cols, r)) for r in self._conn.execute(sql, args).fetchall()]

    def complete_follow_up(self, follow_up_id: int) -> None:
        """标记跟进任务为 DONE."""
        self._conn.execute(
            "UPDATE follow_ups SET status='DONE' WHERE id=?",
            (follow_up_id,))
        self._conn.commit()

    # ---- calibrations (聚合校准参数) ----
    def save_calibration(self, customer_id: str, avg_bias: float,
                         bias_trend: float, adjusted_margin: float,
                         sample_count: int) -> int:
        """保存一次校准结果 (聚合参数, 非 per-quote)."""
        cur = self._conn.execute(
            "INSERT INTO calibrations(customer_id,avg_bias,bias_trend,"
            "adjusted_margin,sample_count,created_at) VALUES(?,?,?,?,?,?)",
            (customer_id, avg_bias, bias_trend, adjusted_margin,
             sample_count, time.time()))
        self._conn.commit()
        return int(cur.lastrowid)

    def get_calibrations(self, customer_id: str, limit: int = 10) -> list:
        """查询客户校准历史 (T13 聚合校准表, 非 v6.1 quote_calibration).

        注意: 此方法覆盖了 v6.1 的同名方法 (签名不同). 
        v6.1 的 per-quote 校准用 record_calibration + _get_quote_calibrations.
        """
        cols = ["id", "customer_id", "avg_bias", "bias_trend",
                "adjusted_margin", "sample_count", "created_at"]
        return [dict(zip(cols, r)) for r in self._conn.execute(
            "SELECT id,customer_id,avg_bias,bias_trend,adjusted_margin,sample_count,created_at "
            "FROM calibrations WHERE customer_id=? ORDER BY created_at DESC LIMIT ?",
            (customer_id, limit)).fetchall()]

    def get_quote_calibrations(self, customer_id: str, material: Optional[str] = None,
                               limit: int = 10) -> list:
        """v6.1 per-quote 校准查询 (保留原 get_calibrations 语义, 避免破坏现有调用)."""
        sql = ("SELECT id,context_id,customer_id,material,surface,quantity,"
               "quoted_unit_price,actual_unit_cost,deviation_pct,outcome,"
               "calibration_action,confidence,created_at FROM quote_calibration "
               "WHERE customer_id=?")
        args: list = [customer_id]
        if material:
            sql += " AND material=?"
            args.append(material)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        cols = ["id", "context_id", "customer_id", "material", "surface",
                "quantity", "quoted_unit_price", "actual_unit_cost",
                "deviation_pct", "outcome", "calibration_action",
                "confidence", "created_at"]
        return [dict(zip(cols, r)) for r in self._conn.execute(sql, args).fetchall()]

    # ---- 客户完整画像 ----
    def get_customer_profile(self, customer_id: str) -> Optional[Dict[str, Any]]:
        """返回客户完整画像: 基础信息 + 生命周期 + 健康分 + 订单统计 + 最近互动 + 校准参数."""
        row = self._conn.execute(
            "SELECT customer_id,name,contact_name,email,country,updated_at,"
            "lifecycle_state,last_interaction_at,last_order_at,"
            "total_orders,total_revenue,health_score "
            "FROM customers WHERE customer_id=?", (customer_id,)).fetchone()
        if not row:
            return None
        profile = dict(zip(
            ["customer_id", "name", "contact_name", "email", "country", "updated_at",
             "lifecycle_state", "last_interaction_at", "last_order_at",
             "total_orders", "total_revenue", "health_score"], row))

        # 最近互动
        interactions = [dict(zip(["id", "channel", "summary", "context_id", "created_at"], r))
                        for r in self._conn.execute(
                            "SELECT id,channel,summary,context_id,created_at "
                            "FROM interactions WHERE customer_id=? "
                            "ORDER BY created_at DESC LIMIT 5", (customer_id,)).fetchall()]
        profile["recent_interactions"] = interactions

        # 最新校准参数
        cals = self.get_calibrations(customer_id, limit=1)
        profile["latest_calibration"] = cals[0] if cals else None

        # 待办跟进
        profile["pending_follow_ups"] = self.list_follow_ups(
            status="PENDING", customer_id=customer_id, limit=5)

        return profile

    def list_all_customer_ids(self) -> list:
        """列出所有客户 ID (生命周期巡检用)."""
        return [r[0] for r in self._conn.execute(
            "SELECT customer_id FROM customers").fetchall()]

    def get_customer_last_interaction_at(self, customer_id: str) -> Optional[float]:
        """获取客户最近互动时间 (last_interaction_at, 无则回退 updated_at)."""
        row = self._conn.execute(
            "SELECT last_interaction_at, updated_at FROM customers WHERE customer_id=?",
            (customer_id,)).fetchone()
        if not row:
            return None
        return row[0] if row[0] else row[1]
