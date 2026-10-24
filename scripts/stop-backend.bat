@echo off
rem ============================================================
rem  CTMS backend stop
rem  - only stops the listener on :8000 when it is CTMS itself
rem    (process command line contains app.main:app)
rem  - use "stop-backend.bat --force" to kill any listener on :8000
rem ============================================================
setlocal enabledelayedexpansion
set FORCE=0
if /i "%~1"=="--force" set FORCE=1

echo [stop] checking listener on :8000 ...
set PID8000=
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:"TCP.*:8000 .*LISTENING"') do set PID8000=%%p

if not defined PID8000 (
  echo [stop] nothing is listening on :8000.
  exit /b 0
)

set IS_CTMS=0
for /f "delims=" %%c in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'ProcessId=%PID8000%').CommandLine"') do (
  echo %%c | findstr /C:"app.main:app" >nul 2>&1
  if not errorlevel 1 set IS_CTMS=1
)

if "%IS_CTMS%"=="0" (
  if "%FORCE%"=="0" (
    echo [stop] Port 8000 is used by a process that is NOT CTMS ^(pid=%PID8000%^).
    echo        Refusing to kill it. Use "stop-backend.bat --force" if you really mean it.
    exit /b 1
  )
  echo [stop] --force: killing non-CTMS listener pid=%PID8000% ...
)

powershell -NoProfile -Command "Stop-Process -Id %PID8000% -Force -ErrorAction SilentlyContinue"

set FREE=0
for /l %%i in (1,1,10) do (
  powershell -NoProfile -Command "if(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue){exit 1}else{exit 0}" >nul 2>&1
  if not errorlevel 1 (
    set FREE=1
    goto :done
  )
  ping -n 2 127.0.0.1 >nul
)
:done
if "!FREE!"=="1" (
  echo [stop] port 8000 released.
) else (
  echo [stop] WARN: port 8000 still in use.
)
exit /b 0
