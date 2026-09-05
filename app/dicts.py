"""系统级字典/设置存取（MVP2 需求①：行项类型等为系统可配置列表）。

存储于 KVSetting('item_types')，无账号体系下的全局配置。
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .models import DEFAULT_ITEM_TYPES, KVSetting

KEY_ITEM_TYPES = "item_types"


def get_item_types(db: Session) -> list[str]:
    row = db.get(KVSetting, KEY_ITEM_TYPES)
    if row is None:
        return list(DEFAULT_ITEM_TYPES)
    try:
        value = json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return list(DEFAULT_ITEM_TYPES)
    return value if isinstance(value, list) and value else list(DEFAULT_ITEM_TYPES)


def set_item_types(db: Session, values: list) -> list[str]:
    cleaned: list[str] = []
    for v in values or []:
        s = str(v).strip()
        if s and s not in cleaned:
            cleaned.append(s)
    if not cleaned:
        raise ValueError("行项类型不能为空")
    row = db.get(KVSetting, KEY_ITEM_TYPES)
    if row is None:
        row = KVSetting(key=KEY_ITEM_TYPES, value="[]")
        db.add(row)
    row.value = json.dumps(cleaned, ensure_ascii=False)
    db.commit()
    return cleaned
