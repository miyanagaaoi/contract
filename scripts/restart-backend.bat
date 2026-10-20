@echo off
rem ============================================================
rem  CTMS backend restart (auto-invoked after backend code changes)
rem  - kills whatever is listening on :8000
rem  - starts uvicorn (serving frontend static) in a new window
rem ============================================================
setlocal
cd /d "%~dp0.."

echo [restart] stopping old backend on :8000 ...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
ping -n 3 127.0.0.1 >nul

echo [restart] starting CTMS on :8000 ...
start "CTMS :8000" cmd /k "cd /d %~dp0.. && set CTMS_SERVE_STATIC=1&& set CTMS_WEB_DIST=%~dp0..\web\dist&& app\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

ping -n 7 127.0.0.1 >nul
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health -TimeoutSec 5).Content } catch { 'health check FAILED' }"
exit /b 0
