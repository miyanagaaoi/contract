"""CTMS 原型后端入口。

启动（开发）：
    cd app
    uvicorn main:app --host 127.0.0.1 --port 8000 --reload
或：python -m uvicorn main:app --host 0.0.0.0 --port 8000

说明：无登录/无角色（01 §2），依赖内网访问边界。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import APP_NAME, APP_VERSION, ensure_dirs
from .database import Base, SessionLocal, engine
from .init_db import seed_dicts
from .routers import contracts, health, meta, tags

__all__ = ["app"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动时确保建表与字典种子存在（幂等），演示数据用 python -m app.init_db --demo 追加。"""
    ensure_dirs()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_dicts(db)
    yield


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)

app.include_router(health.router)
app.include_router(meta.router)
app.include_router(tags.router)
app.include_router(contracts.router)


@app.get("/")
def root():
    return {"app": APP_NAME, "version": APP_VERSION, "docs": "/docs", "health": "/api/health"}
