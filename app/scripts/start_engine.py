"""start_engine.py — 现场启动真实制造内核 cnc-ai-brain v12 :7862 (可复现).

用引擎自带 .venv python 启动完整 FastAPI (app.main:app), 提供:
  /api/health /api/conflict-check /api/quote /api/cnc-quick /api/upload /api/export ...

用法:
    python scripts/start_engine.py            # 前台启动 (Ctrl+C 停止)
    python scripts/start_engine.py --background   # 后台启动, 日志写 data/engine_7862.log

注: 即使不启动本服务, Union Agent 也能通过 TimoAdapter 的**离线内核桥**
    (子进程直接 import 真实 calc_quote + ConflictChecker) 得到 byte-identical 结果。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
from services.config import load_settings  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--background", action="store_true")
    ap.add_argument("--port", type=int, default=7862)
    a = ap.parse_args()

    s = load_settings(_ROOT)
    eng = s["timo"]["engine_src"]
    py = s["timo"]["engine_python"]
    if not Path(eng).exists():
        print(f"[ERR] engine_src 不存在: {eng}")
        return 2
    if not Path(py).exists():
        print(f"[WARN] engine_python 不存在, 回退系统 python: {py}")
        py = sys.executable

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # 完整服务: app.main:app (含 /api/conflict-check /api/quote)
    cmd = [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(a.port)]
    print("[start_engine]", " ".join(cmd))
    print("[cwd]", eng)

    if a.background:
        log = _ROOT / "data" / "engine_7862.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log, "ab")
        proc = subprocess.Popen(cmd, cwd=eng, env=env, stdout=fh, stderr=subprocess.STDOUT)
        print(f"[background] pid={proc.pid} log={log}")
        time.sleep(6)
        import urllib.request
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{a.port}/api/health", timeout=5) as r:
                print("[health]", r.read().decode()[:200])
        except Exception as e:
            print("[health] 尚未就绪:", repr(e)[:120])
        return 0
    else:
        return subprocess.call(cmd, cwd=eng, env=env)


if __name__ == "__main__":
    sys.exit(main())
