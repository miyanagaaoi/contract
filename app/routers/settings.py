"""系统设置/字典 API（MVP2 行项类型 + MVP3 合同类型/我方主体码；V2.0 接入权限）。

权限划分（V2.0）：
- **读接口**只要求登录：这些字典被合同表单作为下拉选项使用（收紧会导致开不了单）；
- **写接口**要求 `system.dict.edit`：字典维护是管理员动作。
"""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..dicts import (
    get_contract_types,
    get_item_types,
    get_subjects,
    set_contract_types,
    set_item_types,
    set_subjects,
)
from ..models_auth import User
from ..services.permission_service import get_current_user, require_perm

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _ok_or_422(fn, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ---- 行项类型（MVP2） ----
@router.get("/item-types")
def read_item_types(_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"item_types": get_item_types(db)}


@router.put("/item-types")
def write_item_types(payload: dict = Body(...),
                     _user: User = Depends(require_perm("system.dict.edit")),
                     db: Session = Depends(get_db)):
    return {"ok": True, "item_types": _ok_or_422(set_item_types, db, payload.get("values") or [])}


# ---- 合同类型（MVP3） ----
@router.get("/contract-types")
def read_contract_types(_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"contract_types": get_contract_types(db)}


@router.put("/contract-types")
def write_contract_types(payload: dict = Body(...),
                         _user: User = Depends(require_perm("system.dict.edit")),
                         db: Session = Depends(get_db)):
    return {"ok": True,
            "contract_types": _ok_or_422(set_contract_types, db, payload.get("contract_types") or [])}


# ---- 我方主体码（MVP3） ----
@router.get("/subjects")
def read_subjects(_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"subjects": get_subjects(db)}


@router.put("/subjects")
def write_subjects(payload: dict = Body(...),
                   _user: User = Depends(require_perm("system.dict.edit")),
                   db: Session = Depends(get_db)):
    return {"ok": True, "subjects": _ok_or_422(set_subjects, db, payload.get("subjects") or [])}
