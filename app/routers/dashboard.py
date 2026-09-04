"""首页看板 API（T9，对应 AC-08）。

- GET /api/dashboard：统计卡 + 质保即将到期(30 天内)/已到期 提醒清单
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Contract

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_WINDOW_DAYS = 30  # BR5：质保到期前 30 天进入"即将到期"


def _summary(c: Contract) -> dict:
    days_left = None
    if c.warranty_end:
        days_left = (c.warranty_end - date.today()).days
    return {
        "id": c.id,
        "contract_no": c.contract_no,
        "name": c.name,
        "party_a": c.party_a,
        "party_b": c.party_b,
        "owner_name": c.owner_name,
        "status": c.status,
        "warranty_end": c.warranty_end.isoformat() if c.warranty_end else None,
        "days_left": days_left,
    }


@router.get("")
def dashboard(db: Session = Depends(get_db)):
    today = date.today()
    horizon = today + timedelta(days=_WINDOW_DAYS)
    base = db.query(Contract).filter(Contract.deleted == False)  # noqa: E712
    pending = base.filter(Contract.has_warranty == True,  # noqa: E712
                          Contract.warranty_released == False,  # noqa: E712
                          Contract.warranty_end.isnot(None))

    expiring = pending.filter(Contract.warranty_end >= today, Contract.warranty_end <= horizon)
    expired = pending.filter(Contract.warranty_end < today)

    total = base.count()
    stats = {
        "total": total,
        "frameworks": base.filter(Contract.is_framework == True).count(),  # noqa: E712
        "with_warranty": base.filter(Contract.has_warranty == True).count(),  # noqa: E712
        "expiring_count": expiring.count(),
        "expired_count": expired.count(),
        "window_days": _WINDOW_DAYS,
    }
    return {
        "stats": stats,
        "expiring": [_summary(c) for c in expiring.order_by(Contract.warranty_end).limit(100)],
        "expired": [_summary(c) for c in expired.order_by(Contract.warranty_end).limit(100)],
    }
