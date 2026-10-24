@echo off
rem ============================================================
rem  CTMS quick start (single process: backend serves frontend)
rem
rem  Usage:
rem    start-all.bat             start (auto-build frontend if dist missing)
rem    start-all.bat --rebuild   force rebuild frontend, then start
rem    start-all.bat --no-open   start without opening the browser
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
set OPEN_BROWSER=1
set FORCE_REBUILD=0
for %%a in (%*) do (
  if /i "%%~a"=="--rebuild" set FORCE_REBUILD=1
  if /i "%%~a"=="--no-open" set OPEN_BROWSER=0
)

echo ============================================================
echo  CTMS quick start (single process: backend serves frontend)
echo  address : http://localhost:8000   (API + pages, 0.0.0.0 for LAN)
echo  stop    : scripts\stop-backend.bat
echo ============================================================

if not exist "app\.venv\Scripts\python.exe" (
  echo [ERROR] venv missing. Run setup.bat first.
  exit /b 1
)

rem ---------- frontend build ----------
set NEED_BUILD=0
if "%FORCE_REBUILD%"=="1" set NEED_BUILD=1
if not exist "web\dist\index.html" set NEED_BUILD=1
if "%NEED_BUILD%"=="1" (
  if not exist "web\node_modules" (
    echo [ERROR] web\node_modules missing. Run setup.bat first.
    exit /b 1
  )
  echo [build] building frontend ...
  pushd web
  call node node_modules\vite\bin\vite.js build
  popd
  if not exist "web\dist\index.html" (
    echo [ERROR] frontend build failed.
    exit /b 1
  )
)

rem ---------- backend :8000 ----------
powershell -NoProfile -Command "if(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue){exit 1}else{exit 0}" >nul 2>&1
if errorlevel 1 (
  rem port busy: verify it is CTMS via health endpoint
  powershell -NoProfile -Command "try{(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health -TimeoutSec 4).Content}catch{''}" > "%TEMP%\ctms_health.txt" 2>nul
  findstr /C:"CTMS" "%TEMP%\ctms_health.txt" >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] Port 8000 is occupied by ANOTHER program ^(not CTMS^).
    echo         Stop it first, or change the port in this script.
    echo         Check: netstat -ano ^| findstr :8000
    exit /b 1
  )
  echo [skip] CTMS already running on :8000
) else (
  echo [start] CTMS on :8000 ...
  start "CTMS :8000" cmd /k "cd /d %~dp0 && set CTMS_SERVE_STATIC=1&& set CTMS_WEB_DIST=%~dp0web\dist&& app\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
)

rem ---------- wait + health ----------
ping -n 7 127.0.0.1 >nul
powershell -NoProfile -Command "try{$c=(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health -TimeoutSec 5).Content; Write-Host ('[health] ' + $c)}catch{Write-Host '[health] FAILED - see the CTMS :8000 window'}" 2>nul

if "%OPEN_BROWSER%"=="1" start http://localhost:8000
echo.
echo Done. Frontend served by backend at http://localhost:8000
echo LAN users: http://THIS-PC-IP:8000 (while the window stays open)
echo.
echo Frontend changes need a rebuild: start-all.bat --rebuild
exit /b 0
