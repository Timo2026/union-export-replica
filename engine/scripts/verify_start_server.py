"""整体验证用服务启动器：以 detached 子进程方式启动 app/main.py，
设置 EXTERNAL_MODE=1 启用门禁三态，日志写入 logs/verify_run.log + logs/verify_run_err.log。"""
import os
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
MAIN = ROOT / "app" / "main.py"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
OUT_LOG = LOG_DIR / "verify_run.log"
ERR_LOG = LOG_DIR / "verify_run_err.log"

for f in (OUT_LOG, ERR_LOG):
    if f.exists():
        f.unlink()

out_fp = open(OUT_LOG, "ab")
err_fp = open(ERR_LOG, "ab")

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

# 启用对外模式门禁三态
env = os.environ.copy()
env["EXTERNAL_MODE"] = "1"
env["PYTHONUTF8"] = "1"
env["PYTHONIOENCODING"] = "utf-8"

proc = subprocess.Popen(
    [str(PY), str(MAIN)],
    cwd=str(ROOT),
    stdout=out_fp,
    stderr=err_fp,
    stdin=subprocess.DEVNULL,
    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
    close_fds=True,
    env=env,
)

print(f"STARTED PID={proc.pid} with EXTERNAL_MODE=1")
sys.exit(0)
