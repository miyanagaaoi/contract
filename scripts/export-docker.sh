#!/usr/bin/env bash
# CTMS single container build & export (Linux / macOS / 服务器)
set -e
cd "$(dirname "$0")/.."
echo "[1/2] build image ctms:1.0.0 ..."
docker build -t ctms:1.0.0 -f deploy/Dockerfile.single .
echo "[2/2] export tar ..."
docker save -o ctms-image-1.0.0.tar ctms:1.0.0
echo "done: $(pwd)/ctms-image-1.0.0.tar"
echo "  import: docker load -i ctms-image-1.0.0.tar"
echo "  run   : docker run -d --name ctms -p 8080:8000 -v ctms_data:/data ctms:1.0.0"
