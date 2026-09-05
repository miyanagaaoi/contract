@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  CTMS setup - first run only (deps + database + demo data)
echo ============================================================

rem ---- locate python (py launcher first, then python) ----
set PY_CMD=
py -3 --version >nul 2>&1 && set "PY_CMD=py -3"
if not defined PY_CMD (
  python --version >nul 2>&1 && set "PY_CMD=python"
)
if not defined PY_CMD (
  echo [ERROR] Python not found. Install Python 3.11+ and retry.
  exit /b 1
)

rem ---- backend venv + deps ----
if not exist "app\.venv\Scripts\python.exe" (
  echo [1/4] create virtual env ...
  %PY_CMD% -m venv app\.venv
  if errorlevel 1 goto :err
)
echo [2/4] install backend deps ...
call app\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r app\requirements.txt
if errorlevel 1 goto :err

rem ---- database + demo data ----
echo [3/4] init database (with demo data if empty) ...
call app\.venv\Scripts\python.exe -m app.init_db --demo
if errorlevel 1 goto :err

rem ---- frontend deps ----
if not exist "web\node_modules" (
  echo [4/4] install frontend deps (first time, may take a few minutes) ...
  pushd web
  call npm install --no-audit --no-fund
  if errorlevel 1 ( popd & goto :err )
  popd
) else (
  echo [4/4] frontend deps already installed - skip
)

echo.
echo ============================================================
echo  Setup finished. Double-click  start-all.bat  to run CTMS.
echo  URL: http://localhost:5173   (backend API: :8000)
echo ============================================================
exit /b 0

:err
echo.
echo [ERROR] Setup failed. Check messages above, then re-run.
exit /b 1
