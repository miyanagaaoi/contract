"""系统级字典/设置存取（MVP2+3）。

KV 键：
- item_types        行项类型（MVP2 需求①）
- contract_types    合同类型（MVP3）：[{code,label,note,enabled}]，6 内置 + OTH(历史,enabled=false)
- subjects          我方主体码：[{code,name}]
无账号体系下的全局配置。
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .models import DEFAULT_ITEM_TYPES, KVSetting

KEY_ITEM_TYPES = "item_types"
KEY_CONTRACT_TYPES = "contract_types"
KEY_SUBJECTS = "subjects"

# ---- 默认合同类型（MVP3，代码固定，标签可编辑） ----
DEFAULT_CONTRACT_TYPES: list[dict] = [
    {"code": "SAL", "label": "销售/收入", "note": "面向客户收款", "enabled": True},
    {"code": "PUR", "label": "采购/支出", "note": "面向供应商付款", "enabled": True},
    {"code": "COO", "label": "合作/战略协议", "note": "不涉及直接金钱往来的框架协议", "enabled": True},
    {"code": "LAB", "label": "劳动/人事", "note": "员工劳动合同", "enabled": True},
    {"code": "FIN", "label": "金融/投融资", "note": "贷款、股权等", "enabled": True},
    {"code": "NDA", "label": "保密协议", "note": "单签或互签保密文件", "enabled": True},
    {"code": "OTH", "label": "其他(历史)", "note": "旧版“其他”历史数据，不参与自动编号", "enabled": False},
]

DEFAULT_SUBJECTS: list[dict] = [
    {"code": "ZC", "name": "智澈公司"},
    {"code": "YX", "name": "云羲公司"},
]

# 旧版类型标签 → 标准代码（历史数据自动映射）
LEGACY_TYPE_MAP = {"采购": "PUR", "销售": "SAL", "其他": "OTH"}
# 旧版主体名 → 代码
LEGACY_SUBJECT_MAP = {"智澈": "ZC", "云羲": "YX"}


def _load_list(db: Session, key: str, default: list) -> list:
    row = db.get(KVSetting, key)
    if row is None:
        return [dict(x) for x in default]
    try:
        value = json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return [dict(x) for x in default]
    return value if isinstance(value, list) else [dict(x) for x in default]


def _save_list(db: Session, key: str, values: list) -> list:
    row = db.get(KVSetting, key)
    if row is None:
        row = KVSetting(key=key, value="[]")
        db.add(row)
    row.value = json.dumps(values, ensure_ascii=False)
    db.commit()
    return values


# ---------- 行项类型 ----------
def get_item_types(db: Session) -> list[str]:
    return _normalize_str_list(_load_list(db, KEY_ITEM_TYPES, DEFAULT_ITEM_TYPES))


def _normalize_str_list(values) -> list[str]:
    out = []
    for v in values or []:
        s = str(v).strip()
        if s and s not in out:
            out.append(s)
    return out


def set_item_types(db: Session, values: list) -> list[str]:
    cleaned = _normalize_str_list(values)
    if not cleaned:
        raise ValueError("行项类型不能为空")
    return _save_list(db, KEY_ITEM_TYPES, cleaned)


# ---------- 合同类型 ----------
def get_contract_types(db: Session) -> list[dict]:
    types = _load_list(db, KEY_CONTRACT_TYPES, DEFAULT_CONTRACT_TYPES)
    # 保证结构完整
    normalized = []
    seen_codes = set()
    for t in types:
        code = str(t.get("code") or "").upper().strip()
        label = str(t.get("label") or "").strip()
        if not code or not label or code in seen_codes:
            continue
        seen_codes.add(code)
        normalized.append({
            "code": code,
            "label": label,
            "note": str(t.get("note") or ""),
            "enabled": bool(t.get("enabled", True)),
        })
    return normalized


def get_enabled_contract_types(db: Session) -> list[dict]:
    return [t for t in get_contract_types(db) if t["enabled"]]


def set_contract_types(db: Session, values: list[dict]) -> list[dict]:
    cleaned = []
    seen = set()
    for t in values or []:
        code = str(t.get("code") or "").upper().strip()
        label = str(t.get("label") or "").strip()
        if not code or not label or code in seen:
            continue
        seen.add(code)
        cleaned.append({"code": code, "label": label,
                        "note": str(t.get("note") or ""), "enabled": bool(t.get("enabled", True))})
    # 至少保留一个可用类型
    if not cleaned or not any(c["enabled"] for c in cleaned):
        raise ValueError("至少保留一个可用的合同类型")
    _save_list(db, KEY_CONTRACT_TYPES, cleaned)
    return cleaned


def type_code_of(db: Session, label_or_code: str) -> str | None:
    """按 label/code 解析标准类型代码；兼容旧版标签。"""
    s = (label_or_code or "").strip()
    if not s:
        return None
    for t in get_contract_types(db):
        if s.upper() == t["code"] or s == t["label"]:
            return t["code"]
    if s in LEGACY_TYPE_MAP:
        return LEGACY_TYPE_MAP[s]
    return None


def type_label_of(db: Session, code_or_label: str) -> str:
    """标准代码 → 类型标签；无法识别时原样返回（历史兜底显示）。"""
    s = (code_or_label or "").strip()
    for t in get_contract_types(db):
        if s.upper() == t["code"] or s == t["label"]:
            return t["label"]
    return s


# ---------- 我方主体码 ----------
def get_subjects(db: Session) -> list[dict]:
    subs = _load_list(db, KEY_SUBJECTS, DEFAULT_SUBJECTS)
    normalized = []
    seen = set()
    for s in subs:
        code = str(s.get("code") or "").upper().strip()
        name = str(s.get("name") or "").strip()
        if not code or not name or code in seen:
            continue
        seen.add(code)
        normalized.append({"code": code, "name": name})
    return normalized


def get_enabled_subjects(db: Session) -> list[dict]:
    return get_subjects(db)  # MVP：主体不设停用标记


def set_subjects(db: Session, values: list[dict]) -> list[dict]:
    cleaned = []
    seen = set()
    for s in values or []:
        code = str(s.get("code") or "").upper().strip()
        name = str(s.get("name") or "").strip()
        if not code or not name or code in seen:
            continue
        seen.add(code)
        cleaned.append({"code": code, "name": name})
    if not cleaned:
        raise ValueError("至少保留一个主体")
    _save_list(db, KEY_SUBJECTS, cleaned)
    return cleaned


def subject_code_of(db: Session, code_or_name: str) -> str | None:
    s = (code_or_name or "").strip()
    if not s:
        return None
    for sub in get_subjects(db):
        if s.upper() == sub["code"] or s == sub["name"]:
            return sub["code"]
    for k, v in LEGACY_SUBJECT_MAP.items():
        if k in s:
            return v
    return None
