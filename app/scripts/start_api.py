"""start_api.py — 启动全模态上传端口 API 服务.

用法:
    python scripts/start_api.py                 # 前台, http://127.0.0.1:8900  (docs: /docs)
    python scripts/start_api.py --port 8900 --background
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8900)
    ap.add_argument("--background", action="store_true")
    a = ap.parse_args()

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [sys.executable, "-m", "uvicorn", "services.api_server:app",
           "--host", "127.0.0.1", "--port", str(a.port), "--log-level", "warning"]
    print("[start_api]", " ".join(cmd), "| cwd", _ROOT)

    if a.background:
        log = _ROOT / "data" / f"api_{a.port}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log, "ab")
        proc = subprocess.Popen(cmd, cwd=str(_ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT)
        print(f"[background] pid={proc.pid} log={log}")
        time.sleep(6)
        import urllib.request
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{a.port}/health", timeout=5) as r:
                print("[health]", r.read().decode()[:300])
        except Exception as e:
            print("[health] 未就绪:", repr(e)[:120])
        return 0
    return subprocess.call(cmd, cwd=str(_ROOT), env=env)


if __name__ == "__main__":
    sys.exit(main())
