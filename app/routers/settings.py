"""系统设置/字典 API（MVP2：行项类型可配置列表）。"""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..dicts import get_item_types, set_item_types

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/item-types")
def read_item_types(db: Session = Depends(get_db)):
    return {"item_types": get_item_types(db)}


@router.put("/item-types")
def write_item_types(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        values = set_item_types(db, payload.get("values") or [])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "item_types": values}
