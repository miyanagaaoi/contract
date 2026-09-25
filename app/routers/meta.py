"""字典元数据（供前端下拉选项）。V2.0：要求登录。

说明：本接口是**登录即可**（不绑定具体权限点）——它被合同表单用作下拉字典，
若收紧到某个按钮权限，采购员将无法打开合同表单。字典的**维护**权限在
`/api/settings/*` 的写接口上（`system.dict.edit`）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..dicts import (
    get_enabled_contract_types,
    get_item_types,
    get_subjects,
)
from ..models import ARRIVAL_STATUSES, CURRENCIES, STATUSES
from ..models_auth import User
from ..services.permission_service import get_current_user

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("")
def meta(_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
