"""统一编号服务（V2.0，对应 `12-erp-system-design.md` §5.1；M1 先服务主数据，M2 起服务 8 类单据）。

规则来源：`app/dicts.get_number_rules()`（KV 字典 `number_rules`，可在系统管理页调整前缀与序号长度）。

口径：
- `reset="month"` → `{prefix}{YYYYMM}{seq:0N}`（单据默认按月重置）；
- `reset="never"` → `{prefix}{seq:0N}`（主数据默认不重置）；
- 序号 = 同前缀（含年月）下库内**最大序号 + 1**，因零填充等宽，字典序即数值序；
- 并发：SQLite 写串行 + 目标列唯一索引，冲突由调用方捕获 `IntegrityError` 后重试（`retry_on_conflict`）。

V1.0 合同编号（`app/numbering.py`：类型码+主体码+年月+序号）保持原样，不走本服务。
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..dicts import get_number_rules

_TRAILING_DIGITS = re.compile(r"(\d+)$")


def _target(kind: str):
    """kind → (ORM 模型, 编码列名)。M2 起在此登记 8 类单据。"""
    from ..models_master import Customer, Product, Supplier

    mapping = {
        "customer": (Customer, Customer.code),
        "supplier": (Supplier, Supplier.code),
        "product": (Product, Product.code),
    }
    if kind not in mapping:
        raise ValueError(f"未知编号类别：{kind}")
    return mapping[kind]


def _next_by_prefix(db: Session, model, column, *, prefix: str, reset: str,
                    seq_len: int, ref_date: date | None = None) -> str:
    """按前缀取号：查库内最大序号 +1（前缀与年月共同构成比较键）。"""
    pattern = f"{prefix}{ref_date:%Y%m}" if reset == "month" else prefix
    row = (
        db.query(column)
        .filter(column.like(f"{pattern}%"))
        .order_by(column.desc())
        .first()
    )
    seq = 1
    if row is not None and row[0]:
        matched = _TRAILING_DIGITS.search(str(row[0]))
        if matched:
            seq = int(matched.group(1)) + 1
    return f"{pattern}{str(seq).zfill(max(1, int(seq_len)))}"


def next_doc_no(db: Session, kind: str, ref_date: date | None = None) -> str:
    """取下一个编号（不落库）。`kind` ∈ `number_rules` 的键。"""
    rule = get_number_rules(db).get(kind)
    if rule is None:
        raise ValueError(f"未知编号类别：{kind}")
    model, column = _target(kind)
    prefix = str(rule.get("prefix") or "").strip().upper()
    return _next_by_prefix(
        db, model, column,
        prefix=prefix,
        reset=str(rule.get("reset") or "never"),
        seq_len=int(rule.get("seq_len") or 4),
        ref_date=ref_date,
    )


def next_product_code(db: Session, product_type) -> str:
    """物料编码：`{商品类型码}{序号}`；类型未维护 code 时退化为 `PT{类型id}`。

    对应 `number_rules["product"]`（prefix 为空 = 由商品类型决定前缀，T-V2-11）。
    """
    from ..models_master import Product

    rule = get_number_rules(db).get("product") or {}
    prefix = (getattr(product_type, "code", None) or "").strip().upper()
    if not prefix:
        prefix = f"PT{getattr(product_type, 'id', 0)}"
    return _next_by_prefix(
        db, Product, Product.code,
        prefix=prefix,
        reset=str(rule.get("reset") or "never"),
        seq_len=int(rule.get("seq_len") or 4),
    )


def next_party_code(db: Session, kind: str) -> str:
    """客户/供应商编码（`CUS0001` / `SUP0001`）。"""
    if kind not in ("customer", "supplier"):
        raise ValueError(f"未知往来单位类别：{kind}")
    return next_doc_no(db, kind)


def retry_on_conflict(db: Session, factory, *, attempts: int = 3):
    """执行 factory()：编码唯一索引冲突时回滚并重试（并发兜底）。

    `factory` 需自行 `db.commit()`（或由内部 service 提交）；重试次数用尽后抛出最后一次异常。
    """
    last: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            return factory()
        except IntegrityError as exc:      # 唯一索引冲突：重取编号再试
            db.rollback()
            last = exc
    assert last is not None
    raise last
