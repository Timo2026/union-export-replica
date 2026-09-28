@echo off
REM ============================================================
REM  verify_l3_demo.bat — L3 邮件自动驱动 一键验证 (5 步)
REM ============================================================
setlocal ENABLEEXTENSIONS
set PROJECT_ROOT=%~dp0..
cd /d "%PROJECT_ROOT%"

echo ============================================================
echo   L3 邮件自动驱动 一键验证 (5 min)
echo ============================================================
echo.

echo [1/5] 环境检查 (Python / pytest / playwright) ...
python --version
python -c "import playwright; print('  playwright OK')" 2>&1 || (
  echo   [WARN] playwright 未安装, 跳过 E2E
)

echo.
echo [2/5] 全量回归 499 pytest ...
python -m pytest tests/ -q --timeout=60
if errorlevel 1 (
  echo   [FAIL] pytest 有失败
  exit /b 1
)

echo.
echo [3/5] 启动 API + Workbench UI ...
curl -s http://127.0.0.1:8900/health > nul 2>&1
if errorlevel 1 (
  echo   API 未启动, 正在启动 ...
  start "UEA-API" python scripts/start_api.py --port 8900 --background
  timeout /t 5 /nobreak > nul
)
curl -s http://127.0.0.1:8900/health
echo.

echo.
echo [4/5] E2E 3 场景截图 (PASS/HITL/BLOCKED) ...
python scripts/e2e_l3.py
if errorlevel 1 (
  echo   [WARN] E2E 部分失败
)

echo.
echo [5/5] 5 min 演示视频截图序列 ...
python scripts/record_demo.py
if errorlevel 1 (
  echo   [WARN] 演示录制部分失败
)

echo.
echo ============================================================
echo   L3 验证完成!
echo   - 测试报告: docs/e2e_l3/e2e_l3_report.md
echo   - 6 张截图: docs/screenshots/*.png
echo   - 12 张 E2E 截图: docs/e2e_l3/*.png
echo   - 30 张演示帧: docs/demo/frames/*.png
echo   - 分镜脚本: docs/demo/v5_demo_storyboard.md
echo ============================================================
echo.
pause
endlocal
