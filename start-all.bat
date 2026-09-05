@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  CTMS quick start
echo  backend  : http://localhost:8000   (API, 0.0.0.0 for LAN)
echo  frontend : http://localhost:5173   (open in browser)
echo  stop     : close the two opened console windows
echo ============================================================

if not exist "app\.venv\Scripts\python.exe" (
  echo [ERROR] venv missing. Run setup.bat first.
  exit /b 1
)
if not exist "web\node_modules" (
  echo [ERROR] node_modules missing. Run setup.bat first.
  exit /b 1
)

rem ---- backend :8000 ----
powershell -NoProfile -Command "if(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue){exit 1}else{exit 0}" >nul 2>&1
if errorlevel 1 (
  echo [skip] :8000 already in use - assume backend is running
) else (
  echo [start] backend on :8000 ...
  start "CTMS Backend :8000" cmd /k "cd /d %~dp0 && app\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
)

rem ---- frontend :5173 ----
powershell -NoProfile -Command "if(Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue){exit 1}else{exit 0}" >nul 2>&1
if errorlevel 1 (
  echo [skip] :5173 already in use - assume frontend is running
) else (
  echo [start] frontend on :5173 ...
  start "CTMS Frontend :5173" cmd /k "cd /d %~dp0web && npm run dev -- --host 0.0.0.0"
)

rem ---- open browser after startup ----
timeout /t 6 /nobreak >nul
start http://localhost:5173
echo.
echo Done. Frontend opens in the browser. Colleagues on the LAN can
echo open http://THIS-PC-IP:5173 while these two windows are open.
exit /b 0
