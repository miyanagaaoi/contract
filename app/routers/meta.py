"""字典元数据（供前端下拉选项）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..dicts import get_item_types
from ..models import ARRIVAL_STATUSES, CONTRACT_TYPES, CURRENCIES, DEFAULT_TAGS, STATUSES

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("")
def meta(db: Session = Depends(get_db)):
    from .export import export_column_meta  # 避免模块级环依赖

    export = export_column_meta()
    return {
        "contract_types": CONTRACT_TYPES,
        "statuses": STATUSES,
        "arrival_statuses": ARRIVAL_STATUSES,
        "currencies": CURRENCIES,
        "default_tags": DEFAULT_TAGS,
        "item_types": get_item_types(db),
        "export_default_cols": export["default_cols"],
        "export_columns": export["columns"],
    }
