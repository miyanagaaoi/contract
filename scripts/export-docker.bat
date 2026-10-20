@echo off
rem ============================================================
rem  Build & export CTMS images (V2.6 分功能打包)
rem  Usage: scripts\export-docker.bat [版本号]       默认 2.6.0
rem
rem  产物：
rem    ctms-browser-1.tar.gz           浏览器底座（**一次性**，~575MB gz，几乎不更新）
rem    ctms-image-<版本>-core.tar.gz   业务核心包（每次更新，~71MB gz）
rem    ctms-image-<版本>-sync.tar.gz   完整同步包（可选，仅离线全量交付时用）
rem
rem  服务器侧（推荐流程）：
rem    1) 首次：load 浏览器底座 + 核心包 → 本地组装同步镜像（离线、秒级）
rem         docker load -i ctms-browser-1.tar.gz
rem         docker load -i ctms-image-<版本>-core.tar.gz
rem         docker build -t ctms:<版本>-sync --build-arg CORE=ctms:<版本> -f deploy/Dockerfile.sync-local .
rem    2) 以后每次业务更新：只传核心包！
rem         docker load -i ctms-image-<新版本>-core.tar.gz
rem         docker build -t ctms:<新版本>-sync --build-arg CORE=ctms:<新版本> -f deploy/Dockerfile.sync-local .
rem         docker rm -f ctms ^&^& docker run -d --name ctms -p 8080:8000 -v ctms_data:/data ctms:<新版本>-sync
rem    （核心包 71MB，Chromium 层原地不动、不再传输）
rem ============================================================
setlocal
set VERSION=%~1
if "%VERSION%"=="" set VERSION=2.6.0
cd /d "%~dp0\.."

echo [1/7] build browser base ctms-browser:1 (固定底座) ...
docker build -t ctms-browser:1 -f deploy\Dockerfile.browser .
if errorlevel 1 goto :err
docker save ctms-browser:1 | gzip > ctms-browser-1.tar.gz

echo [2/7] build core image ctms:%VERSION% ...
docker build -t ctms:%VERSION% -f deploy\Dockerfile.single .
if errorlevel 1 goto :err

echo [3/7] build sync-local image (底座+核心组装，验证用) ...
docker build -t ctms:%VERSION%-sync --build-arg CORE=ctms:%VERSION% -f deploy\Dockerfile.sync-local .
if errorlevel 1 goto :err

echo [4/7] save core tar + gzip ...
docker save -o ctms-image-%VERSION%-core.tar ctms:%VERSION%
if errorlevel 1 goto :err
gzip -f -k ctms-image-%VERSION%-core.tar

echo [5/7] (可选) 全量同步包 —— 仅离线一次性交付需要，日常更新不用 ...
docker save -o ctms-image-%VERSION%-sync.tar ctms:%VERSION%-sync
if errorlevel 1 goto :err
gzip -f -k ctms-image-%VERSION%-sync.tar

echo [6/7] cleanup intermediate tars (keep .gz) ...
del /q ctms-image-%VERSION%-core.tar 2>nul
del /q ctms-image-%VERSION%-sync.tar 2>nul

echo [7/7] done.
echo   base  : ctms-browser-1.tar.gz              （一次性，~575MB）
echo   core  : ctms-image-%VERSION%-core.tar.gz     （每次更新，~71MB）
echo   sync  : ctms-image-%VERSION%-sync.tar.gz     （可选全量，~616MB）
echo.
echo 服务器组装同步镜像（离线，秒级）：
echo   docker build -t ctms:%VERSION%-sync --build-arg CORE=ctms:%VERSION% -f deploy/Dockerfile.sync-local .
exit /b 0
:err
echo [ERROR] docker build/save failed - check messages above.
exit /b 1
