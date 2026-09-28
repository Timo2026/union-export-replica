"""main.py - cnc-alchemist 子进程入口 (解决相对导入)"""
import subprocess, sys, os, json

ENTRY = os.path.join(os.path.dirname(__file__), "workflow.py")

def run(**kwargs):
    """子进程运行 workflow.py, 避免相对导入问题"""
    try:
        proc = subprocess.run(
            [sys.executable, ENTRY],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(__file__)
        )
        if proc.returncode == 0:
            return {"status": "success", "output": proc.stdout.strip()[:500]}
        else:
            return {"status": "error", "stderr": proc.stderr.strip()[:300]}
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "message": "执行超时(30s)"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    print(run())
