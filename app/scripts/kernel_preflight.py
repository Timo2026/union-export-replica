"""kernel_preflight.py — 制造内核三态预检 (demo/验收脚本共用).

内核 cnc-ai-brain v12.0-Fusion 是**确定性报价与 DFM 裁决的唯一权威来源**
(铁律② LLM 不定价)。它缺席时:

  - 绝不用另一个引擎冒充 (那会让 BLOCKED/PASS 失去意义);
  - 绝不静默跳过 (那会把"没测"显示成"通过");
  - 只如实上报三态, 并让调用方以退出码 3 结束 (区别于 1 = 断言失败)。

三态:
  live            命中真实 FastAPI :7862
  byte-identical  离线内核源码在本机, 子进程 import 真实 calc_quote/ConflictChecker
  absent          两者都不可用 → 报价/DFM 无法进行
"""
from __future__ import annotations

from typing import Any, Dict

STATE_LIVE = "live"
STATE_OFFLINE = "byte-identical"
STATE_ABSENT = "absent"

EXIT_ENV_MISSING = 3


def probe(ctrl: Any) -> Dict[str, Any]:
    """探测控制器所持 TimoAdapter 的内核三态. 不抛异常."""
    timo = getattr(ctrl, "timo", None)
    online = False
    available = False
    label = "unavailable"
    if timo is not None:
        try:
            online = bool(timo.health())
        except Exception:
            online = False
        try:
            available = bool(getattr(timo, "kernel_available", False))
        except Exception:
            available = False
        try:
            label = str(timo.source_label())
        except Exception:
            label = "offline:kernel-absent(UNVERIFIED)"

    if online:
        state = STATE_LIVE
    elif available:
        state = STATE_OFFLINE
    else:
        state = STATE_ABSENT

    return {
        "state": state,
        "online": online,
        "kernel_available": available,
        "source_label": label,
        "engine_src": str(getattr(timo, "engine_src", "") or ""),
        "engine_python": str(getattr(timo, "engine_python", "") or ""),
        "usable": state != STATE_ABSENT,
    }


def banner(probe_result: Dict[str, Any]) -> str:
    """给人看的一行摘要."""
    s = probe_result["state"]
    if s == STATE_LIVE:
        return f"内核: live ({probe_result['source_label']})"
    if s == STATE_OFFLINE:
        return f"内核: offline byte-identical ({probe_result['source_label']})"
    return (f"内核: absent ({probe_result['source_label']})\n"
            f"        engine_src  = {probe_result['engine_src']!r} (本机不存在)\n"
            f"        修复: 设置 CNC_BRAIN_SRC / CNC_BRAIN_PY 指向 cnc-ai-brain v12.0 根目录及其解释器\n"
            f"        说明: 内核是确定性报价/DFM 的唯一权威来源, 缺席时不造假、不静默跳过")


def require(ctrl: Any, title: str = "") -> Dict[str, Any]:
    """预检 + 打印. 返回 probe 结果; 缺席时打印显式降级说明 (调用方据此返回 EXIT_ENV_MISSING)."""
    r = probe(ctrl)
    if title:
        print(f" {title}")
    print(f" {banner(r)}")
    return r
