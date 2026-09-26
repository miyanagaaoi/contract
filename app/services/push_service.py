"""下推服务（T-V2-20~22 / M3 复用，对应 `12-erp-system-design.md` §5.3）。

下推链：
- 采购线：采购申请 → 采购单 → 入库单
- 销售线：销售申请 → 销售订单 → 出库单

规则：
- 下推数量不得超过**剩余可下推量**（`qty - ordered_qty` / `qty - received_qty` / `qty - shipped_qty`），
  超出时给出中文提示（AC-V2-16、AC-V2-18）；
- 下推生成**草稿**单据并记录来源（`source_doc_type/id/no`）；行项保留 `src_item_id` 以便回写；
- 过账后回写来源数量；红冲时回退（由 `posting_service` 调用）；
- 上游单据存在未作废的下游单据时，禁止反审核/作废（AC-V2-24）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models_doc import (
    PurchaseOrder,
    PurchaseRequest,
    SalesOrder,
    SalesRequest,
    StockInOrder,
    StockOutOrder,
)
from . import doc_service, numbering_service

ZERO = Decimal("0")

# 上游单据类型 → 下游（表模型, 中文名）
_DOWNSTREAM: dict[str, list[tuple[type, str]]] = {
    "purchase_request": [(PurchaseOrder, "采购单")],
    "purchase_order": [(StockInOrder, "入库单")],
    "sales_request": [(SalesOrder, "销售订单")],
    "sales_order": [(StockOutOrder, "出库单")],
}


def remaining_qty(item, field: str) -> Decimal:
    """剩余可下推数量。`field` ∈ ordered_qty / received_qty / shipped_qty。"""
    used = getattr(item, field, None) or ZERO
    return (item.qty or ZERO) - used


def assert_pushable(item, field: str, qty: Decimal, label: str) -> None:
    remain = remaining_qty(item, field)
    if qty <= 0:
        raise ValueError(f"下推数量必须大于 0（{label}）")
    if qty > remain:
        raise ValueError(
            f"{label}「{item.product_name}」可下推数量不足（剩余 {remain}，本次 {qty}）")


def assert_no_downstream(db: Session, doc) -> None:
    """上游单据反审核/作废前检查下游（AC-V2-24）。"""
    for model, label in _DOWNSTREAM.get(doc.doc_type, []):
        exists = (db.query(model.id)
                  .filter(model.source_doc_type == doc.doc_type,
                          model.source_doc_id == doc.id,
                          model.status != "voided")
                  .first())
        if exists is not None:
            raise ValueError(f"已存在下游{label}，请先处理下游单据（反审核或作废）后再操作")


def _rows_of(db: Session, doc, rows: list[dict] | None, *, field: str,
             default_warehouse_id: int | None = None) -> list[dict]:
    """把下推行项解析为 [{src_item, qty, unit_price, warehouse_id}]；`rows=None` 表示按剩余量全推。"""
    by_id = {it.id: it for it in doc.items}
    if not rows:
        picked = []
        for item in doc.items:
            remain = remaining_qty(item, field)
            if remain > 0:
                picked.append({"src_item": item, "qty": remain, "unit_price": item.unit_price,
                               "warehouse_id": item.warehouse_id or default_warehouse_id})
        if not picked:
            raise ValueError("没有可下推的行项（剩余数量均为 0）")
        return picked

    picked = []
    for idx, raw in enumerate(rows):
        src_id = raw.get("src_item_id") or raw.get("id")
        # 未指定来源行时按顺序对应（支持"整单下推时只传数量"的简化调用）
        item = by_id.get(int(src_id)) if src_id else (doc.items[idx] if idx < len(doc.items) else None)
        if item is None:
            raise ValueError("下推行项与来源单据不匹配")
        qty_raw = raw.get("qty")
        qty = Decimal(str(qty_raw if qty_raw not in (None, "") else remaining_qty(item, field)))
        assert_pushable(item, field, qty, "行项")
        picked.append({
            "src_item": item, "qty": qty,
            "unit_price": Decimal(str(raw.get("unit_price", item.unit_price) or 0)),
            "warehouse_id": raw.get("warehouse_id") or item.warehouse_id or default_warehouse_id,
        })
    if not picked:
        raise ValueError("请至少选择一行下推")
    return picked


# ==================== 采购线 ====================

def push_purchase_order(db: Session, request_doc: PurchaseRequest, user, *,
                        supplier_id, doc_date=None, rows: list[dict] | None = None,
                        remark: str | None = None) -> PurchaseOrder:
    """采购申请 → 采购单草稿（AC-V2-16）。"""
    if request_doc.status != "approved":
        raise ValueError("仅已审核的采购申请单可以下推采购单")
    picked = _rows_of(db, request_doc, rows, field="ordered_qty")
    supplier = doc_service.require_supplier(db, supplier_id)
    day = doc_service.parse_doc_date(doc_date) if doc_date else (request_doc.doc_date or date.today())

    po = PurchaseOrder(
        doc_no=numbering_service.next_doc_no(db, "purchase_order", day),
        doc_date=day, status="draft", org_id=request_doc.org_id,
        created_by=getattr(user, "id", None),
        created_by_name=getattr(user, "real_name", None),
        handler_user_id=request_doc.handler_user_id,
        remark=remark or f"由采购申请单 {request_doc.doc_no} 下推",
        contract_id=request_doc.contract_id, contract_no=request_doc.contract_no,
        source_doc_type="purchase_request", source_doc_id=request_doc.id,
        source_doc_no=request_doc.doc_no,
        supplier_id=supplier.id, supplier_name=supplier.name,
        purchase_dept_id=getattr(request_doc, "request_dept_id", None),
        expected_arrival_date=getattr(request_doc, "need_date", None),
    )
    item_cls = type(po).items.property.mapper.class_      # 行项类（class_ 是类属性，勿加括号）
    db.add(po)
    db.flush()
    for idx, row in enumerate(picked, start=1):
        src = row["src_item"]
        po.items.append(item_cls(
            seq=idx, product_id=src.product_id, product_code=src.product_code,
            product_name=src.product_name, spec=src.spec, uom_name=src.uom_name,
            uom_decimals=src.uom_decimals, qty=row["qty"], unit_price=row["unit_price"],
            amount=(row["qty"] * row["unit_price"]).quantize(Decimal("0.01")),
            warehouse_id=row["warehouse_id"], src_item_id=src.id,
        ))
        src.ordered_qty = (src.ordered_qty or ZERO) + row["qty"]

    po.total_amount = doc_service.total_amount_of(po)
    # V2.1（N8，BR-V2.1-06）：全部行项下推归零 → 申请单自动置「已完成」
    complete_if_fully_ordered(db, request_doc)
    doc_service.log(db, po, "_origin", None, request_doc.doc_no,
                    note=f"由采购申请单下推（{len(picked)} 行）")
    return po


def complete_if_fully_ordered(db: Session, request_doc) -> bool:
    """V2.1（N7/N8）：申请单**全部行项**剩余可下推量为 0 时，置为「已完成」。

    幂等：已是 completed 或无行项时直接返回 False（可安全重复调用）。
    返回是否本次发生了状态变更。
    """
    if request_doc.status == "completed":
        return False
    items = list(request_doc.items or [])
    if not items:
        return False
    if any(remaining_qty(it, "ordered_qty") > 0 for it in items):
        return False
    old_status = request_doc.status
    request_doc.status = "completed"
    doc_service.log(db, request_doc, "status", old_status, "completed",
                    note="全部行项已下推完毕，自动置为已完成")
    return True


def remain_qty_sum(doc) -> Decimal:
    """V2.1（N7）：单据全部行项的剩余可下推量合计（供列表按钮显隐）。"""
    total = ZERO
    for it in (doc.items or []):
        total += remaining_qty(it, "ordered_qty")
    return total


def push_stock_in(db: Session, po: PurchaseOrder, user, *, doc_date=None,
                  rows: list[dict] | None = None, warehouse_id=None,
                  in_type: str | None = None, remark: str | None = None) -> StockInOrder:
    """采购单 → 入库单草稿（AC-V2-18）。"""
    if po.status not in ("approved", "completed"):
        raise ValueError("仅已审核的采购单可以下推入库单")
    warehouse = doc_service.require_warehouse(db, warehouse_id or po.receipt_warehouse_id)
    picked = _rows_of(db, po, rows, field="received_qty", default_warehouse_id=warehouse.id)
    day = doc_service.parse_doc_date(doc_date) if doc_date else date.today()

    doc = StockInOrder(
        doc_no=numbering_service.next_doc_no(db, "stock_in", day),
        doc_date=day, status="draft", org_id=po.org_id,
        created_by=getattr(user, "id", None),
        created_by_name=getattr(user, "real_name", None),
        handler_user_id=po.handler_user_id,
        remark=remark or f"由采购单 {po.doc_no} 下推",
        contract_id=po.contract_id, contract_no=po.contract_no,
        source_doc_type="purchase_order", source_doc_id=po.id, source_doc_no=po.doc_no,
        warehouse_id=warehouse.id, warehouse_name=warehouse.name,
        in_type=in_type or "采购入库",
        supplier_id=po.supplier_id, supplier_name=po.supplier_name,
    )
    item_cls = type(doc).items.property.mapper.class_
    db.add(doc)
    db.flush()
    for idx, row in enumerate(picked, start=1):
        src = row["src_item"]
        doc.items.append(item_cls(
            seq=idx, product_id=src.product_id, product_code=src.product_code,
            product_name=src.product_name, spec=src.spec, uom_name=src.uom_name,
            uom_decimals=src.uom_decimals, qty=row["qty"], unit_price=src.unit_price,
            amount=(row["qty"] * (src.unit_price or ZERO)).quantize(Decimal("0.01")),
            warehouse_id=row["warehouse_id"] or warehouse.id,
            warehouse_name=warehouse.name, src_item_id=src.id,
        ))
    doc.total_amount = doc_service.total_amount_of(doc)
    doc_service.log(db, doc, "_origin", None, po.doc_no, note=f"由采购单下推（{len(picked)} 行）")
    return doc


# ==================== 销售线（M3 使用，M2 先实现服务层） ====================

def push_sales_order(db: Session, request_doc: SalesRequest, user, *,
                     customer_id, doc_date=None, rows: list[dict] | None = None,
                     remark: str | None = None) -> SalesOrder:
    """销售申请 → 销售订单草稿。"""
    if request_doc.status != "approved":
        raise ValueError("仅已审核的销售申请单可以下推销售订单")
    picked = _rows_of(db, request_doc, rows, field="ordered_qty")
    customer = doc_service.require_customer(db, customer_id)
    day = doc_service.parse_doc_date(doc_date) if doc_date else (request_doc.doc_date or date.today())

    so = SalesOrder(
        doc_no=numbering_service.next_doc_no(db, "sales_order", day),
        doc_date=day, status="draft", org_id=request_doc.org_id,
        created_by=getattr(user, "id", None),
        created_by_name=getattr(user, "real_name", None),
        handler_user_id=request_doc.handler_user_id,
        remark=remark or f"由销售申请单 {request_doc.doc_no} 下推",
        contract_id=request_doc.contract_id, contract_no=request_doc.contract_no,
        source_doc_type="sales_request", source_doc_id=request_doc.id,
        source_doc_no=request_doc.doc_no,
        customer_id=customer.id, customer_name=customer.name,
        sales_dept_id=getattr(request_doc, "sales_dept_id", None),
        delivery_date=getattr(request_doc, "expect_delivery_date", None),
    )
    item_cls = type(so).items.property.mapper.class_
    db.add(so)
    db.flush()
    for idx, row in enumerate(picked, start=1):
        src = row["src_item"]
        so.items.append(item_cls(
            seq=idx, product_id=src.product_id, product_code=src.product_code,
            product_name=src.product_name, spec=src.spec, uom_name=src.uom_name,
            uom_decimals=src.uom_decimals, qty=row["qty"], unit_price=row["unit_price"],
            amount=(row["qty"] * row["unit_price"]).quantize(Decimal("0.01")),
            warehouse_id=row["warehouse_id"], src_item_id=src.id,
        ))
        src.ordered_qty = (src.ordered_qty or ZERO) + row["qty"]

    so.total_amount = doc_service.total_amount_of(so)
    doc_service.log(db, so, "_origin", None, request_doc.doc_no,
                    note=f"由销售申请单下推（{len(picked)} 行）")
    return so


def push_stock_out(db: Session, so: SalesOrder, user, *, doc_date=None,
                   rows: list[dict] | None = None, warehouse_id=None,
                   out_type: str | None = None, remark: str | None = None) -> StockOutOrder:
    """销售订单 → 出库单草稿。"""
    if so.status not in ("approved", "completed"):
        raise ValueError("仅已审核的销售订单可以下推出库单")
    warehouse = doc_service.require_warehouse(db, warehouse_id or so.ship_warehouse_id)
    picked = _rows_of(db, so, rows, field="shipped_qty", default_warehouse_id=warehouse.id)
    day = doc_service.parse_doc_date(doc_date) if doc_date else date.today()

    doc = StockOutOrder(
        doc_no=numbering_service.next_doc_no(db, "stock_out", day),
        doc_date=day, status="draft", org_id=so.org_id,
        created_by=getattr(user, "id", None),
        created_by_name=getattr(user, "real_name", None),
        handler_user_id=so.handler_user_id,
        remark=remark or f"由销售订单 {so.doc_no} 下推",
        contract_id=so.contract_id, contract_no=so.contract_no,
        source_doc_type="sales_order", source_doc_id=so.id, source_doc_no=so.doc_no,
        warehouse_id=warehouse.id, warehouse_name=warehouse.name,
        out_type=out_type or "销售出库",
        customer_id=so.customer_id, customer_name=so.customer_name,
    )
    item_cls = type(doc).items.property.mapper.class_
    db.add(doc)
    db.flush()
    for idx, row in enumerate(picked, start=1):
        src = row["src_item"]
        doc.items.append(item_cls(
            seq=idx, product_id=src.product_id, product_code=src.product_code,
            product_name=src.product_name, spec=src.spec, uom_name=src.uom_name,
            uom_decimals=src.uom_decimals, qty=row["qty"], unit_price=src.unit_price,
            amount=(row["qty"] * (src.unit_price or ZERO)).quantize(Decimal("0.01")),
            warehouse_id=row["warehouse_id"] or warehouse.id,
            warehouse_name=warehouse.name, src_item_id=src.id,
        ))
    doc.total_amount = doc_service.total_amount_of(doc)
    doc_service.log(db, doc, "_origin", None, so.doc_no, note=f"由销售订单下推（{len(picked)} 行）")
    return doc


# ==================== 过账后的数量回写 ====================

def _source_items(db: Session, doc, source_type: str) -> dict[int, object] | None:
    """按 `source_doc_id` 取回来源单据的行项（{行项 id: 行项}）。"""
    if doc.source_doc_type != source_type or not doc.source_doc_id:
        return None
    model = {"purchase_order": PurchaseOrder, "sales_order": SalesOrder}.get(source_type)
    if model is None:
        return None
    source = db.get(model, doc.source_doc_id)
    if source is None:
        return None
    return {it.id: it for it in source.items}


def backfill_received_qty(db: Session, stock_in_doc) -> None:
    """入库过账后回写采购单行项 `received_qty`（AC-V2-18）。"""
    items = _source_items(db, stock_in_doc, "purchase_order")
    if not items:
        return
    for line in stock_in_doc.items:
        target = items.get(line.src_item_id)
        if target is not None:
            target.received_qty = (target.received_qty or ZERO) + (line.qty or ZERO)


def rollback_received_qty(db: Session, stock_in_doc) -> None:
    """红冲时回退采购单行项 `received_qty`。"""
    items = _source_items(db, stock_in_doc, "purchase_order")
    if not items:
        return
    for line in stock_in_doc.items:
        target = items.get(line.src_item_id)
        if target is not None:
            target.received_qty = max(ZERO, (target.received_qty or ZERO) - (line.qty or ZERO))


def backfill_shipped_qty(db: Session, stock_out_doc) -> None:
    """出库过账后回写销售订单行项 `shipped_qty`。"""
    items = _source_items(db, stock_out_doc, "sales_order")
    if not items:
        return
    for line in stock_out_doc.items:
        target = items.get(line.src_item_id)
        if target is not None:
            target.shipped_qty = (target.shipped_qty or ZERO) + (line.qty or ZERO)


def rollback_shipped_qty(db: Session, stock_out_doc) -> None:
    items = _source_items(db, stock_out_doc, "sales_order")
    if not items:
        return
    for line in stock_out_doc.items:
        target = items.get(line.src_item_id)
        if target is not None:
            target.shipped_qty = max(ZERO, (target.shipped_qty or ZERO) - (line.qty or ZERO))
