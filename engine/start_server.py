# -*- coding: utf-8 -*-
"""启动 uvicorn 服务并输出日志到文件"""
import subprocess, sys, os, time

os.environ['EXTERNAL_MODE'] = '1'
os.environ['PYTHONUTF8'] = '1'
os.environ['PYTHONIOENCODING'] = 'utf-8'

log_file = os.path.join(os.path.dirname(__file__), 'server_log.txt')
python_exe = os.environ.get('PYTHON_EXECUTABLE', sys.executable)
workdir = os.path.dirname(__file__)

with open(log_file, 'w', encoding='utf-8') as f:
    f.write(f"启动时间: {time.strftime('%H:%M:%S')}\n")
    f.flush()
    
    proc = subprocess.Popen(
        [python_exe, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '7862'],
        cwd=workdir,
        stdout=f, stderr=subprocess.STDOUT,
        env={**os.environ, 'PYTHONPATH': workdir},
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    )
    
    f.write(f"PID: {proc.pid}\n")
    f.flush()
    
    # 等待最多40秒
    for i in range(40):
        time.sleep(1)
        f.flush()
        # 检查服务是否就绪
        try:
            import urllib.request
            r = urllib.request.urlopen('http://127.0.0.1:7862/docs', timeout=2)
            f.write(f"\n服务就绪! (等待{i+1}秒)\n")
            f.flush()
            print(f"OK: 服务已就绪 (PID={proc.pid}, 等待{i+1}秒)")
            sys.exit(0)
        except Exception:
            pass
        
        # 检查进程是否已退出
        if proc.poll() is not None:
            f.write(f"\n进程已退出，返回码: {proc.returncode}\n")
            f.flush()
            print(f"FAIL: 进程已退出，返回码={proc.returncode}")
            sys.exit(1)
    
    f.write("\n超时：40秒内服务未就绪\n")
    f.flush()
    print("TIMEOUT: 40秒内服务未就绪")
    sys.exit(1)