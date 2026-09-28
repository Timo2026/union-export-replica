@echo off
chcp 65001 >nul
cd /d %~dp0

REM ── 版本号（单一来源：config\version.txt，禁止多处硬编码）──
set "APP_VERSION=12.0.0-fusion"
if exist "config\version.txt" for /f "usebackq delims=" %%V in ("config\version.txt") do set "APP_VERSION=%%V"

title Union·由你 - CNC AI Brain v%APP_VERSION%

REM ── 部署方式说明（本脚本为 Windows 本机一键启动，非容器）──
REM 本项目另提供多硬件厂商 Docker 部署，详见 docs/DEPLOY.md：
REM   纯 CPU      : docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build
REM   AMD ROCm    : docker compose -f docker-compose.yml -f docker-compose.rocm.yml up -d --build
REM   NVIDIA CUDA : docker compose -f docker-compose.yml -f docker-compose.cuda.yml up -d --build
REM   摩尔线程 MUSA（当前主后端）: 本机 vLLM MUSA → 见 MUSA_vLLM_启动.bat
REM     （config/models.json 已配置本机端点 127.0.0.1:32102 / :8000，
REM       本脚本启动的主服务会自动发现并优先调用该 MUSA 后端）

echo =======================================================
echo   Union·由你 — CNC AI 工艺大脑 v%APP_VERSION%
echo   启动完整版（支持 STEP 精确解析 + 云端AI + 本地模型）
echo =======================================================
echo.

:: ── 优先检测 conda step-render 环境（含 OCP/cadquery/cascadio）──
echo [1/3] 检测运行环境...
set "CONDA_PY=C:\Users\<user>\anaconda3\envs\step-render\python.exe"
if exist "%CONDA_PY%" (
    echo   [OK] 检测到 conda step-render 环境（推荐，支持 STEP 精确解析）
    set "PYTHON=%CONDA_PY%"
    set "USE_CONDA=1"
    goto :start_service
)

:: ── 回退: 项目独立虚拟环境 ──
set "VENV=%~dp0.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
if exist "%PYTHON%" (
    echo   [WARN] conda step-render 未找到，使用 .venv（STEP 解析将降级为 trimesh）
    set "USE_CONDA=0"
    goto :check_deps
)

:: ── 创建 venv ──
echo   [WARN] 虚拟环境不存在，正在创建 .venv...
python -m venv "%VENV%"
if %errorlevel% neq 0 (
    echo   [ERROR] 创建虚拟环境失败！请先安装 Python 3.10+
    pause
    exit /b 1
)
set "USE_CONDA=0"

:check_deps
echo.
echo [2/3] 检查依赖...
"%PYTHON%" -c "import fastapi" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [WARN] 依赖未安装，正在安装...
    set PYTHONUTF8=1
    "%VENV%\Scripts\pip.exe" install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
)
echo   [OK] 核心依赖就绪

:start_service
echo.
echo [3/3] 启动 cnc-ai-brain 主服务...
echo.
echo =======================================================
echo   [OK] 服务启动中...
echo   浏览器将自动打开: http://localhost:7862
echo   仪表盘:              http://localhost:7862/api/dashboard
echo   状态检查:            http://localhost:7862/api/health
echo   API 文档(Swagger):   http://localhost:7862/docs
echo =======================================================
echo.
echo   按 Ctrl+C 停止服务
echo.

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
start http://localhost:7862
"%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 7862 --reload

pause
