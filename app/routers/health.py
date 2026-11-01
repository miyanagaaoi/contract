"""健康检查路由。

CR-033：在原有 `status/app/version/db` 基础上补充**可运维信息**（不暴露敏感数据）：
数据库延迟、上传目录剩余磁盘、进程运行时长、关键表行数。群晖/宝塔可直接用该接口做监控。
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ..config import APP_NAME, APP_VERSION, UPLOAD_DIR
from ..database import get_db

router = APIRouter()

_START_TS = time.time()


@router.get("/api/health")
def health(db: Session = Depends(get_db)):
    t0 = time.perf_counter()
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    disk_free_mb = None
    try:
        usage = shutil.disk_usage(Path(UPLOAD_DIR))
        disk_free_mb = round(usage.free / 1024 / 1024, 1)
    except OSError:
        pass

    counts: dict[str, int] = {}
    if db_ok:
        try:
            from ..models import Attachment, Contract
            from ..models_stock import StockLedger

            counts = {
                "contracts": int(db.query(func.count(Contract.id)).scalar() or 0),
                "ledger_rows": int(db.query(func.count(StockLedger.id)).scalar() or 0),
                "attachments": int(db.query(func.count(Attachment.id)).scalar() or 0),
            }
        except Exception:  # noqa: BLE001
            counts = {}

    degraded = (not db_ok) or (disk_free_mb is not None and disk_free_mb < 200)
    return {
        "status": "degraded" if degraded else "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "db": db_ok,                       # 兼容旧探针
        "db_latency_ms": latency_ms,
        "disk_free_mb": disk_free_mb,
        "uptime_seconds": int(time.time() - _START_TS),
        "counts": counts,
    }
