"""services.web_search — 联网搜索接入点 (直接调用本地 SearXNG 引擎).

SearXNG 是项目 tools/searxng/ 内嵌的元搜索引擎 (聚合 Google/Bing/DDG 等).

铁律:
  - 不可达时返空 + log warning, 不静默冒充
  - 隐私优先: SearXNG 本地部署, 搜索记录不外发
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

DEFAULT_SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8888")
DEFAULT_TIMEOUT_S = 10


def health(base_url: str = DEFAULT_SEARXNG_URL, timeout_s: float = 3.0) -> bool:
    """检查本地 SearXNG 服务."""
    try:
        with urllib.request.urlopen(f"{base_url}/", timeout=timeout_s) as r:
            return r.status == 200
    except Exception:
        return False


def search(query: str, num: int = 5, category: str = "general",
          base_url: str = DEFAULT_SEARXNG_URL, timeout_s: float = DEFAULT_TIMEOUT_S) -> Dict[str, Any]:
    """SearXNG 联网搜索.

    输入: query (搜索词), num (结果数), category (general/news/images/videos)
    输出: {hits: [{title, url, snippet, engine}], mock: bool, _source}
    """
    if not health(base_url, timeout_s=2.0):
        log.warning("[web_search] SearXNG 不可达, 返空")
        return {"hits": [], "mock": False, "_source": "searxng-offline",
                "warning": "SearXNG 不可达, 启动 tools/searxng/SearXNG.exe 后重试"}

    params = f"q={urllib.parse.quote(query)}&format=json&categories={category}"
    try:
        req = urllib.request.Request(f"{base_url}/search?{params}")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read())
            hits = [
                {"title": r.get("title", ""), "url": r.get("url", ""),
                 "snippet": r.get("content", ""), "engine": r.get("engine", "")}
                for r in data.get("results", [])[:num]
            ]
            return {"hits": hits, "mock": False, "_source": f"searxng@{base_url}"}
    except Exception as e:
        log.warning("[web_search] HTTP 失败: %r", e)
        return {"hits": [], "mock": False, "_source": "searxng-error",
                "warning": repr(e)}


def page_summary(url: str, base_url: str = DEFAULT_SEARXNG_URL,
                timeout_s: float = DEFAULT_TIMEOUT_S) -> Optional[str]:
    """调 SearXNG 提取网页摘要 (给 LLM 提供上下文)."""
    if not health(base_url, timeout_s=2.0):
        return None
    try:
        params = f"url={urllib.parse.quote(url)}&format=json"
        req = urllib.request.Request(f"{base_url}/summary?{params}")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read())
            return data.get("summary", "")
    except Exception as e:
        log.warning("[web_search] summary 失败: %r", e)
        return None
