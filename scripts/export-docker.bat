@echo off
rem ============================================================
rem  Build & export CTMS image (V2.6.2: core only)
rem  Usage: scripts\export-docker.bat [version]   default 2.6.2
rem
rem  Note: Playwright sync channel was removed in CR-026.
rem        Only the core image is built/exported (no Chromium layer).
rem
rem  Output:
rem    ctms-image-<version>-core.tar.gz   core image (~71MB gz)
rem
rem  Server side:
rem    docker load -i ctms-image-<version>-core.tar.gz
rem    docker compose -f deploy/docker-compose.synology.yml up -d
rem ============================================================
setlocal
set VERSION=%~1
if "%VERSION%"=="" set VERSION=2.6.2
cd /d "%~dp0\.."

echo [1/4] build core image ctms:%VERSION% ...
docker build -t ctms:%VERSION% -f deploy\Dockerfile.single .
if errorlevel 1 goto :err

echo [2/4] save core tar ...
docker save -o ctms-image-%VERSION%-core.tar ctms:%VERSION%
if errorlevel 1 goto :err

echo [3/4] gzip ...
gzip -f -k ctms-image-%VERSION%-core.tar
del /q ctms-image-%VERSION%-core.tar 2>nul

echo [4/4] done: ctms-image-%VERSION%-core.tar.gz
exit /b 0
:err
echo [ERROR] docker build/save failed - check messages above.
exit /b 1
