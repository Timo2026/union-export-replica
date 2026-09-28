@echo off
REM ============================================================
REM  start_novastudio.bat — 一键启动 NovaStudio 4 工具 (v5.0.0)
REM  MinerU + ragflow + OmniVoice + SearXNG 全部本地嵌入
REM ============================================================

setlocal ENABLEEXTENSIONS
set PROJECT_ROOT=%~dp0..

echo ============================================================
echo   Union Manufacturing Export Agent v5.0.0
echo   NovaStudio 4 工具一键启动
echo ============================================================
echo.

REM ---- 1. SearXNG (本地 EXE) ----
echo [1/4] SearXNG (本地 EXE, port 8888) ...
start "SearXNG" "%PROJECT_ROOT%\tools\searxng\SearXNG.exe" --port 8888
echo       启动 OK: http://127.0.0.1:8888

REM ---- 2. OmniVoice ASR/TTS (Python embedded) ----
echo [2/4] OmniVoice (Python embedded, port 8082) ...
if exist "%PROJECT_ROOT%\tools\omnivoice\engine\python.exe" (
  start "OmniVoice" "%PROJECT_ROOT%\tools\omnivoice\engine\python.exe" ^
    "%PROJECT_ROOT%\tools\omnivoice\engine\Lib\site-packages\omnivoice\server.py" --port 8082
  echo       启动 OK: http://127.0.0.1:8082
) else (
  echo       [WARN] Python engine 未找到, 跳过
)

REM ---- 3. ragflow (Docker) ----
echo [3/4] ragflow (Docker, port 9380) ...
if exist "%PROJECT_ROOT%\tools\ragflow\docker\docker-compose.yml" (
  cd /d "%PROJECT_ROOT%\tools\ragflow\docker"
  docker compose up -d
  echo       启动 OK: http://127.0.0.1:9380
  cd /d "%PROJECT_ROOT%"
) else (
  echo       [WARN] docker-compose.yml 未找到, 跳过
)

REM ---- 4. MinerU (Docker) ----
echo [4/4] MinerU (Docker, port 8081) ...
if exist "%PROJECT_ROOT%\tools\mineru\docker\compose.yaml" (
  cd /d "%PROJECT_ROOT%\tools\mineru\docker"
  docker compose -f compose.yaml up -d
  echo       启动 OK: http://127.0.0.1:8081
  cd /d "%PROJECT_ROOT%"
) else (
  echo       [WARN] compose.yaml 未找到, 跳过
)

echo.
echo ============================================================
echo   NovaStudio 全部启动完成
echo   - SearXNG:  http://127.0.0.1:8888
echo   - OmniVoice: http://127.0.0.1:8082
echo   - ragflow:   http://127.0.0.1:9380
echo   - MinerU:    http://127.0.0.1:8081
echo ============================================================
echo.
echo 健康检查: python -m pytest tests/ -k novastudio -v
echo.
pause
endlocal
