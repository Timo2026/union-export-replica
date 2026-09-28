"""flywheel_api.py — 飞轮 API 端点：客户沙箱 + 报价统计。

端点:
  GET  /v1/flywheel/customers              客户列表
  GET  /v1/flywheel/customers/{cid}        客户画像 + 报价统计
  POST /v1/flywheel/customers/{cid}/quote  记录报价
  POST /v1/flywheel/customers/{cid}/outcome 记录结果
  GET  /v1/flywheel/stats                  全局统计
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.sandbox import CustomerSandbox, get_sandbox, list_all_sandboxes

router = APIRouter(prefix="/v1/flywheel", tags=["flywheel"])


class QuoteRequest(BaseModel):
    rfq: Dict[str, Any]
    quote: Dict[str, Any]


class OutcomeRequest(BaseModel):
    context_id: str
    outcome: str
    actual_cost: Optional[float] = None
    note: str = ""


@router.get("/customers")
def list_customers() -> Dict[str, Any]:
    """列出所有客户沙箱。"""
    customers = list_all_sandboxes()
    return {"customers": customers, "count": len(customers)}


@router.get("/customers/{customer_id}")
def get_customer(customer_id: str) -> Dict[str, Any]:
    """获取客户画像 + 报价历史。"""
    try:
        sb = get_sandbox(customer_id)
        history = sb.get_history(limit=20)
        model = sb.get_pricing_model()
        knowledge = sb.get_knowledge_base(limit=10)
        sb.close()
        return {
            "customer_id": customer_id,
            "pricing_model": model,
            "history": history,
            "knowledge_base": knowledge,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/customers/{customer_id}/quote")
def record_quote(customer_id: str, req: QuoteRequest) -> Dict[str, Any]:
    """记录报价到客户沙箱。"""
    try:
        sb = get_sandbox(customer_id)
        context_id = req.rfq.get("context_id", f"API-{int(time.time())}")
        sb.write_rfq(context_id, req.rfq)
        sb.write_quote(context_id, req.quote)
        sb.close()
        return {"ok": True, "context_id": context_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/customers/{customer_id}/outcome")
def record_outcome(customer_id: str, req: OutcomeRequest) -> Dict[str, Any]:
    """记录成交/丢单结果。"""
    try:
        sb = get_sandbox(customer_id)
        sb.record_postmortem(req.context_id, req.outcome, req.actual_cost, req.note)
        # 更新定价模型
        won = req.outcome == "won"
        quote_data = sb.get_history(limit=1)
        if quote_data["quotes"]:
            last_quote = quote_data["quotes"][0]
            deviation = 0.0
            if req.actual_cost and last_quote.get("unit_price"):
                deviation = (last_quote["unit_price"] - req.actual_cost) / req.actual_cost * 100
            sb.update_pricing_model(0, 0, 0, deviation, won)
        sb.close()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
def flywheel_stats() -> Dict[str, Any]:
    """全局飞轮统计。"""
    customers = list_all_sandboxes()
    total_quotes = 0
    total_won = 0
    total_lost = 0
    for c in customers:
        total_quotes += c.get("total_quotes", 0)
        total_won += c.get("total_won", 0)
        total_lost += c.get("total_lost", 0)
    return {
        "total_customers": len(customers),
        "total_quotes": total_quotes,
        "total_won": total_won,
        "total_lost": total_lost,
        "overall_win_rate": round(total_won / (total_won + total_lost), 3) if (total_won or total_lost) else 0,
    }
