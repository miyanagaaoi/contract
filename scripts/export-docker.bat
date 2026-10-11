@echo off
rem ============================================================
rem  Build & export CTMS as a single importable docker image
rem  Usage: scripts\export-docker.bat [版本号]      默认 2.3.0
rem  Run this on any machine with Docker; then copy the .tar to
rem  the target server and: docker load -i ctms-image-<版本>.tar
rem ============================================================
setlocal
set VERSION=%~1
if "%VERSION%"=="" set VERSION=2.3.0
cd /d "%~dp0\.."
echo [1/3] build image ctms:%VERSION% ...
docker build -t ctms:%VERSION% -f deploy\Dockerfile.single .
if errorlevel 1 goto :err

echo [2/3] export tar ...
docker save -o ctms-image-%VERSION%.tar ctms:%VERSION%
if errorlevel 1 goto :err

echo [3/3] done.
echo   import on server : docker load -i ctms-image-%VERSION%.tar
echo   run               : docker run -d --name ctms -p 8080:8000 -v ctms_data:/data ctms:%VERSION%
echo   with PostgreSQL   : add -e CTMS_DB_URL=postgresql+psycopg2://user:pwd@host:5432/ctms
echo   (or: docker compose -f deploy\docker-compose.single.yml up -d)
exit /b 0
:err
echo [ERROR] docker build/save failed - check messages above.
exit /b 1
