@echo off
rem ============================================================
rem  CTMS backend restart (run after backend code changes)
rem  - stops the listener on :8000 ONLY if it is CTMS (app.main:app)
rem  - waits until the port is released, then starts uvicorn
rem  - health check with retries (up to ~30s)
rem ============================================================
setlocal enabledelayedexpansion
pushd "%~dp0.."
set ROOT=%CD%

echo [restart] checking listener on :8000 ...
set PID8000=
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:"TCP.*:8000 .*LISTENING"') do set PID8000=%%p

if defined PID8000 (
  set IS_CTMS=0
  for /f "delims=" %%c in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'ProcessId=%PID8000%').CommandLine"') do (
    echo %%c | findstr /C:"app.main:app" >nul 2>&1
    if not errorlevel 1 set IS_CTMS=1
  )
  if "!IS_CTMS!"=="0" (
    echo [ERROR] Port 8000 is occupied by a NON-CTMS process ^(pid=%PID8000%^).
    echo         Refusing to kill it. Stop it manually or change the port.
    popd
    exit /b 1
  )
  echo [restart] stopping CTMS pid=%PID8000% ...
  powershell -NoProfile -Command "Stop-Process -Id %PID8000% -Force -ErrorAction SilentlyContinue"
)

set PORT_FREE=0
for /l %%i in (1,1,10) do (
  powershell -NoProfile -Command "if(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue){exit 1}else{exit 0}" >nul 2>&1
  if not errorlevel 1 (
    set PORT_FREE=1
    goto :port_done
  )
  ping -n 2 127.0.0.1 >nul
)
:port_done
if "%PORT_FREE%"=="0" (
  echo [ERROR] Port 8000 is still in use after stop attempts. Abort.
  popd
  exit /b 1
)

echo [restart] starting CTMS on :8000 ...
start "CTMS :8000" cmd /k "cd /d %ROOT% && set CTMS_SERVE_STATIC=1&& set CTMS_WEB_DIST=%ROOT%\web\dist&& app\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

set HEALTH=0
for /l %%i in (1,1,10) do (
  powershell -NoProfile -Command "try{(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health -TimeoutSec 4).Content}catch{''}" > "%TEMP%\ctms_restart_health.txt" 2>nul
  findstr /C:"CTMS" "%TEMP%\ctms_restart_health.txt" >nul 2>&1
  if not errorlevel 1 (
    set HEALTH=1
    goto :health_ok
  )
  ping -n 4 127.0.0.1 >nul
)
:health_ok
if "!HEALTH!"=="1" (
  echo [health] OK
) else (
  echo [health] FAILED - see the CTMS :8000 window for errors
)
popd
exit /b 0
