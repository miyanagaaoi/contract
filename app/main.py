"""CTMS 后端入口。

启动（开发）：
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

生产（单容器：由后端托管前端静态，env 开启）：
    CTMS_SERVE_STATIC=1  CTMS_WEB_DIST=/srv/web/dist  python -m uvicorn app.main:app ...

说明：无登录/无角色（01 §2），依赖内网/访问边界。
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from .config import APP_NAME, APP_VERSION, ensure_dirs
from .database import Base, SessionLocal, engine
from .db_migrate import ensure_schema_upgrades
from .init_db import seed_dicts
from .routers import attachments, contracts, dashboard, export, health, imports, meta, settings, tags

__all__ = ["app"]

# ---- 生产单容器：可选由后端托管前端静态页 ----
_WEB_DIST = Path(os.environ.get("CTMS_WEB_DIST") or "").resolve() if os.environ.get("CTMS_WEB_DIST") else None
_SERVE_STATIC = os.environ.get("CTMS_SERVE_STATIC", "0") == "1" and _WEB_DIST is not None and _WEB_DIST.is_dir()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动时确保建表与字典种子存在（幂等），演示数据用 python -m app.init_db --demo 追加。"""
    ensure_dirs()
    Base.metadata.create_all(bind=engine)
    ensure_schema_upgrades()
    with SessionLocal() as db:
        seed_dicts(db)
    yield


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)

app.include_router(health.router)
app.include_router(meta.router)
app.include_router(dashboard.router)
app.include_router(tags.router)
app.include_router(settings.router)
app.include_router(contracts.router)
app.include_router(attachments.router)
app.include_router(export.router)
app.include_router(imports.router)


def _index() -> FileResponse:
    return FileResponse(_WEB_DIST / "index.html")


@app.get("/")
def root():
    if _SERVE_STATIC:
        return _index()
    return {"app": APP_NAME, "version": APP_VERSION, "docs": "/docs", "health": "/api/health"}


if _SERVE_STATIC:
    from fastapi.staticfiles import StaticFiles

    # 静态资源（Vite 产物 assets/ 等），提升并发性能
    app.mount("/assets", StaticFiles(directory=_WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (_WEB_DIST / full_path).resolve()
        if full_path and candidate.is_file() and str(candidate).startswith(str(_WEB_DIST)):
            return FileResponse(candidate)
        return _index()
