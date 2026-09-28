@echo off
REM ===========================================================================
REM start_workbench.bat - Union Export Agent Workbench 离线演示启动脚本
REM ===========================================================================
REM 用途：比赛现场一键起 HTTP 服务（python -m http.server），打开浏览器即可
REM       演示 index.html (融合版 Workbench UI)
REM 端口：8901（避免与 API 服务 :8900 冲突）
REM ===========================================================================

setlocal
cd /d "%~dp0\.."

echo.
echo ============================================================
echo  Union Export Agent Workbench 离线演示启动器
echo ============================================================
echo.

REM 检测 Python
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 未检测到 python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM 检测端口占用
netstat -an | findstr :8901 >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [警告] 端口 8901 已被占用，将尝试 8902
    set PORT=8902
) else (
    set PORT=8901
)

echo [信息] 启动 HTTP 服务于 127.0.0.1:%PORT%
echo [信息] 工作目录: %CD%
echo.
echo [提示] 浏览器打开 http://127.0.0.1:%PORT%/index.html
echo [提示] 或 docs 版本 http://127.0.0.1:%PORT%/docs/workbench-v4-web.html
echo [提示] Ctrl+C 停止服务
echo ============================================================
echo.

REM 自动打开浏览器（5 秒延迟让服务先起）
start "" timeout 5 /nobreak >nul ^&^& start http://127.0.0.1:%PORT%/index.html

python -m http.server %PORT% --bind 127.0.0.1

endlocal