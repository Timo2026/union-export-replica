"""bootstrap.py — 组装根: 从配置构建 CATController (Replace the adapters, not the architecture).

用法:
    from bootstrap import build_controller
    ctrl = build_controller()          # 自动读 config/settings.yaml + policy.yaml
    result = ctrl.run(email_text=..., customer=...)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from adapters.timo_adapter import TimoAdapter          # noqa: E402
from adapters.funasr_adapter import FunASRAdapter       # noqa: E402
from agents.cat_controller import CATController         # noqa: E402
from services.config import load_commercial, load_policy, load_settings  # noqa: E402
from services.crm_memory import CRMMemory               # noqa: E402
from services.llm_planner import LLMPlanner             # noqa: E402
from services import model_config                        # noqa: E402


def _build_planner(settings: Dict[str, Any], mcfg: Optional[Dict[str, Any]] = None) -> LLMPlanner:
    """LLM Planner 端点优先取 models.yaml(UI 可改), 回退 settings.model_router。"""
    mr = (settings.get("model_router", {}) or {})
    backend = str(mr.get("backend", "local"))
    llm = model_config.get_model(mcfg, "llm") if mcfg else {}
    ep = llm.get("endpoint") or ((mr.get("roles", {}) or {}).get("REASON") or {}).get("endpoint", "http://127.0.0.1:1234/v1")
    model = llm.get("model") or ((mr.get("roles", {}) or {}).get("REASON") or {}).get("model", "qwen3.8-27b")
    if not llm.get("enabled", True) and mcfg:
        backend = "mock"          # UI 关闭 LLM → Planner 走 MOCK
    if backend == "nvidia":
        nim = ((settings.get("nvidia_nim", {}) or {}).get("REASON")
               or {"endpoint": "http://127.0.0.1:8000/v1", "model": "deepseek-ai/deepseek-r1"})
        ep, model = nim.get("endpoint", ep), nim.get("model", model)
    return LLMPlanner(endpoint=ep, model=model,
                      backend=("mock" if backend == "mock" else "local"),
                      allow_mock=True)


def _funasr_cfg(settings: Dict[str, Any], mcfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """funasr 适配器端点优先取 models.yaml(asr/vlm/embedding + 网关), 回退 settings.funasr。"""
    base = dict((settings.get("funasr", {}) or {}))
    if mcfg:
        gw = (mcfg.get("funasr_gateway") or {}).get("endpoint")
        if gw:
            base["base_url"] = gw
        for key, field in [("asr", "asr_url"), ("vlm", "vlm_url"), ("embedding", "embed_url")]:
            ep = model_config.endpoint_for(key, mcfg)
            if ep:
                base[field] = ep
    return {"funasr": base}


def build_controller(root: Optional[Path] = None, use_crm: bool = True,
                     settings_override: Optional[Dict[str, Any]] = None) -> CATController:
    root = Path(root) if root else _ROOT
    settings = settings_override or load_settings(root)
    policy = load_policy(root)
    commercial_cfg = load_commercial(root)
    try:
        mcfg = model_config.load()
    except Exception:
        mcfg = None
    timo = TimoAdapter(settings)
    funasr = FunASRAdapter(_funasr_cfg(settings, mcfg))
    planner = _build_planner(settings, mcfg)
    crm = None
    if use_crm:
        db = settings.get("storage", {}).get("crm_db", "data/crm.sqlite3")
        if not Path(db).is_absolute():
            db = str(root / db)
        crm = CRMMemory(db)
    return CATController(timo=timo, funasr=funasr, policy=policy,
                         settings=settings, crm=crm, commercial_cfg=commercial_cfg,
                         planner=planner)


def status() -> Dict[str, Any]:
    """环境自检: 各后端在线状态。"""
    s = load_settings(_ROOT)
    t = TimoAdapter(s)
    f = FunASRAdapter(s)
    return {
        "timo_online": t.health(), "timo_source": t.source_label(),
        "funasr_online": f.health(), "funasr_source": f.source_label(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(status(), ensure_ascii=False, indent=2))
