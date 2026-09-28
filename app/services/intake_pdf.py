"""services.intake_pdf — PDF 接入点 (直接调用本地 MinerU 服务, 无适配层).

MinerU 是项目 tools/mineru/ 内嵌的 PDF/Office 深度解析工具.
本模块是业务接入点: 调本地 MinerU HTTP 服务, 解析上传的 PDF/Office 附件.

铁律:
  - 不可达时返 None + log warning, 不静默冒充
  - 输出格式标准化: {text, layout, tables, formulas, metadata}
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# 默认本地 MinerU 端点 (启动 tools/mineru/docker/compose.yaml 后可达)
DEFAULT_MINERU_URL = os.environ.get("MINERU_URL", "http://127.0.0.1:8081")
DEFAULT_TIMEOUT_S = 30


def health(base_url: str = DEFAULT_MINERU_URL, timeout_s: float = 3.0) -> bool:
    """检查本地 MinerU 服务是否在线."""
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=timeout_s) as r:
            return r.status == 200
    except Exception:
        return False


def parse_pdf(pdf_path: str, base_url: str = DEFAULT_MINERU_URL,
              timeout_s: float = DEFAULT_TIMEOUT_S) -> Optional[Dict[str, Any]]:
    """调本地 MinerU 解析 PDF → 标准化输出.

    输入: pdf_path (本地文件路径)
    输出: {text, layout, tables, formulas, metadata} 或 None (失败)
    """
    p = Path(pdf_path)
    if not p.exists():
        log.warning("[intake_pdf] 文件不存在: %s", pdf_path)
        return None

    # 优先 HTTP 上传
    if health(base_url, timeout_s=2.0):
        try:
            import urllib.request
            import mimetypes
            boundary = "----mineru"
            with open(pdf_path, "rb") as f:
                file_data = f.read()
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{p.name}"\r\n'
                f"Content-Type: {mimetypes.guess_type(str(p))[0] or 'application/octet-stream'}\r\n\r\n"
            ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(f"{base_url}/parse",
                                        data=body,
                                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read())
        except Exception as e:
            log.warning("[intake_pdf] HTTP 失败, 尝试本地 CLI fallback: %r", e)

    # Fallback: 直接调本地 CLI (tools/mineru/docker/ 内有 parse.py 或类似)
    cli_script = Path(__file__).resolve().parent.parent / "tools" / "mineru" / "parse_local.py"
    if cli_script.exists():
        try:
            import subprocess
            r = subprocess.run(["python", str(cli_script), pdf_path],
                               capture_output=True, text=True, timeout=timeout_s,
                               encoding="utf-8", errors="replace")
            if r.returncode == 0:
                return json.loads(r.stdout)
        except Exception as e:
            log.warning("[intake_pdf] CLI fallback 失败: %r", e)

    log.warning("[intake_pdf] MinerU 完全不可达, 返 None")
    return None


def extract_layout(pdf_path: str, **kw: Any) -> Optional[Dict[str, Any]]:
    """仅提取版面 (公式 / 表格 / 图片位置)."""
    result = parse_pdf(pdf_path, **kw)
    if result is None:
        return None
    return {"layout": result.get("layout", []),
            "tables": result.get("tables", []),
            "formulas": result.get("formulas", [])}
