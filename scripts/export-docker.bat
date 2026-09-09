@echo off
rem ============================================================
rem  Build & export CTMS as a single importable docker image
rem  Run this on any machine with Docker; then copy the .tar to
rem  the target server and: docker load -i ctms-image-1.0.0.tar
rem ============================================================
cd /d "%~dp0\.."
echo [1/3] build image ctms:1.0.0 ...
docker build -t ctms:1.0.0 -f deploy\Dockerfile.single .
if errorlevel 1 goto :err

echo [2/3] export tar ...
docker save -o ctms-image-1.0.0.tar ctms:1.0.0
if errorlevel 1 goto :err

echo [3/3] done.
echo   import on server : docker load -i ctms-image-1.0.0.tar
echo   run               : docker run -d --name ctms -p 8080:8000 -v ctms_data:/data ctms:1.0.0
echo   (or: docker compose -f deploy\docker-compose.single.yml up -d)
exit /b 0
:err
echo [ERROR] docker build/save failed - check messages above.
exit /b 1
