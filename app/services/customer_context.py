"""customer_context.py — 跨询盘的客户级上下文聚合 (T14).

Context（per-RFQ）↔ CustomerContext（per-customer）联动:
  - 新询盘进来: inject_into(ctx) 注入客户级记忆
  - 询盘结束: update_after_rfq(ctx) 写回摘要

铁律:
  - 铁律①: 只注入参数/偏好, 不生成报价数字
  - 铁律④: RAG 只引证, 不改数字
  - 联动是单向注入 (客户级 → per-RFQ), 不反向污染
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from services.crm_memory import CRMMemory
    from services.customer_sandbox import CustomerSandbox
    from services.context_engine import Context


class CustomerContext:
    """跨询盘的客户级上下文聚合器."""

    def __init__(self, crm: "CRMMemory", sandbox: "CustomerSandbox"):
        self.crm = crm
        self.sandbox = sandbox

    # ---------- 加载客户级上下文 ----------

    def load(self, customer_id: str) -> Dict[str, Any]:
        """加载客户级上下文: 偏好/历史报价模式/跟进状态/校准参数.

        返回 dict:
          preferences: {material, surface, tolerance, quantity_mode}
          calibrations: 最新校准参数
          follow_ups: 待办跟进
          lifecycle_state: 生命周期状态
          health_score: 健康分
          sandbox_params: 沙箱报价参数
          sandbox_context: 沙箱跨询盘上下文
        """
        if not customer_id:
            return {"customer_id": "", "preferences": {}, "calibrations": [],
                    "follow_ups": [], "lifecycle_state": "NEW", "health_score": 1.0}

        # 1. 偏好
        preferences = self.extract_preferences(customer_id)

        # 2. 校准参数 (CRM calibrations 表)
        calibrations = self.crm.get_calibrations(customer_id, limit=3)

        # 3. 待办跟进
        follow_ups = self.crm.list_follow_ups(
            status="PENDING", customer_id=customer_id, limit=5)

        # 4. 客户画像 (生命周期 + 健康分)
        profile = self.crm.get_customer_profile(customer_id) or {}
        lifecycle_state = profile.get("lifecycle_state", "NEW")
        health_score = profile.get("health_score", 1.0)

        # 5. 沙箱参数 + 上下文
        sandbox_params = self.sandbox.get_params(customer_id)
        sandbox_context = self.sandbox.get_context(customer_id)

        return {
            "customer_id": customer_id,
            "preferences": preferences,
            "calibrations": calibrations,
            "follow_ups": follow_ups,
            "lifecycle_state": lifecycle_state,
            "health_score": health_score,
            "sandbox_params": sandbox_params,
            "sandbox_context": sandbox_context,
        }

    # ---------- 询盘结束后更新 ----------

    def update_after_rfq(self, customer_id: str, ctx: "Context") -> None:
        """询盘结束后更新客户级上下文摘要 (写回 sandbox context.json).

        摘要内容: 最近询盘的材料/表面/数量/报价/状态, 用于下次 inject_into.
        """
        if not customer_id:
            return

        # 加载现有上下文
        existing = self.sandbox.get_context(customer_id)

        # 追加本次询盘摘要
        rfq = getattr(ctx, "rfq", {}) or {}
        commercial = getattr(ctx, "commercial", {}) or {}
        quote = commercial.get("quote", commercial)

        recent_rfq = {
            "context_id": getattr(ctx, "context_id", ""),
            "material": rfq.get("material", ""),
            "surface": rfq.get("surface", ""),
            "quantity": rfq.get("quantity", 0),
            "tolerance": rfq.get("tolerance_grade", ""),
            "unit_price": quote.get("unit_price"),
            "margin_pct": commercial.get("margin_pct"),
            "state": getattr(ctx, "state", ""),
            "timestamp": time.time(),
        }

        rfqs = existing.get("recent_rfqs", [])
        rfqs.append(recent_rfq)
        # 只保留最近 20 条
        rfqs = rfqs[-20:]

        existing.update({
            "customer_id": customer_id,
            "recent_rfqs": rfqs,
            "last_rfq_at": recent_rfq["timestamp"],
            "last_material": recent_rfq["material"],
            "last_surface": recent_rfq["surface"],
        })

        self.sandbox.set_context(customer_id, existing)

    # ---------- 注入客户级记忆到 per-RFQ Context ----------

    def inject_into(self, customer_id: str, ctx: "Context") -> None:
        """将客户级记忆注入单次询盘的 Context (联动).

        注入内容:
          - 校准参数 → ctx.commercial (margin_pct, price_adjustment_factor)
          - 客户偏好 → ctx.customer (preferences, lifecycle_state)
          - 历史模式 → ctx.evidence (历史报价模式作为 crm evidence)
        """
        if not customer_id:
            return

        info = self.load(customer_id)

        # 1. 校准参数 → ctx.commercial
        sandbox_params = info.get("sandbox_params", {})
        if sandbox_params:
            # 只注入参数, 不生成数字 (铁律①)
            ctx.commercial.setdefault("calibrated_params", {})
            ctx.commercial["calibrated_params"].update({
                "margin_pct": sandbox_params.get("margin_pct"),
                "lead_time_buffer_days": sandbox_params.get("lead_time_buffer_days"),
                "price_adjustment_factor": sandbox_params.get("price_adjustment_factor", 1.0),
            })

        # 最新校准的 adjusted_margin 优先
        calibrations = info.get("calibrations", [])
        if calibrations:
            latest_cal = calibrations[0]
            if latest_cal.get("adjusted_margin") is not None:
                ctx.commercial.setdefault("calibrated_params", {})
                ctx.commercial["calibrated_params"]["adjusted_margin"] = \
                    latest_cal["adjusted_margin"]
                ctx.commercial["calibrated_params"]["avg_bias"] = \
                    latest_cal.get("avg_bias", 0.0)

        # 2. 客户偏好 → ctx.customer
        preferences = info.get("preferences", {})
        ctx.customer.setdefault("customer_id", customer_id)
        ctx.customer["preferences"] = preferences
        ctx.customer["lifecycle_state"] = info.get("lifecycle_state", "NEW")
        ctx.customer["health_score"] = info.get("health_score", 1.0)

        # 3. 历史模式 → ctx.evidence (用 add_evidence, source_type='crm')
        sandbox_context = info.get("sandbox_context", {})
        recent_rfqs = sandbox_context.get("recent_rfqs", [])
        if recent_rfqs:
            try:
                ctx.add_evidence(
                    source_type="crm",
                    content={
                        "type": "customer_history",
                        "recent_rfqs": recent_rfqs[-5:],  # 最近 5 条
                        "preferences": preferences,
                    },
                    source_ref=f"crm://{customer_id}/history",
                    confidence=0.9,
                )
            except Exception:
                pass  # evidence 注入失败不阻断主流程

        # 4. 跟进状态 → ctx.flywheel_state (如果存在)
        if hasattr(ctx, "flywheel_state"):
            ctx.flywheel_state.setdefault("customer_id", customer_id)
            ctx.flywheel_state["follow_ups_due"] = info.get("follow_ups", [])
            ctx.flywheel_state["lifecycle_state"] = info.get("lifecycle_state", "NEW")

    # ---------- 从历史 RFQ 提取偏好 ----------

    def extract_preferences(self, customer_id: str) -> Dict[str, Any]:
        """从历史 RFQ 提取客户偏好 (常用材料/表面处理/公差等级/数量模式).

        返回 dict:
          materials: [{material, count}], 按频次降序
          surfaces: [{surface, count}]
          tolerances: [{tolerance, count}]
          quantity_mode: {avg, min, max, median}
          top_material: 最常用材料
          top_surface: 最常用表面处理
        """
        if not customer_id:
            return {}

        hist = self.crm.list_customer_history(customer_id, limit=100)
        quotes = hist.get("quotes", [])

        # 从 quotes 反查 rfqs 表获取材料/表面/公差/数量
        materials: Dict[str, int] = {}
        surfaces: Dict[str, int] = {}
        tolerances: Dict[str, int] = {}
        quantities: List[int] = []

        for q in quotes:
            ctx_id = q.get("context_id")
            if not ctx_id:
                continue
            row = self.crm._conn.execute(
                "SELECT material, surface, quantity, tolerance "
                "FROM rfqs WHERE context_id=?", (ctx_id,)).fetchone()
            if not row:
                continue
            mat, surf, qty, tol = row
            if mat:
                materials[mat] = materials.get(mat, 0) + 1
            if surf:
                surfaces[surf] = surfaces.get(surf, 0) + 1
            if tol:
                tolerances[tol] = tolerances.get(tol, 0) + 1
            if qty:
                quantities.append(qty)

        # 按频次降序
        mat_list = sorted([{"material": k, "count": v}
                           for k, v in materials.items()],
                          key=lambda x: x["count"], reverse=True)
        surf_list = sorted([{"surface": k, "count": v}
                            for k, v in surfaces.items()],
                           key=lambda x: x["count"], reverse=True)
        tol_list = sorted([{"tolerance": k, "count": v}
                           for k, v in tolerances.items()],
                          key=lambda x: x["count"], reverse=True)

        # 数量统计
        qty_mode = {}
        if quantities:
            qty_sorted = sorted(quantities)
            qty_mode = {
                "avg": round(sum(quantities) / len(quantities), 1),
                "min": qty_sorted[0],
                "max": qty_sorted[-1],
                "median": qty_sorted[len(qty_sorted) // 2],
            }

        return {
            "materials": mat_list[:5],
            "surfaces": surf_list[:5],
            "tolerances": tol_list[:5],
            "quantity_mode": qty_mode,
            "top_material": mat_list[0]["material"] if mat_list else None,
            "top_surface": surf_list[0]["surface"] if surf_list else None,
        }