"""健康检查路由（T1 骨架验证用）。"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import APP_NAME, APP_VERSION
from ..database import get_db

router = APIRouter()


@router.get("/api/health")
def health(db: Session = Depends(get_db)):
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "app": APP_NAME, "version": APP_VERSION, "db": db_ok}
