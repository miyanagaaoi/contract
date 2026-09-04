"""字典元数据（供前端下拉选项）。"""
from fastapi import APIRouter

from ..models import ARRIVAL_STATUSES, CONTRACT_TYPES, CURRENCIES, DEFAULT_TAGS, STATUSES

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("")
def meta():
    return {
        "contract_types": CONTRACT_TYPES,
        "statuses": STATUSES,
        "arrival_statuses": ARRIVAL_STATUSES,
        "currencies": CURRENCIES,
        "default_tags": DEFAULT_TAGS,
    }
