"""单据打印模板服务（V2.2，BR-V2.2-02）。

背景：打印 HTML 原先由 `print_service` 用**硬编码**的标题、字段顺序与列清单拼出，
业务上想让「入库单」的表头把"仓库"提到最前、或者把"制单"签字栏改成"仓管员签字"，
都必须改代码发版。

本模块把打印版面抽成**按单据类型**保存的模板配置（`PrintTemplate.config`，JSON 文本），
管理员在「系统管理 → 打印模板」里可视化调整：

- **文字信息**：标题 / 副标题 / 页脚、表头字段标签、行项列标签、签字栏文字；
- **组件放置位置**：四个区块（标题区 / 表头信息 / 行项明细 / 签字与备注）的整体顺序，
  表头字段与行项列的先后顺序、是否显示、是否独占整行，表头每行放几个字段；
- **组成部分显隐**（V2.5+）：标题区 / 表头信息 / 行项明细 / 签字与备注 / 页脚
  各自一个显示开关（`SHOW_KEYS`，默认全开）——"只打行项与签字"这类要求不必再删区块。

设计要点：
1. **默认值即代码**：`default_config()` 由目录常量生成，与旧版硬编码版面**逐项一致**；
   数据库里没有记录时直接返回默认值 —— 不要求管理员先去"初始化模板"。
2. **读取即合并**：`get_config()` 把库里存的（可能来自旧版本）与默认值合并，
   新增可配置项时老模板不会 KeyError，缺失项自动回落默认。
3. **写入即校验**：未知字段/列 key 会被丢弃，顺序按提交的数组为准，
   非法值（例如表头列数为 0）回落默认 —— 模板坏了会打印不出来，不能让前端随便写库。
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..models_doc import PrintTemplate

# ==================== 目录（唯一真源） ====================

#: 可配置模板的单据类型（与 `DOC_MODELS` 对齐，含 V2.1 新增的调拨单）
KINDS: list[tuple[str, str]] = [
    ("purchase_request", "采购申请单"),
    ("purchase_order", "采购单"),
    ("sales_request", "销售申请单"),
    ("sales_order", "销售订单"),
    ("stock_in", "入库单"),
    ("stock_out", "出库单"),
    ("stock_take", "盘点单"),
    ("stock_transfer", "调拨单"),
    # V2.5：财务域（付款凭单 / 收款凭单 / 发票）—— 表头字段与签字栏可配；
    # 行项明细区块对表头型单据无行可印（核销明细的专属版式留待后续，见 docs/32 §4）
    ("payment", "付款单"),
    ("receipt", "收款单"),
    ("invoice", "发票"),
]
KIND_LABELS: dict[str, str] = dict(KINDS)

#: 打印区块：(key, 名称, 说明)。顺序即默认版面顺序。
BLOCKS: list[tuple[str, str, str]] = [
    ("title", "标题区", "单据名称与副标题"),
    ("head", "表头信息", "单号 / 日期 / 往来单位等字段表"),
    ("items", "行项明细", "物料明细表与合计行"),
    ("sign", "签字与备注", "审批信息、备注、作废说明与签字栏"),
]
BLOCK_LABELS: dict[str, str] = {key: label for key, label, _ in BLOCKS}

#: 5 个**组成部分**的显示开关（key, 名称, 说明），默认全开。
#: 前 4 个直接由 `BLOCKS` 派生（名称与说明完全一致，避免两处文案漂移），页脚单独一项。
#: 与「区块顺序」（`blocks`）正交：顺序决定谁在上面、开关决定**印不印**——
#: 管理员常要"只打行项与签字"，此前只能靠清空标题文字/页脚来变相实现（表头字段仍会印）。
SHOW_KEYS: list[tuple[str, str, str]] = [
    (f"show_{key}", label, note) for key, label, note in BLOCKS
] + [
    ("show_footer", "页脚", "页面最下方的一行说明"),
]
SHOW_KEY_LABELS: dict[str, str] = {key: label for key, label, _ in SHOW_KEYS}
#: 区块 key → 显示开关 key（`print_service` 渲染时按此跳过整块）
BLOCK_SHOW_KEYS: dict[str, str] = {"title": "show_title", "head": "show_head",
                                   "items": "show_items", "sign": "show_sign"}
#: 页脚开关（页脚不在 BLOCKS 里，单独一项）
SHOW_FOOTER_KEY = "show_footer"

#: 表头字段目录：(key, 默认标签, 内容说明)
HEAD_FIELD_CATALOG: list[tuple[str, str, str]] = [
    ("doc_no", "单据编号", "单据编号"),
    ("doc_date", "单据日期", "单据日期"),
    ("status", "状态", "单据状态"),
    ("subject", "签约公司", "我方签约主体（V2.3；无该字段或未填写的单据自动跳过）"),
    ("supplier", "供应商", "采购方向往来单位（无该字段的单据自动跳过）"),
    ("customer", "客户", "销售方向往来单位"),
    ("warehouse", "仓库", "表头仓库（默认显示 主体码-仓库名）"),
    ("from_warehouse", "调出仓库", "调拨单调出仓"),
    ("to_warehouse", "调入仓库", "调拨单调入仓"),
    ("from_subject", "调出单位", "调拨单调出仓库所属公司（V2.3）"),
    ("to_subject", "调入单位", "调拨单调入仓库所属公司（V2.3）"),
    ("in_type", "入库类型", "入库单业务类型"),
    ("out_type", "出库类型", "出库单业务类型"),
    ("take_type", "盘点方式", "全盘 / 抽盘"),
    ("expected_arrival_date", "预计到货", "采购单预计到货日期"),
    ("delivery_date", "交货日期", "销售订单交货日期"),
    ("contract_no", "关联合同", "关联合同编号"),
    ("handler", "经办人", "制单人"),
    ("source_doc_no", "来源单据", "下推来源单号"),
    ("generated_in_no", "盘盈入库单", "盘点生成的入库单"),
    ("generated_out_no", "盘亏出库单", "盘点生成的出库单"),
    # ---- V2.5：《付款申请单》版式字段（对齐纸质模板 docs/33；其它单据无这些字段会自动跳过） ----
    ("payee", "收款单位名称", "付款单收款方名称（其余单据跳过）"),
    ("payee_bank", "收款方开户银行", "付款单收款方开户银行"),
    ("payee_account", "收款方账号", "付款单收款方账号"),
    ("payer", "付款单位名称", "我方付款主体（取签约公司名称快照）"),
    ("payer_bank", "我方开户行", "付款单我方开户行"),
    ("category_l1", "一级分类", "经营/经济/行政/人力/投资/往来"),
    ("category_l2", "二级分类", "具体费用说明"),
    ("belong_period", "付款归属期", "如 2026-09 / 以前年度"),
    ("bank_purpose", "银行付款用途", "如 预付款 / 代付款"),
    ("pay_reason", "付款事由", "付款单的事由说明"),
    ("amount_cn", "金额（大写）", "由金额自动换算的财务大写"),
    ("plan_type", "计划内/外", "计划内 / 计划外"),
    # V2.6：我方公司税号（取自系统设置「我方公司」扩展属性；模板外项目默认关闭，docs/33 §6 口径）
    ("tax_no", "税号", "我方公司税号（需先在系统设置 → 我方公司维护）"),
]
HEAD_FIELD_LABELS: dict[str, str] = {k: v for k, v, _ in HEAD_FIELD_CATALOG}
HEAD_FIELD_NOTES: dict[str, str] = {k: note for k, _, note in HEAD_FIELD_CATALOG}

#: 行项列目录：(key, 默认标签, 默认是否显示)
ITEM_COLUMN_CATALOG: list[tuple[str, str, bool]] = [
    ("seq", "序号", True),
    ("product_code", "物料编码", True),
    ("product_name", "物料名称", True),
    ("spec", "规格型号", True),
    ("uom_name", "单位", True),
    ("qty", "数量", True),
    ("unit_price", "单价", True),
    ("amount", "金额", True),
    ("remark", "备注", True),
    # 盘点单专用列：默认关闭，由 default_config 对 stock_take 打开
    ("book_qty", "账面数量", False),
    ("actual_qty", "实盘数量", False),
    ("diff_qty", "差异", False),
    ("diff_reason", "差异说明", False),
]
ITEM_COLUMN_LABELS: dict[str, str] = {k: v for k, v, _ in ITEM_COLUMN_CATALOG}
_ITEM_COLUMN_DEFAULT_ON: set[str] = {k for k, _, on in ITEM_COLUMN_CATALOG if on}

#: 金额相关列（盘点单没有单价/金额，默认关闭）
MONEY_COLUMNS = {"unit_price", "amount"}
#: 差异相关列（仅盘点单默认打开）
TAKE_COLUMNS = {"book_qty", "actual_qty", "diff_qty", "diff_reason"}

CONFIG_VERSION = 1

DEFAULT_SUBTITLE = "CTMS · ERP 进销存"
DEFAULT_FOOTER = "本单据由系统生成，签字后作为业务凭证留存。"
DEFAULT_SIGN_LABELS = ["制单", "审核", "仓管", "领料/收货"]
# 《付款申请单》纸质模板的签字栏（V2.5）
PAYMENT_SIGN_LABELS = ["经理", "部门负责人", "制单人", "财务", "财务负责人", "领款人"]
TAKE_SIGN_LABELS = ["制单", "盘点人", "审核", "仓管"]

#: 《付款申请单》纸质模板上**实际存在**的表头项（其余项默认关闭打印，可按需在模板页开启）
PAYMENT_TEMPLATE_KEYS: set[str] = {
    "payee", "payee_bank", "payee_account",          # 收款信息
    "payer", "payer_bank",                            # 付款信息（我方）
    "category_l1", "category_l2", "belong_period", "bank_purpose", "pay_reason",
    "amount_cn", "plan_type", "doc_date", "supplier", "remark",
}

#: 表头每行字段数可选值
HEAD_COLUMN_CHOICES = [1, 2, 3]


def _kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, "单据")


# ==================== 默认配置 ====================


def default_config(kind: str) -> dict:
    """生成某类单据的**出厂**打印模板（与 V2.1 的硬编码版面逐项一致）。"""
    is_take = kind == "stock_take"
    # 付款单：**模板上没有的项目默认关闭打印**（可在「打印模板」页按需打开，
    # 打开后打印在《付款申请单》固定网格之后的「附加信息」区，不影响模板本体）
    head_fields = [
        {"key": key, "label": label,
         "enabled": (key in PAYMENT_TEMPLATE_KEYS) if kind == "payment" else True,
         "full": False}
        for key, label, _ in HEAD_FIELD_CATALOG
        if key != "tax_no"
    ]
    # 税号（V2.6）是模板外项目：所有单据默认关闭，管理员在模板页按需打开（docs/33 §6 口径）
    head_fields.append({"key": "tax_no", "label": "税号", "enabled": False, "full": False})
    item_columns = []
    for key, label, _default_on in ITEM_COLUMN_CATALOG:
        if key in TAKE_COLUMNS:
            enabled = is_take
        elif key in MONEY_COLUMNS:
            enabled = not is_take
        else:
            enabled = True
        if kind == "payment":
            enabled = False          # 付款单没有物料行项，行项列默认全关
        item_columns.append({"key": key, "label": label, "enabled": enabled})
    return {
        "version": CONFIG_VERSION,
        # 《付款申请单》纸质模板的标题与系统单据名不同（系统内叫"付款单"）
        "title": "付款申请单" if kind == "payment" else _kind_label(kind),
        # 模板外内容默认不印（付款申请单纸质模板没有副标题/页脚/打印时间）
        "subtitle": "" if kind == "payment" else DEFAULT_SUBTITLE,
        "footer": "" if kind == "payment" else DEFAULT_FOOTER,
        "show_printed_at": False if kind == "payment" else True,
        "head_columns": 2,
        "blocks": [key for key, _, _ in BLOCKS],
        "head_fields": head_fields,
        "item_columns": item_columns,
        "signature_labels": list(PAYMENT_SIGN_LABELS if kind == "payment"
                                 else TAKE_SIGN_LABELS if is_take
                                 else DEFAULT_SIGN_LABELS),
        "show_approval": True,
        "show_remarks": True,
        "show_void_note": True,
        # V2.5+：5 个组成部分的显示开关，默认全开（与旧版版面逐项一致）
        **{key: True for key, _, _ in SHOW_KEYS},
    }


# ==================== 归一化（读写共用） ====================


def _clean_text(value, default: str, limit: int = 200) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text[:limit] if text else default


def _normalize_blocks(raw) -> list[str]:
    """区块顺序：只保留已知 key，并按目录补齐遗漏的（保证四个区块都在，不会漏印）。"""
    valid = [key for key, _, _ in BLOCKS]
    picked: list[str] = []
    for item in (raw if isinstance(raw, list) else []):
        key = str(item)
        if key in valid and key not in picked:
            picked.append(key)
    picked.extend(key for key in valid if key not in picked)
    return picked


def _normalize_head_fields(raw, kind: str) -> list[dict]:
    """表头字段：**以提交的列表为准**（顺序即版面顺序），未知 key 丢弃。

    列表里没提到的字段 = 使用者主动移除了它，渲染时不再出现；
    只有整个列表缺失/为空时才回落出厂清单（避免误存出空表头）。
    """
    base = default_config(kind)["head_fields"]
    by_key = {row["key"]: dict(row) for row in base}
    if not isinstance(raw, list) or not raw:
        return base
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        if key not in by_key or key in seen:
            continue
        seen.add(key)
        row = by_key[key]
        if "label" in item:
            row["label"] = _clean_text(item.get("label"), row["label"], 32)
        if "enabled" in item:
            row["enabled"] = bool(item.get("enabled"))
        if "full" in item:
            row["full"] = bool(item.get("full"))
        out.append(row)
    return out or base


def _normalize_item_columns(raw, kind: str) -> list[dict]:
    """行项列：同表头字段，以提交的列表为准（顺序即列顺序）。"""
    base = default_config(kind)["item_columns"]
    by_key = {row["key"]: dict(row) for row in base}
    if not isinstance(raw, list) or not raw:
        return base
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        if key not in by_key or key in seen:
            continue
        seen.add(key)
        row = by_key[key]
        if "label" in item:
            row["label"] = _clean_text(item.get("label"), row["label"], 32)
        if "enabled" in item:
            row["enabled"] = bool(item.get("enabled"))
        out.append(row)
    if not out:
        return base
    # 至少保留一列，否则明细表会退化成空表
    if not any(col["enabled"] for col in out):
        for col in out:
            if col["key"] in _ITEM_COLUMN_DEFAULT_ON:
                col["enabled"] = True
                break
        else:
            out[0]["enabled"] = True
    return out


def _normalize_sign_labels(raw, kind: str) -> list[str]:
    default = default_config(kind)["signature_labels"]
    if not isinstance(raw, list):
        return default
    labels = [_clean_text(item, "", 24) for item in raw]
    labels = [text for text in labels if text][:8]
    return labels or default


def normalize_config(kind: str, raw) -> dict:
    """把任意来源的配置归一成**完整且合法**的模板（未知键丢弃、缺项回落默认）。"""
    base = default_config(kind)
    if not isinstance(raw, dict):
        return base
    try:
        head_columns = int(raw.get("head_columns", base["head_columns"]))
    except (TypeError, ValueError):
        head_columns = base["head_columns"]
    if head_columns not in HEAD_COLUMN_CHOICES:
        head_columns = base["head_columns"]
    return {
        "version": CONFIG_VERSION,
        "title": _clean_text(raw.get("title"), base["title"], 64),
        "subtitle": _clean_text(raw.get("subtitle"), base["subtitle"], 96),
        "show_printed_at": bool(raw.get("show_printed_at", base["show_printed_at"])),
        "footer": _clean_text(raw.get("footer"), base["footer"], 200),
        "head_columns": head_columns,
        "blocks": _normalize_blocks(raw.get("blocks")),
        "head_fields": _normalize_head_fields(raw.get("head_fields"), kind),
        "item_columns": _normalize_item_columns(raw.get("item_columns"), kind),
        "signature_labels": _normalize_sign_labels(raw.get("signature_labels"), kind),
        "show_approval": bool(raw.get("show_approval", base["show_approval"])),
        "show_remarks": bool(raw.get("show_remarks", base["show_remarks"])),
        "show_void_note": bool(raw.get("show_void_note", base["show_void_note"])),
        # 旧模板里没有这些键 → 回落默认 True（向后兼容：升级后版面不变）
        **{key: bool(raw.get(key, base[key])) for key, _, _ in SHOW_KEYS},
    }


# ==================== 读写 ====================


def _load_row(db: Session, kind: str) -> PrintTemplate | None:
    return db.query(PrintTemplate).filter(PrintTemplate.kind == kind).first()


def _config_hash(cfg: dict) -> str:
    return json.dumps(cfg, ensure_ascii=False, sort_keys=True)


def get_config(db: Session, kind: str) -> dict:
    """取某类单据的生效模板：库里存过就用库里的（与默认值合并），否则用默认值。"""
    if kind not in KIND_LABELS:
        raise ValueError(f"未知单据类型：{kind}")
    row = _load_row(db, kind)
    if row is None:
        return default_config(kind)
    try:
        stored = json.loads(row.config or "{}")
    except (TypeError, ValueError):
        stored = {}
    return normalize_config(kind, stored)


def get_stored_config(db: Session, kind: str) -> dict | None:
    """取库里**原样保存**的模板（无记录返回 None）；用于判断"是否已自定义"。"""
    row = _load_row(db, kind)
    if row is None:
        return None
    try:
        return json.loads(row.config or "{}")
    except (TypeError, ValueError):
        return None


def factory_config(kind: str) -> dict:
    """出厂模板（前端"恢复默认"按钮的对照值）。"""
    if kind not in KIND_LABELS:
        raise ValueError(f"未知单据类型：{kind}")
    return default_config(kind)


def is_customized(db: Session, kind: str) -> bool:
    """是否与出厂模板不同（前端据此显示"已自定义"标记）。"""
    stored = get_stored_config(db, kind)
    if stored is None:
        return False
    return _config_hash(normalize_config(kind, stored)) != _config_hash(default_config(kind))


def save_config(db: Session, kind: str, raw, user=None) -> dict:
    """保存模板（整表替换语义）。返回归一化后的完整配置。"""
    if kind not in KIND_LABELS:
        raise ValueError(f"未知单据类型：{kind}")
    cfg = normalize_config(kind, raw)
    row = _load_row(db, kind)
    if row is None:
        row = PrintTemplate(kind=kind, config="{}")
        db.add(row)
    row.config = json.dumps(cfg, ensure_ascii=False)
    row.updated_by = getattr(user, "id", None)
    row.updated_by_name = getattr(user, "real_name", None)
    db.commit()
    db.refresh(row)
    return cfg


def reset_config(db: Session, kind: str) -> dict:
    """恢复出厂模板（删除自定义记录）。"""
    if kind not in KIND_LABELS:
        raise ValueError(f"未知单据类型：{kind}")
    row = _load_row(db, kind)
    if row is not None:
        db.delete(row)
        db.commit()
    return default_config(kind)


def _fmt_template(db: Session, kind: str) -> dict:
    row = _load_row(db, kind)
    return {
        "kind": kind,
        "label": _kind_label(kind),
        "customized": is_customized(db, kind),
        "updated_at": (row.updated_at.isoformat(sep=" ", timespec="seconds")
                       if row is not None and row.updated_at else None),
        "updated_by_name": row.updated_by_name if row is not None else None,
        "config": get_config(db, kind),
        "factory": default_config(kind),
    }


def list_templates(db: Session) -> list[dict]:
    """全部单据类型的模板概览（系统管理页左侧列表用）。"""
    return [_fmt_template(db, kind) for kind, _ in KINDS]


def get_template_detail(db: Session, kind: str) -> dict:
    """单个单据类型的模板明细（含出厂默认值，供前端做"恢复默认"对照）。"""
    if kind not in KIND_LABELS:
        raise ValueError(f"未知单据类型：{kind}")
    return _fmt_template(db, kind)


def template_meta() -> dict:
    """模板编辑界面的元数据：区块、字段、列目录（前端不重复硬编码这些清单）。"""
    return {
        "kinds": [{"kind": kind, "label": label} for kind, label in KINDS],
        "blocks": [{"key": key, "label": label, "note": note} for key, label, note in BLOCKS],
        # 5 个组成部分的显示开关（前端"显示开关"区渲染用；文案与区块说明保持一致）
        "show_keys": [{"key": key, "label": label, "note": note}
                      for key, label, note in SHOW_KEYS],
        "head_fields": [{"key": key, "label": label, "note": note}
                        for key, label, note in HEAD_FIELD_CATALOG],
        "item_columns": [{"key": key, "label": label}
                         for key, label, _ in ITEM_COLUMN_CATALOG],
        "head_column_choices": HEAD_COLUMN_CHOICES,
        "max_sign_labels": 8,
    }
