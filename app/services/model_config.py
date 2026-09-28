"""model_config.py — 模型注册表管理 (UI「模型设置工具」后端).

职责: 读写 config/models.yaml (LLM/VLM/Embedding/OCR/ASR/DETERMINISTIC), 并对每个端点真实探活。
UI 改动 → save() 落盘 → Planner/funasr/model_router 重新加载即生效。
铁律: deterministic 角色 locked, 不可禁用/不可改成 LLM (报价不走 LLM)。

v2.3.1 新增: A/B 路由 (ab_test.alternate + strategy) + fallback 端点。
  - primary 是顶层 endpoint/model; alternate 在 ab_test.alternate; fallback 在顶层 fallback。
  - 策略: primary_only / fallback / ab_hash / ab_round_robin
  - choose_route() 返回带 selected 用法的元数据, 供 router/adapter 决策。
"""
from __future__ import annotations

import hashlib
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_MODELS_YAML = _ROOT / "config" / "models.yaml"

_REQUIRED_FIELDS = ("endpoint", "model")
KNOWN_KEYS = ("llm", "vlm", "embedding", "ocr", "asr", "deterministic")
_AB_STRATEGIES = ("primary_only", "fallback", "ab_hash", "ab_round_robin")


def _load_yaml(path: Path) -> Dict[str, Any]:
    import yaml  # type: ignore
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load() -> Dict[str, Any]:
    return _load_yaml(_MODELS_YAML)


def save(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """校验并写回 models.yaml。返回规范化后的配置。"""
    import yaml  # type: ignore
    errs = validate(cfg)
    if errs:
        raise ValueError(f"invalid model config: {errs}")
    cfg = dict(cfg)
    cfg["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # 强制 deterministic locked + enabled (铁律①不可被 UI 关掉)
    det = (cfg.get("models") or {}).get("deterministic")
    if isinstance(det, dict):
        det["locked"] = True
        det["enabled"] = True
    _MODELS_YAML.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8")
    return cfg


def validate(cfg: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    models = cfg.get("models")
    if not isinstance(models, dict) or not models:
        return ["models 为空或非对象"]
    for key, m in models.items():
        if not isinstance(m, dict):
            errs.append(f"{key}: 非对象")
            continue
        for f in _REQUIRED_FIELDS:
            if not m.get(f):
                errs.append(f"{key}: 缺 {f}")
        ep = str(m.get("endpoint", ""))
        if ep and not ep.startswith(("http://", "https://")):
            errs.append(f"{key}: endpoint 必须以 http(s):// 开头")
        if key == "deterministic" and not m.get("enabled", True):
            errs.append("deterministic: 不可禁用 (铁律①: 报价不走 LLM)")
        # ---- v2.3.1: A/B / fallback 校验 ----
        ab = m.get("ab_test")
        if ab is not None:
            if not isinstance(ab, dict):
                errs.append(f"{key}: ab_test 必须是对象")
            else:
                strat = ab.get("strategy", "primary_only")
                if strat not in _AB_STRATEGIES:
                    errs.append(f"{key}: ab_test.strategy 必须是 {_AB_STRATEGIES}")
                alt = ab.get("alternate")
                if strat in ("ab_hash", "ab_round_robin"):
                    if not isinstance(alt, dict):
                        errs.append(f"{key}: ab_test.strategy={strat} 必须有 alternate 对象")
                    else:
                        for f in ("endpoint", "model"):
                            if not alt.get(f):
                                errs.append(f"{key}: ab_test.alternate 缺 {f}")
                        aep = str(alt.get("endpoint", ""))
                        if aep and not aep.startswith(("http://", "https://")):
                            errs.append(f"{key}: ab_test.alternate.endpoint 必须以 http(s):// 开头")
        fb = m.get("fallback")
        if fb is not None:
            if not isinstance(fb, dict):
                errs.append(f"{key}: fallback 必须是对象")
            else:
                for f in ("endpoint", "model"):
                    if not fb.get(f):
                        errs.append(f"{key}: fallback 缺 {f}")
                fep = str(fb.get("endpoint", ""))
                if fep and not fep.startswith(("http://", "https://")):
                    errs.append(f"{key}: fallback.endpoint 必须以 http(s):// 开头")
        # deterministic 不可参与 A/B（确定性是真相）
        if key == "deterministic" and (ab or fb):
            errs.append("deterministic: 不可配置 ab_test/fallback (确定性角色是真相)")
    return errs


def get_model(cfg: Optional[Dict[str, Any]], key: str) -> Dict[str, Any]:
    cfg = cfg or load()
    return (cfg.get("models") or {}).get(key, {}) or {}


def _probe_url(entry: Dict[str, Any]) -> str:
    ep = str(entry.get("endpoint", "")).rstrip("/")
    pp = str(entry.get("probe_path", "/") or "/")
    if not pp.startswith("/"):
        pp = "/" + pp
    return ep + pp


def probe_one(entry: Dict[str, Any], timeout: float = 4.0) -> Dict[str, Any]:
    """对单个模型端点真实探活: GET probe_url, 返回 online/状态码/时延。"""
    if not entry.get("enabled", True):
        return {"online": False, "skipped": "disabled", "latency_ms": None}
    url = _probe_url(entry)
    if not url.strip("/"):
        return {"online": False, "error": "no endpoint", "latency_ms": None}
    t0 = time.time()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"online": r.status == 200, "status_code": r.status,
                    "latency_ms": round((time.time() - t0) * 1000, 1), "url": url}
    except Exception as e:  # noqa
        return {"online": False, "error": repr(e)[:120],
                "latency_ms": round((time.time() - t0) * 1000, 1), "url": url}


def probe_all(cfg: Optional[Dict[str, Any]] = None, timeout: float = 4.0) -> Dict[str, Any]:
    cfg = cfg or load()
    models = cfg.get("models") or {}
    out: Dict[str, Any] = {}
    for key, entry in models.items():
        r = probe_one(entry, timeout=timeout)
        d = {"label": entry.get("label", key), "role": entry.get("role"),
             "endpoint": entry.get("endpoint"), "model": entry.get("model"),
             "enabled": entry.get("enabled", True), **r}
        # 探活 alternate (A/B)
        ab = entry.get("ab_test") or {}
        alt = ab.get("alternate") if isinstance(ab, dict) else None
        if isinstance(alt, dict) and alt.get("endpoint"):
            ar = probe_one({**alt, "enabled": entry.get("enabled", True)}, timeout=timeout)
            d["alternate"] = {"endpoint": alt.get("endpoint"), "model": alt.get("model"),
                              "strategy": ab.get("strategy", "primary_only"), **ar}
        # 探活 fallback
        fb = entry.get("fallback")
        if isinstance(fb, dict) and fb.get("endpoint"):
            fr = probe_one({**fb, "enabled": entry.get("enabled", True)}, timeout=timeout)
            d["fallback"] = {"endpoint": fb.get("endpoint"), "model": fb.get("model"), **fr}
        out[key] = d
    # funasr 网关
    gw = cfg.get("funasr_gateway") or {}
    if gw.get("endpoint"):
        g = probe_one({"endpoint": gw["endpoint"], "probe_path": gw.get("probe_path", "/health"),
                       "enabled": True}, timeout=timeout)
        out["funasr_gateway"] = {"label": "funasr 多模态网关", "role": "GATEWAY",
                                 "endpoint": gw.get("endpoint"), **g}
    return out


# ---- v2.3.1: A/B 路由决策 ----

def _hash_pick(key: str, request_id: Optional[str]) -> int:
    """稳定 hash 选 0 或 1。"""
    h = hashlib.sha256((key + "|" + (request_id or "")).encode("utf-8")).digest()
    return h[0] % 2


def choose_route(key: str, cfg: Optional[Dict[str, Any]] = None,
                 request_id: Optional[str] = None,
                 round_robin_counter: Optional[Dict[str, int]] = None
                 ) -> Dict[str, Any]:
    """根据 entry 的 ab_test/fallback 决策返回 {selected, source, ...}。

    决策表:
      - 顶层 endpoint 在线 + 无 A/B: selected=primary, source=primary
      - 顶层 endpoint 在线 + ab_test.strategy=ab_hash: 按 request_id hash 选 primary/alternate
      - 顶层 endpoint 在线 + ab_test.strategy=ab_round_robin: 按 counter 交替
      - 顶层 endpoint 在线 + ab_test.strategy=fallback: 顶层 primary (忽略 alternate)
      - 顶层 endpoint 离线 + fallback 在线: fallback
      - 否则 source=offline
    """
    entry = get_model(cfg, key)
    if not entry:
        return {"selected": None, "source": "missing", "endpoint": None, "model": None,
                "strategy": "primary_only"}
    if not entry.get("enabled", True):
        return {"selected": None, "source": "disabled", "endpoint": None, "model": None,
                "strategy": "primary_only"}

    primary = {"endpoint": entry.get("endpoint"), "model": entry.get("model")}
    ab = entry.get("ab_test") or {}
    strat = (ab.get("strategy") or "primary_only") if isinstance(ab, dict) else "primary_only"
    alt = ab.get("alternate") if isinstance(ab, dict) else None
    fb = entry.get("fallback")

    # 简化: 在线探测由调用方完成 (router/adapter 已经 probe); 此处只做逻辑决策
    # 调用方拿到 decision 后用 selected.endpoint 真探一次
    if strat == "ab_hash" and isinstance(alt, dict):
        pick = _hash_pick(key, request_id)
        if pick == 0:
            return {"selected": primary, "alternate": alt, "source": "primary",
                    "strategy": strat, "endpoint": primary["endpoint"],
                    "model": primary["model"]}
        return {"selected": alt, "alternate": primary, "source": "alternate",
                "strategy": strat, "endpoint": alt.get("endpoint"),
                "model": alt.get("model")}

    if strat == "ab_round_robin" and isinstance(alt, dict):
        if round_robin_counter is None:
            round_robin_counter = {}
        n = round_robin_counter.get(key, 0)
        round_robin_counter[key] = n + 1
        if n % 2 == 0:
            return {"selected": primary, "alternate": alt, "source": "primary",
                    "strategy": strat, "endpoint": primary["endpoint"],
                    "model": primary["model"]}
        return {"selected": alt, "alternate": primary, "source": "alternate",
                "strategy": strat, "endpoint": alt.get("endpoint"),
                "model": alt.get("model")}

    if strat == "fallback":
        # 强制走 primary; 若 primary 离线由调用方 fallback 到 entry.fallback
        return {"selected": primary, "fallback": fb, "source": "primary",
                "strategy": strat, "endpoint": primary["endpoint"],
                "model": primary["model"]}

    # primary_only
    return {"selected": primary, "fallback": fb, "source": "primary",
            "strategy": "primary_only", "endpoint": primary["endpoint"],
            "model": primary["model"]}


# ---- 供 adapter/router 读取的便捷函数 ----
def endpoint_for(key: str, cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    m = get_model(cfg, key)
    return m.get("endpoint") if m.get("enabled", True) else None


def model_for(key: str, cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    m = get_model(cfg, key)
    return m.get("model") if m.get("enabled", True) else None


if __name__ == "__main__":
    import json
    print(json.dumps(probe_all(), ensure_ascii=False, indent=2))
