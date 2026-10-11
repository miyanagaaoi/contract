#!/usr/bin/env bash
# CTMS single container build & export (Linux / macOS / 服务器)
# 用法：bash scripts/export-docker.sh [版本号]     默认 2.3.0
set -e
VERSION="${1:-2.3.0}"
cd "$(dirname "$0")/.."
echo "[1/2] build image ctms:${VERSION} ..."
docker build -t "ctms:${VERSION}" -f deploy/Dockerfile.single .
echo "[2/2] export tar ..."
docker save -o "ctms-image-${VERSION}.tar" "ctms:${VERSION}"
echo "done: $(pwd)/ctms-image-${VERSION}.tar"
echo "  import: docker load -i ctms-image-${VERSION}.tar"
echo "  run   : docker run -d --name ctms -p 8080:8000 -v ctms_data:/data ctms:${VERSION}"
echo "  with PG: add -e CTMS_DB_URL=postgresql+psycopg2://user:pwd@host:5432/ctms"
