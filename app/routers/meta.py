"""字典元数据（供前端下拉选项）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..dicts import (
    get_enabled_contract_types,
    get_item_types,
    get_subjects,
)
from ..models import ARRIVAL_STATUSES, CURRENCIES, STATUSES

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("")
def meta(db: Session = Depends(get_db)):
    from ..models import Contract
    from .export import export_column_meta  # 避免模块级环依赖

    export = export_column_meta()
    types = get_enabled_contract_types(db)
    labels = [t["label"] for t in types]
    # 历史遗留类型（旧"采购/销售/其他"等未入库标准化的值）补入筛选下拉
    distinct = db.query(Contract.type).filter(Contract.deleted == False).distinct()  # noqa: E712
    legacy = [r[0] for r in distinct if r[0] and r[0] not in labels]
    return {
        "contract_types": labels + sorted(legacy),
        "contract_type_defs": types,
        "subjects": get_subjects(db),
        "statuses": STATUSES,
        "arrival_statuses": ARRIVAL_STATUSES,
        "currencies": CURRENCIES,
        "item_types": get_item_types(db),
        "export_default_cols": export["default_cols"],
        "export_columns": export["columns"],
        "numbering_hint": "类型码+主体码+年份+月份+6位序号（如 PURZC202609000001，年度递增）",
    }
