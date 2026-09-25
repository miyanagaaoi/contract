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


# ---------- V2.0：系统参数（KV 字典，键 sys_params） ----------

KEY_SYS_PARAMS = "sys_params"
KEY_NUMBER_RULES = "number_rules"

DEFAULT_SYS_PARAMS: dict = {
    "warranty_window_days": 30,     # 质保到期提醒窗口（天）
    "allow_negative_stock": False,  # 是否允许负库存（O1 默认不允许）
    "allow_self_approve": False,    # 是否允许创建人自审（O6 默认不允许）
    "default_qty_decimals": 2,      # 数量默认小数位（物料单位可覆盖）
    "default_price_decimals": 4,    # 单价小数位
    "money_decimals": 2,            # 金额小数位
    "pwd_min_length": 8,            # 密码最小长度
}

# 参数取值类型（set 时按此归一，防脏值）
_SYS_PARAM_TYPES: dict[str, type] = {
    "warranty_window_days": int,
    "allow_negative_stock": bool,
    "allow_self_approve": bool,
    "default_qty_decimals": int,
    "default_price_decimals": int,
    "money_decimals": int,
    "pwd_min_length": int,
}

# 参数元数据（系统管理页展示：中文名/类型/说明；T-V2-12）
SYS_PARAM_META: list[dict] = [
    {"key": "warranty_window_days", "label": "质保到期提醒窗口（天）", "type": "int",
     "note": "首页看板提前多少天提醒质保到期", "min": 1, "max": 365},
    {"key": "allow_negative_stock", "label": "允许负库存", "type": "bool",
     "note": "关闭时出库过账校验可用库存（建议保持关闭）"},
    {"key": "allow_self_approve", "label": "允许创建人自审", "type": "bool",
     "note": "关闭时单据创建人不能审核自己录入的单据"},
    {"key": "default_qty_decimals", "label": "数量默认小数位", "type": "int",
     "note": "新建物料时的数量精度默认值", "min": 0, "max": 4},
    {"key": "default_price_decimals", "label": "单价小数位", "type": "int",
     "note": "单价展示精度", "min": 0, "max": 4},
    {"key": "money_decimals", "label": "金额小数位", "type": "int",
     "note": "金额展示精度", "min": 0, "max": 2},
    {"key": "pwd_min_length", "label": "密码最小长度", "type": "int",
     "note": "改密与重置密码时的最小长度（≥6）", "min": 6, "max": 64},
]

# 单据与主数据编号规则（reset=month → 前缀+YYYYMM+序号；never → 前缀+序号）
DEFAULT_NUMBER_RULES: dict = {
    "purchase_request": {"prefix": "PR", "reset": "month", "seq_len": 6},
    "purchase_order": {"prefix": "PO", "reset": "month", "seq_len": 6},
    "sales_request": {"prefix": "SR", "reset": "month", "seq_len": 6},
    "sales_order": {"prefix": "SO", "reset": "month", "seq_len": 6},
    "stock_in": {"prefix": "IN", "reset": "month", "seq_len": 6},
    "stock_out": {"prefix": "OUT", "reset": "month", "seq_len": 6},
    "stock_take": {"prefix": "ST", "reset": "month", "seq_len": 6},
    "customer": {"prefix": "CUS", "reset": "never", "seq_len": 4},
    "supplier": {"prefix": "SUP", "reset": "never", "seq_len": 4},
    "product": {"prefix": "", "reset": "never", "seq_len": 4},   # 空前缀=按商品类型码生成
}

NUMBER_RULE_LABELS: dict[str, str] = {
    "purchase_request": "采购申请单", "purchase_order": "采购单",
    "sales_request": "销售申请单", "sales_order": "销售订单",
    "stock_in": "入库单", "stock_out": "出库单", "stock_take": "盘点单",
    "customer": "客户编码", "supplier": "供应商编码", "product": "物料编码",
}


def _load_dict(db: Session, key: str, default: dict) -> dict:
    """读 KV 字典：与默认值合并，保证调用方拿到的键完整。"""
    row = db.get(KVSetting, key)
    if row is None:
        return dict(default)
    try:
        value = json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return dict(default)
    if not isinstance(value, dict):
        return dict(default)
    merged = dict(default)
    merged.update(value)
    return merged


def _save_dict(db: Session, key: str, values: dict) -> dict:
    row = db.get(KVSetting, key)
    if row is None:
        row = KVSetting(key=key, value="{}")
        db.add(row)
    row.value = json.dumps(values, ensure_ascii=False)
    db.commit()
    return values


def _coerce_bool(raw) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    return str(raw).strip().lower() in ("1", "true", "yes", "on", "是")


def get_sys_params(db: Session) -> dict:
    """系统参数；首次读取时落库默认值，保证界面始终有值。"""
    if db.get(KVSetting, KEY_SYS_PARAMS) is None:
        return _save_dict(db, KEY_SYS_PARAMS, DEFAULT_SYS_PARAMS)
    return _load_dict(db, KEY_SYS_PARAMS, DEFAULT_SYS_PARAMS)


def set_sys_params(db: Session, values: dict) -> dict:
    """只接受已知参数键并按类型归一；未知键忽略，非法值报 422。"""
    current = get_sys_params(db)
    for key, raw in (values or {}).items():
        if key not in DEFAULT_SYS_PARAMS:
            continue
        caster = _SYS_PARAM_TYPES.get(key)
        try:
            if caster is bool:
                current[key] = _coerce_bool(raw)
            elif caster is int:
                current[key] = int(raw)
            else:
                current[key] = raw
        except (TypeError, ValueError):
            raise ValueError(f"参数 {key} 取值非法：{raw!r}")
    if current["pwd_min_length"] < 6:
        raise ValueError("密码最小长度不得小于 6")
    _save_dict(db, KEY_SYS_PARAMS, current)
    return current


def get_number_rules(db: Session) -> dict:
    """编号规则（逐项与默认结构对齐，避免缺键）。"""
    stored = _load_dict(db, KEY_NUMBER_RULES, DEFAULT_NUMBER_RULES)
    out: dict = {}
    for kind, default in DEFAULT_NUMBER_RULES.items():
        item = dict(default)
        raw = stored.get(kind) or {}
        if isinstance(raw, dict):
            item.update({k: v for k, v in raw.items() if k in default})
        out[kind] = item
    return out


def set_number_rules(db: Session, values: dict) -> dict:
    """仅允许调整前缀与序号长度；reset 策略固定（单据按月、主数据不重置）。"""
    current = get_number_rules(db)
    for kind, raw in (values or {}).items():
        if kind not in current or not isinstance(raw, dict):
            continue
        if "prefix" in raw:
            prefix = str(raw["prefix"] or "").strip().upper()
            # 仅允许 A~Z（中文/数字/符号会被 isalpha() 放过，需显式限定 ASCII）
            if prefix and not (prefix.isascii() and prefix.isalpha()):
                raise ValueError(f"{NUMBER_RULE_LABELS.get(kind, kind)} 前缀只能是大写字母")
            if len(prefix) > 4:
                raise ValueError(f"{NUMBER_RULE_LABELS.get(kind, kind)} 前缀最多 4 位")
            current[kind]["prefix"] = prefix
        if "seq_len" in raw:
            try:
                n = int(raw["seq_len"])
            except (TypeError, ValueError):
                raise ValueError(f"{NUMBER_RULE_LABELS.get(kind, kind)} 序号长度非法")
            if not 3 <= n <= 8:
                raise ValueError("序号长度需在 3~8 之间")
            current[kind]["seq_len"] = n
    _save_dict(db, KEY_NUMBER_RULES, current)
    return current
