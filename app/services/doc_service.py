"""单据公共服务（T-V2-17，对应 `12-erp-system-design.md` §4.4 与 §6.3）。

职责：状态机与通用动作、行项处理（物料快照 + 金额计算）、变更历史、统一格式化。

事务约定：本模块**不提交事务**，由路由层统一 `db.commit()`；
审核/反审核涉及过账时必须整体成功或整体回滚（AC-V2-21）。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..dicts import get_sys_params
from ..models import ChangeLog
from ..models_doc import DOC_KINDS, DOC_STATUS, EDITABLE_STATUSES
from ..models_master import Customer, Product, Supplier, Warehouse


class BusinessError(ValueError):
    """业务校验失败（路由层转 HTTP 422 + 中文提示）。

    继承 `ValueError` 以便统一被 `doc_routes._guard` 捕获并转 422。
    """


# ==================== 基础查询 ====================

def get_doc(db: Session, model, doc_id: int):
    doc = db.get(model, doc_id)
    if doc is None or doc.deleted:
        raise ValueError(f"{getattr(model, 'label', '单据')}不存在")
    return doc


def assert_editable(doc) -> None:
    if doc.status not in EDITABLE_STATUSES:
        raise ValueError(f"当前状态（{DOC_STATUS.get(doc.status, doc.status)}）不可编辑，请先反审核或作废")


def kind_of(doc) -> str:
    return getattr(doc, "doc_type", "")


# ==================== 变更历史 ====================

def log(db: Session, doc, field: str, old, new, note: str | None = None,
        source: str = "manual") -> None:
    """写单据变更历史（操作人取当前登录用户，`contract_id` 可空 —— M2 已放开约束）。"""
    user = (db.info or {}).get("user")
    db.add(ChangeLog(
        contract_id=doc.contract_id, field_name=field,
        old_value=None if old is None else str(old),
        new_value=None if new is None else str(new),
        note=note, source=source,
        operator_id=getattr(user, "id", None),
        operator_name=getattr(user, "real_name", None),
        object_type=doc.doc_type, object_id=doc.id,
    ))


def list_logs(db: Session, doc) -> list[dict]:
    rows = (db.query(ChangeLog)
            .filter(ChangeLog.object_type == doc.doc_type, ChangeLog.object_id == doc.id)
            .order_by(ChangeLog.id.desc()).all())
    return [{
        "id": r.id, "field_name": r.field_name, "old_value": r.old_value, "new_value": r.new_value,
        "note": r.note, "source": r.source,
        "operator_id": r.operator_id, "operator_name": r.operator_name,
        "created_at": r.created_at.isoformat(sep=" ", timespec="seconds") if r.created_at else None,
    } for r in rows]


# ==================== 行项处理 ====================

def _to_decimal(value, field: str, default: str = "0") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        raise ValueError(f"{field}必须是数字")


def _qty_decimals(uom_decimals: int | None, params: dict) -> int:
    return int(uom_decimals if uom_decimals is not None else params.get("default_qty_decimals", 2))


def apply_items(db: Session, doc, rows: list[dict] | None, *,
                default_warehouse_id: int | None = None) -> None:
    """整体替换行项：物料信息取**快照**，金额 = 数量 × 单价。

    - `rows` 为 None 表示不修改行项；空列表表示清空；
    - 数量精度按物料单位的 `decimals` 校验（AC-V2-11：单位不支持小数时录入 1.5 应被拒绝）。
    """
    if rows is None:
        return
    if not isinstance(rows, list):
        raise ValueError("行项格式非法")
    params = get_sys_params(db)
    doc.items.clear()
    seq = 0
    for raw in rows:
        seq += 1
        product_id = raw.get("product_id")
        if not product_id:
            raise ValueError(f"第 {seq} 行：请选择物料")
        product = db.get(Product, int(product_id))
        if product is None:
            raise ValueError(f"第 {seq} 行：物料不存在")
        if product.status != "enabled":
            raise ValueError(f"第 {seq} 行：物料「{product.name}」已停用")

        qty = _to_decimal(raw.get("qty"), "数量")
        if qty <= 0:
            raise ValueError(f"第 {seq} 行：数量必须大于 0")
        decimals = _qty_decimals(product.uom.decimals if product.uom else None, params)
        if decimals == 0 and qty != qty.to_integral_value():
            raise ValueError(
                f"第 {seq} 行：单位「{product.uom.name if product.uom else ''}」不支持小数，数量请填整数")
        if -qty.as_tuple().exponent > decimals:
            raise ValueError(f"第 {seq} 行：数量小数位超过单位允许的 {decimals} 位")

        warehouse_id = raw.get("warehouse_id") or default_warehouse_id
        warehouse = db.get(Warehouse, int(warehouse_id)) if warehouse_id else None
        if warehouse_id and warehouse is None:
            raise ValueError(f"第 {seq} 行：仓库不存在")

        unit_price = _to_decimal(raw.get("unit_price"), "单价")
        if unit_price < 0:
            raise ValueError(f"第 {seq} 行：单价不能为负数")
        amount = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        item = type(doc).items.property.mapper.class_()   # 对应的行项类
        item.seq = seq
        item.product_id = product.id
        item.product_code = product.code
        item.product_name = product.name
        item.spec = product.spec
        item.uom_name = product.uom.name if product.uom else None
        item.uom_decimals = decimals
        item.qty = qty
        item.unit_price = unit_price
        item.amount = amount
        item.warehouse_id = warehouse.id if warehouse else None
        item.warehouse_name = warehouse.name if warehouse else None
        item.remark = (str(raw.get("remark") or "").strip() or None)
        doc.items.append(item)

    total = sum((it.amount or Decimal("0")) for it in doc.items)
    if hasattr(doc, "total_amount"):
        doc.total_amount = total.quantize(Decimal("0.01"))


def total_amount_of(doc) -> Decimal:
    """行项金额合计（空行项时返回 0，注意 sum 的初值必须是 Decimal，否则 int 无 quantize）。"""
    return sum((it.amount or Decimal("0") for it in (doc.items or [])),
               Decimal("0")).quantize(Decimal("0.01"))


# ==================== 状态机动作 ====================

def _ensure_status(doc, allowed: set[str], action: str) -> None:
    if doc.status not in allowed:
        expected = " / ".join(DOC_STATUS.get(s, s) for s in allowed)
        raise ValueError(
            f"当前状态为「{DOC_STATUS.get(doc.status, doc.status)}」，{action}仅适用于：{expected}")


def submit(db: Session, doc, user) -> None:
    _ensure_status(doc, {"draft"}, "提交")
    if not doc.items:
        raise ValueError("单据没有行项，不能提交")
    doc.status = "submitted"
    doc.submitted_by = getattr(user, "id", None)
    doc.submitted_at = datetime.now()
    log(db, doc, "status", "draft", "submitted", note="提交审核")


def is_admin_user(user) -> bool:
    """V2.1（N6）：是否属于"管理员"，用于自审例外。

    判据（`23-v2.1-system-design.md` §8.2，口径经业务方确认）：
    - `is_superadmin=True`（内置初始管理员 `admin`）；或
    - 持有角色 code 为 `admin` / `superadmin` / **`sysadmin`** 的账号。

    注意：`admin` 是**账号名**而非角色 code，故不能靠用户名判断；`sysadmin`（系统管理员角色）
    已按业务确认**纳入**例外（`23` §13 第 6 项）——它与内置 `admin` 在语义上同属"管理员"，
    若只放开 `admin` 会造成"同为管理员却行为不一致"。
    """
    if getattr(user, "is_superadmin", False):
        return True
    codes = {getattr(r, "code", None) for r in (getattr(user, "roles", None) or [])}
    return bool({"admin", "superadmin", "sysadmin"} & codes)


def assert_can_approve(db: Session, doc, user) -> None:
    """审核前置校验：创建人不可自审（V2.1 起管理员例外，修订 AC-V2-15）。"""
    if doc.created_by != getattr(user, "id", None):
        return
    params = get_sys_params(db)
    if is_admin_user(user) or params.get("allow_self_approve", False):
        return
    raise ValueError("不能审核自己创建的单据（仅管理员可自审）")


def approve(db: Session, doc, user) -> None:
    _ensure_status(doc, {"submitted"}, "审核")
    assert_can_approve(db, doc, user)
    self_approved = doc.created_by == getattr(user, "id", None)
    doc.status = "approved"
    doc.approved_by = getattr(user, "id", None)
    doc.approved_at = datetime.now()
    log(db, doc, "status", "submitted", "approved",
        note="审核通过（管理员自审）" if self_approved else "审核通过")


def reject(db: Session, doc, reason: str, user) -> None:
    _ensure_status(doc, {"submitted"}, "驳回")
    if not (reason or "").strip():
        raise ValueError("驳回原因必填")
    doc.status = "draft"
    log(db, doc, "status", "submitted", "draft", note=f"驳回：{reason.strip()}")


def complete(db: Session, doc, user) -> None:
    _ensure_status(doc, {"approved"}, "置为已完成")
    doc.status = "completed"
    log(db, doc, "status", "approved", "completed", note="手工置为已完成")


def void(db: Session, doc, reason: str, user) -> None:
    _ensure_status(doc, {"draft", "submitted"}, "作废")
    if not (reason or "").strip():
        raise ValueError("作废原因必填")
    old = doc.status
    doc.status = "voided"
    doc.voided_by = getattr(user, "id", None)
    doc.voided_at = datetime.now()
    doc.void_reason = reason.strip()
    log(db, doc, "status", old, "voided", note=f"作废：{reason.strip()}")


def unapprove(db: Session, doc, reason: str, user) -> None:
    """反审核：库存类单据由 `posting_service` 负责红冲（见路由层）。"""
    _ensure_status(doc, {"approved", "completed"}, "反审核")
    if not (reason or "").strip():
        raise ValueError("反审核原因必填")
    from . import push_service

    push_service.assert_no_downstream(db, doc)          # AC-V2-24
    old = doc.status
    doc.status = "submitted" if old == "approved" else "draft"
    doc.approved_by = None
    doc.approved_at = None
    log(db, doc, "status", old, doc.status, note=f"反审核：{reason.strip()}")


# ==================== 关联合同 / 往来单位校验 ====================

def bind_contract(db: Session, doc, contract_id) -> None:
    """关联合同（可空）：只允许关联未删除的合同，并写入编号快照。"""
    from ..models import Contract

    if contract_id in (None, "", 0, "0"):
        doc.contract_id = None
        doc.contract_no = None
        return
    try:
        cid = int(contract_id)
    except (TypeError, ValueError):
        raise ValueError("关联合同 id 非法")
    contract = db.get(Contract, cid)
    if contract is None or contract.deleted:
        raise ValueError("关联合同不存在或已停用")
    doc.contract_id = contract.id
    doc.contract_no = contract.contract_no


def require_supplier(db: Session, supplier_id) -> Supplier:
    if not supplier_id:
        raise ValueError("请选择供应商")
    supplier = db.get(Supplier, int(supplier_id))
    if supplier is None:
        raise ValueError("供应商档案不存在")
    if supplier.status != "enabled":
        raise ValueError(f"供应商「{supplier.name}」已停用")
    return supplier


def require_customer(db: Session, customer_id) -> Customer:
    if not customer_id:
        raise ValueError("请选择客户")
    customer = db.get(Customer, int(customer_id))
    if customer is None:
        raise ValueError("客户档案不存在")
    if customer.status != "enabled":
        raise ValueError(f"客户「{customer.name}」已停用")
    return customer


def require_warehouse(db: Session, warehouse_id) -> Warehouse:
    if not warehouse_id:
        raise ValueError("请选择仓库")
    warehouse = db.get(Warehouse, int(warehouse_id))
    if warehouse is None:
        raise ValueError("仓库不存在")
    if not warehouse.enabled:
        raise ValueError(f"仓库「{warehouse.name}」已停用")
    return warehouse


def parse_doc_date(value) -> date:
    if value in (None, ""):
        return date.today()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError("单据日期格式应为 YYYY-MM-DD")


# ==================== 格式化 ====================

def fmt_item(it: dict) -> dict:
    return {
        "id": it.id, "seq": it.seq,
        "product_id": it.product_id, "product_code": it.product_code, "product_name": it.product_name,
        "spec": it.spec, "uom_name": it.uom_name, "uom_decimals": it.uom_decimals,
        "qty": float(it.qty) if it.qty is not None else None,
        "unit_price": float(it.unit_price) if it.unit_price is not None else None,
        "amount": float(it.amount) if it.amount is not None else None,
        "warehouse_id": it.warehouse_id, "warehouse_name": it.warehouse_name,
        "src_item_id": getattr(it, "src_item_id", None),
        "ordered_qty": float(it.ordered_qty) if getattr(it, "ordered_qty", None) is not None else None,
        "received_qty": float(it.received_qty) if getattr(it, "received_qty", None) is not None else None,
        "shipped_qty": float(it.shipped_qty) if getattr(it, "shipped_qty", None) is not None else None,
        "book_qty": float(it.book_qty) if getattr(it, "book_qty", None) is not None else None,
        "actual_qty": float(it.actual_qty) if getattr(it, "actual_qty", None) is not None else None,
        "diff_qty": float(it.diff_qty) if getattr(it, "diff_qty", None) is not None else None,
        "diff_reason": getattr(it, "diff_reason", None),
        "remark": it.remark,
    }


def handler_snapshot(db: Session, handler_user_id) -> tuple[int | None, str | None]:
    """V2.1（N1，BR-V2.1-01）：把经办人 id 解析为 `(id, 姓名快照)`。

    姓名以**快照**落库，账号停用后历史单据仍能显示姓名（与 `created_by_name` 同一惯例）。
    空值表示"未指定"（列表筛选用的也是 `handler_user_id`）。
    """
    if not handler_user_id:
        return None, None
    from ..models_auth import User

    user = db.get(User, int(handler_user_id))
    if user is None:
        raise ValueError(f"经办人不存在：{handler_user_id}")
    return user.id, (user.real_name or user.username)


def fmt_doc(db: Session, doc, *, with_items: bool = True) -> dict:
    data = {
        "id": doc.id, "doc_type": doc.doc_type, "kind_label": DOC_KINDS.get(doc.doc_type, ""),
        "doc_no": doc.doc_no,
        "doc_date": doc.doc_date.isoformat() if doc.doc_date else None,
        "status": doc.status, "status_label": DOC_STATUS.get(doc.status, doc.status),
        "org_id": doc.org_id, "created_by": doc.created_by, "created_by_name": doc.created_by_name,
        "handler_user_id": doc.handler_user_id,
        "handler_name": doc.handler_name,        # V2.1/N1：姓名快照（停用账号仍可显示）
        "contract_id": doc.contract_id, "contract_no": doc.contract_no,
        "source_doc_type": doc.source_doc_type, "source_doc_id": doc.source_doc_id,
        "source_doc_no": doc.source_doc_no,
        "submitted_at": _dt(doc.submitted_at), "approved_at": _dt(doc.approved_at),
        "voided_at": _dt(doc.voided_at), "void_reason": doc.void_reason,
        "posted": doc.posted, "remark": doc.remark,
        "created_at": _dt(doc.created_at), "updated_at": _dt(doc.updated_at),
        "total_amount": (float(doc.total_amount) if getattr(doc, "total_amount", None) is not None
                         else float(total_amount_of(doc))),
        "editable": doc.status in EDITABLE_STATUSES,
    }
    for field in ("warehouse_id", "warehouse_name", "in_type", "out_type", "take_type", "scope_note",
                  "supplier_id", "supplier_name", "customer_id", "customer_name", "currency",
                  "request_dept_id", "need_date", "purpose", "suggest_supplier_id",
                  "purchase_dept_id", "expected_arrival_date", "settle_type", "receipt_warehouse_id",
                  "customer_name_text", "sales_dept_id", "expect_delivery_date",
                  "delivery_date", "delivery_address", "contact_name", "contact_phone",
                  "ship_warehouse_id", "generated_in_id", "generated_in_no",
                  "generated_out_id", "generated_out_no",
                  # V2.1/N13：调拨单调出/调入仓库
                  "from_warehouse_id", "from_warehouse_name",
                  "to_warehouse_id", "to_warehouse_name"):
        if hasattr(doc, field):
            value = getattr(doc, field)
            data[field] = value.isoformat() if isinstance(value, date) else value
    if with_items:
        data["items"] = [fmt_item(it) for it in (doc.items or [])]
    return data


def _dt(value) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None


# ==================== 列表通用筛选 ====================

def apply_doc_filters(query, model, *, keyword: str | None = None, status: str | None = None,
                      date_from: str | None = None, date_to: str | None = None,
                      statuses: list[str] | None = None,
                      include_voided: bool = False):
    """列表通用筛选：关键词按单号/来源单号/合同号/往来单位/仓库快照模糊。

    AC-V2-17：作废单据**默认不进列表**，需要时传 `include_voided=True` 或按状态筛"已作废"。
    """
    if not include_voided:
        query = query.filter(model.status != "voided")
    if status:
        query = query.filter(model.status == status)
    if statuses:
        query = query.filter(model.status.in_(statuses))
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        conds = [model.doc_no.like(like), model.source_doc_no.like(like),
                 model.contract_no.like(like), model.remark.like(like)]
        for field in ("supplier_name", "customer_name", "customer_name_text", "warehouse_name"):
            if hasattr(model, field):
                conds.append(getattr(model, field).like(like))
        query = query.filter(or_(*conds))
    if date_from:
        query = query.filter(model.doc_date >= parse_doc_date(date_from))
    if date_to:
        query = query.filter(model.doc_date <= parse_doc_date(date_to))
    return query
