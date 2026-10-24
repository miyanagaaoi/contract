@echo off
rem ============================================================
rem  CTMS setup - first install / environment check (V2.6.1 CR-016)
rem
rem  Usage:
rem    setup.bat          install deps + init DB (NO demo data)
rem    setup.bat demo     same, plus demo data (dev only)
rem    setup.bat check    check environment only (changes nothing)
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
set MODE=%~1
if /i "%MODE%"=="check" goto :check
if /i "%MODE%"=="demo" (set WITH_DEMO=1) else (set WITH_DEMO=0)

echo ============================================================
echo  CTMS setup - first run only (deps + database)
echo ============================================================

rem ---------- 1) locate python ----------
set PY_CMD=
py -3 --version >nul 2>&1 && set "PY_CMD=py -3"
if not defined PY_CMD (
  python --version >nul 2>&1 && set "PY_CMD=python"
)
if not defined PY_CMD (
  echo [ERROR] Python not found. Install Python 3.11+ and retry.
  exit /b 1
)

rem ---------- 2) require node ----------
where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not found. Install Node.js 20+ and retry.
  exit /b 1
)

rem ---------- 3) venv + backend deps (mirror configurable) ----------
if not exist "app\.venv\Scripts\python.exe" (
  echo [1/5] create virtual env ...
  %PY_CMD% -m venv app\.venv
  if errorlevel 1 goto :err
)
echo [2/5] install backend deps ...
if not defined PIP_INDEX_URL set "PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"
call app\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -i "%PIP_INDEX_URL%" -r app\requirements.txt
if errorlevel 1 goto :err

rem ---------- 4) playwright chromium (optional: invoice sync) ----------
echo [3/5] install Playwright Chromium (optional) ...
if not defined PLAYWRIGHT_DOWNLOAD_HOST set "PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/"
call app\.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 (
  echo [WARN] Playwright Chromium install failed - invoice auto-sync unavailable.
  echo        Bridge channel and invoice package import are NOT affected.
  echo        Retry: set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/
  echo               app\.venv\Scripts\python.exe -m playwright install chromium
)

rem ---------- 5) database (demo data only in demo mode) ----------
echo [4/5] init database ...
if "%WITH_DEMO%"=="1" (
  echo        demo data ENABLED
  call app\.venv\Scripts\python.exe -m app.init_db --demo
) else (
  echo        demo data DISABLED ^(use "setup.bat demo" to seed^)
  call app\.venv\Scripts\python.exe -m app.init_db
)
if errorlevel 1 goto :err

rem ---------- 6) frontend deps ----------
if not exist "web\node_modules" (
  echo [5/5] install frontend deps (may take a few minutes) ...
  pushd web
  call npm install --no-audit --no-fund
  if errorlevel 1 ( popd & goto :err )
  popd
) else (
  echo [5/5] frontend deps already installed - skip
)

echo.
echo ============================================================
echo  Setup finished. Double-click start-all.bat to run CTMS.
echo  URL: http://localhost:8000   (single process: API + pages)
echo ============================================================
exit /b 0

:check
echo ============================================================
echo  CTMS environment check (no changes)
echo ============================================================
set FAIL=0
py -3 --version >nul 2>&1
if not errorlevel 1 (
  echo [OK]   python:
  py -3 --version
) else (
  python --version >nul 2>&1
  if not errorlevel 1 (
    echo [OK]   python:
    python --version
  ) else (
    echo [MISS] python 3.11+
    set FAIL=1
  )
)
where node >nul 2>&1
if not errorlevel 1 (
  echo [OK]   node:
  node --version
) else (
  echo [MISS] node 20+
  set FAIL=1
)
if exist "app\.venv\Scripts\python.exe" (echo [OK]   venv: app\.venv) else (echo [MISS] venv - run setup.bat & set FAIL=1)
if exist "web\node_modules" (echo [OK]   web deps: web\node_modules) else (echo [MISS] web deps - run setup.bat & set FAIL=1)
if exist "web\dist\index.html" (echo [OK]   frontend build: web\dist) else (echo [WARN] web\dist missing - start-all.bat will build it)
if exist "app\.venv\Scripts\python.exe" (
  call app\.venv\Scripts\python.exe -c "import playwright" >nul 2>&1
  if not errorlevel 1 (echo [OK]   playwright package) else (echo [WARN] playwright missing - invoice auto-sync unavailable)
)
if exist ".env" (echo [OK]   .env found) else (echo [WARN] .env missing - defaults used ^(SQLite^))
echo.
if "%FAIL%"=="1" (echo Result: MISSING required components, fix [MISS] items above.) else (echo Result: environment ready, run start-all.bat.)
exit /b 0

:err
echo.
echo [ERROR] Setup failed. Check messages above, then re-run.
exit /b 1
