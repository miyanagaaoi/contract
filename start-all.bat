@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  CTMS quick start (single process: backend serves frontend)
echo  address  : http://localhost:8000   (API + pages, 0.0.0.0 for LAN)
echo  stop     : close the opened console window
echo ============================================================

if not exist "app\.venv\Scripts\python.exe" (
  echo [ERROR] venv missing. Run setup.bat first.
  exit /b 1
)

rem ---- 前端产物检查：后端托管的是 web/dist 静态页，缺失时先构建一次 ----
if not exist "web\dist\index.html" (
  if not exist "web\node_modules" (
    echo [ERROR] web\node_modules missing. Run setup.bat first.
    exit /b 1
  )
  echo [build] web\dist missing - building frontend once ...
  pushd web
  call node node_modules\vite\bin\vite.js build
  popd
  if not exist "web\dist\index.html" (
    echo [ERROR] frontend build failed.
    exit /b 1
  )
)

rem ---- backend :8000（托管前端静态页）----
powershell -NoProfile -Command "if(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue){exit 1}else{exit 0}" >nul 2>&1
if errorlevel 1 (
  echo [skip] :8000 already in use - assume CTMS is running
) else (
  echo [start] CTMS on :8000 ...
  start "CTMS :8000" cmd /k "cd /d %~dp0 && set CTMS_SERVE_STATIC=1&& set CTMS_WEB_DIST=%~dp0web\dist&& app\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
)

rem ---- open browser after startup ----
timeout /t 6 /nobreak >nul
start http://localhost:8000
echo.
echo Done. Frontend is served by the backend at http://localhost:8000.
echo Colleagues on the LAN can open http://THIS-PC-IP:8000 while the window is open.
echo.
echo Note: to update the frontend after code changes, rebuild it first:
echo   cd web ^&^& node node_modules\vite\bin\vite.js build
exit /b 0
