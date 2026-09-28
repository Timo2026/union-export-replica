"""tests/conftest.py — 全局 pytest fixtures.

保留原 fixture:
  - require_engine (session) — 无引擎时跳过依赖用例
  - engine_available() helper — 在线或离线引擎探测

新增 fixture (T1+):
  - isolated_creds (function, opt-in) — 测试隔离 GLOBAL credentials.json / gmail_settings.json
        让需要测 mail_puller / gmail_imap 的测试在独立 tmp_root 下跑,
        避免跨测污染 (凭据文件路径在 services.credentials 是模块级硬编码).
        用法: 在测试函数加 @pytest.mark.usefixtures("isolated_creds") 或参数化 isolated_creds.
"""
from __future__ import annotations

import os
import shutil
import sys
import urllib.request
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# LINK-3 双保险: pytest 进程内禁止 lifespan 自动拉起真实 mail 后台线程
# (真实 uvicorn 入口默认 autostart=1, 仍受 puller.is_enabled() 凭据门禁)
os.environ.setdefault("UEA_MAIL_AUTOSTART", "0")


# ============== 原 fixture: 引擎依赖 ==============
def _engine_online(url: str = "http://127.0.0.1:7862") -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _engine_src_present() -> bool:
    """离线 byte-identical 内核需要引擎源码 + .venv(OCP)。"""
    try:
        from services.config import load_settings
        s = load_settings(_ROOT)
        src = s.get("timo", {}).get("engine_src", "")
        py = s.get("timo", {}).get("engine_python", "")
        return bool(src) and Path(src).exists() and (not py or Path(py).exists())
    except Exception:
        return False


def engine_available() -> bool:
    """CI 无引擎/无 :7862 → False (相关用例 skip); 本机有引擎 → True。"""
    return _engine_online() or _engine_src_present()


@pytest.fixture(scope="session")
def require_engine():
    if not engine_available():
        pytest.skip("无制造内核(:7862 离线且引擎 .venv 缺失) — 跳过引擎依赖用例 (CI 环境)")


# ============== 新增 fixture: 凭据隔离 (T1+) ==============
GLOBAL_CRED = _ROOT / "data" / "credentials.json"
GLOBAL_GMAIL_SETTINGS = _ROOT / "data" / "gmail_settings.json"


@pytest.fixture
def tmp_root(tmp_path, isolated_creds):
    """独立 root 目录 (data/ 已创建) + 全局 credentials 隔离. 适用于 mail/gmail/puller 测试."""
    (tmp_path / "data").mkdir()
    return tmp_path


@pytest.fixture
def isolated_creds(tmp_path):
    """备份全局 credentials.json / gmail_settings.json, 临时清空, 测试后还原.

    mail_puller / gmail_imap 等用全局 CRED_FILE 硬编码路径的测试需此 fixture.
    """
    cred_backup = GLOBAL_CRED.read_bytes() if GLOBAL_CRED.exists() else None
    settings_backup = GLOBAL_GMAIL_SETTINGS.read_bytes() if GLOBAL_GMAIL_SETTINGS.exists() else None

    if GLOBAL_CRED.exists():
        GLOBAL_CRED.unlink()
    if GLOBAL_GMAIL_SETTINGS.exists():
        GLOBAL_GMAIL_SETTINGS.unlink()
    # 重置单例
    try:
        from services import mail_puller as mp
        mp.reset_global()
    except Exception:
        pass
    try:
        from services import gmail_imap as gi
        gi.reset_global()
    except Exception:
        pass

    yield tmp_path  # 给测试用

    # 还原全局
    if cred_backup is not None:
        GLOBAL_CRED.write_bytes(cred_backup)
    if settings_backup is not None:
        GLOBAL_GMAIL_SETTINGS.write_bytes(settings_backup)
    try:
        from services import mail_puller as mp
        mp.reset_global()
    except Exception:
        pass
    try:
        from services import gmail_imap as gi
        gi.reset_global()
    except Exception:
        pass
