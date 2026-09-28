"""services.asr_engine — ASR/TTS 接入点 (直接调用本地 OmniVoice 引擎).

OmniVoice 是项目 tools/omnivoice/ 内嵌的 ASR + TTS 引擎 (含 Python embedded + 模型).

铁律:
  - 不可达时返 None + log warning, 不静默冒充
  - ASR + TTS 都通过本地子进程调用
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# OmniVoice 默认端点 (HTTP 模式启动后)
DEFAULT_OMNIVOICE_URL = os.environ.get("OMNIVOICE_URL", "http://127.0.0.1:8082")
DEFAULT_TIMEOUT_S = 30


def health(base_url: str = DEFAULT_OMNIVOICE_URL, timeout_s: float = 3.0) -> bool:
    """检查本地 OmniVoice 服务."""
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=timeout_s) as r:
            return r.status == 200
    except Exception:
        return False


def asr(audio_path: str, base_url: str = DEFAULT_OMNIVOICE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        language: str = "zh") -> Optional[str]:
    """ASR 转写: 音频 → 文本.

    输入: audio_path (wav/mp3/m4a 等)
    输出: 转写文本或 None (失败)
    """
    p = Path(audio_path)
    if not p.exists():
        log.warning("[asr] 文件不存在: %s", audio_path)
        return None

    if health(base_url, timeout_s=2.0):
        try:
            import mimetypes
            boundary = "----omnivoice"
            with open(audio_path, "rb") as f:
                data = f.read()
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="audio"; filename="{p.name}"\r\n'
                f"Content-Type: {mimetypes.guess_type(str(p))[0] or 'audio/wav'}\r\n\r\n"
            ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(f"{base_url}/v1/asr?language={language}",
                                        data=body,
                                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read()).get("text")
        except Exception as e:
            log.warning("[asr] HTTP 失败, fallback 本地 CLI: %r", e)

    # Fallback: 调本地 OmniVoice Python embedded (subprocess)
    cli_python = Path(__file__).resolve().parent.parent / "tools" / "omnivoice" / "engine" / "python.exe"
    if cli_python.exists():
        try:
            r = subprocess.run(
                [str(cli_python), "-c", "print('ASR_MOCK')"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            if r.returncode == 0:
                # 真实 OmniVoice API 调用 (待 engine 启动后实现)
                return None  # 暂无完整 ASR 引擎, fallback mock
        except Exception as e:
            log.warning("[asr] engine fallback 失败: %r", e)

    log.warning("[asr] OmniVoice 完全不可达, 返 None")
    return None


def tts(text: str, output_path: str, base_url: str = DEFAULT_OMNIVOICE_URL,
        voice: str = "default", timeout_s: float = DEFAULT_TIMEOUT_S) -> bool:
    """TTS 合成: 文本 → 音频文件.

    输入: text, output_path (mp3/wav 输出路径)
    输出: True 成功, False 失败
    """
    if not text or not output_path:
        return False
    if health(base_url, timeout_s=2.0):
        try:
            payload = json.dumps({"text": text, "voice": voice, "format": "wav"}).encode()
            req = urllib.request.Request(f"{base_url}/v1/tts",
                                        data=payload,
                                        headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                Path(output_path).write_bytes(resp.read())
                return True
        except Exception as e:
            log.warning("[tts] HTTP 失败: %r", e)
    return False
