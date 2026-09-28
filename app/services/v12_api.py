"""v12_api.py — /v1/v12/* 端点: Timo_CNC-AI-Brain v12 内核实时状态.

供 webui #tab-v12 仪表板. 读多写少, 全 GET.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .v12_status import V12Status

router = APIRouter(prefix="/v1/v12", tags=["v12"])

_V12 = V12Status()


@router.get("/status")
def v12_status():
    return JSONResponse(_V12.status())


@router.get("/audit")
def v12_audit(limit: int = 10):
    return JSONResponse(_V12.audit(limit=limit))


@router.get("/dfm")
def v12_dfm():
    return JSONResponse(_V12.dfm())