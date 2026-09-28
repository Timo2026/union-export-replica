"""security.py — 上传端口硬化 + 数据脱敏 (维度 6.2 / 7.2 / 15 安全).

- safe_filename: 防路径穿越 (剥离目录/.. /绝对路径/控制字符)
- size_guard: 上传大小上限
- redact: PII/凭证脱敏 (入审计/日志前)
- RateLimiter: 令牌桶限流 (per-client)
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

# ---- 凭证/PII 脱敏模式 ----
_REDACT_PATTERNS = [
    (re.compile(r"(sk-[A-Za-z0-9]{6,})"), "<REDACTED_API_KEY>"),
    (re.compile(r"(AKIA[0-9A-Z]{12,})"), "<REDACTED_AWS_KEY>"),
    (re.compile(r"(ghp_[A-Za-z0-9]{10,})"), "<REDACTED_GH_TOKEN>"),
    (re.compile(r"(xox[baprs]-[A-Za-z0-9-]{6,})"), "<REDACTED_SLACK_TOKEN>"),
    (re.compile(r"(Bearer\s+[A-Za-z0-9\-._~+/]{8,})", re.I), "<REDACTED_BEARER>"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
     "<REDACTED_PRIVATE_KEY>"),
    (re.compile(r"\b([\w.+-]+@[\w-]+\.[\w.]+)\b"), "<REDACTED_EMAIL>"),
    (re.compile(r"\b(1[3-9]\d{9})\b"), "<REDACTED_PHONE>"),          # 中国大陆手机号
    (re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+"), "\\1=<REDACTED>"),
]

MAX_UPLOAD_BYTES = 50 * 1024 * 1024      # 50MB 默认上限
_ALLOWED_NAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]")


def safe_filename(name: Optional[str], fallback: str = "upload.bin") -> str:
    """防路径穿越: 只取 basename, 去 .. / 绝对路径 / 控制字符。"""
    if not name:
        return fallback
    base = Path(name.replace("\\", "/")).name           # 剥离任何目录
    base = base.replace("..", "_").strip()
    base = _ALLOWED_NAME.sub("_", base)
    return base or fallback


def size_guard(nbytes: int, limit: int = MAX_UPLOAD_BYTES) -> None:
    if nbytes > limit:
        raise ValueError(f"upload too large: {nbytes} > {limit} bytes")


def redact(text: Any) -> Any:
    """对字符串做 PII/凭证脱敏; 非字符串原样返回。"""
    if not isinstance(text, str):
        return text
    out = text
    for pat, repl in _REDACT_PATTERNS:
        out = pat.sub(repl, out)
    return out


def redact_dict(d: Dict[str, Any], keys: tuple = ("email", "body", "text", "content",
                                                  "voice_transcript", "raw_text")) -> Dict[str, Any]:
    out = dict(d)
    for k in keys:
        if k in out and isinstance(out[k], str):
            out[k] = redact(out[k])
    return out


class RateLimiter:
    """令牌桶限流 (per-key)。capacity 令牌, refill_rate 令牌/秒。"""
    def __init__(self, capacity: int = 30, refill_rate: float = 5.0):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._buckets: Dict[str, float] = {}
        self._ts: Dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, cost: int = 1) -> bool:
        now = time.time()
        with self._lock:
            tokens = self._buckets.get(key, float(self.capacity))
            last = self._ts.get(key, now)
            tokens = min(self.capacity, tokens + (now - last) * self.refill_rate)
            if tokens >= cost:
                self._buckets[key] = tokens - cost
                self._ts[key] = now
                return True
            self._buckets[key] = tokens
            self._ts[key] = now
            return False

    def reset(self, key: Optional[str] = None):
        with self._lock:
            if key is None:
                self._buckets.clear(); self._ts.clear()
            else:
                self._buckets.pop(key, None); self._ts.pop(key, None)
