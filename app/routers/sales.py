"""销售线 API（T-V2-29/30，对应 `12-erp-system-design.md` §6.3）。

- 销售申请单 `/api/sales/requests`：录入需求（客户可选，也可只写文本）→ 提交 → 审核 → 下推销售订单；
- 销售订单   `/api/sales/orders`  ：确认客户与交期 → 审核 → 下推出库单（可先用可用库存校验）。

出库单与盘点单复用库存域接口（`/api/stock/out-orders`、`/api/stock/takes`），
审核即过账、红冲与负库存拦截由 `posting_service` 统一保证（AC-V2-20/21/22）。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models_auth import User
from ..models_doc import SalesOrder, SalesRequest
from ..services import audit_service, doc_service, push_service
from ..services.permission_service import get_current_user, require_perm
from .doc_routes import _guard, register_doc_routes

router = APIRouter(tags=["sales"])

# ==================== 销售申请单 ====================

REQ_PREFIX = "/api/sales/requests"


def _apply_request_fields(db: Session, doc: SalesRequest, payload: dict) -> None:
    if "customer_id" in payload:
        customer_id = payload.get("customer_id") or None
        if customer_id:
            customer = doc_service.require_customer(db, customer_id)
            doc.customer_id = customer.id
            doc.customer_name_text = customer.name
        else:
            doc.customer_id = None
    if "customer_name_text" in payload and not doc.customer_id:
        doc.customer_name_text = str(payload.get("customer_name_text") or "").strip() or None
    if "sales_dept_id" in payload:
        doc.sales_dept_id = payload.get("sales_dept_id") or None
    if "expect_delivery_date" in payload:
        doc.expect_delivery_date = (doc_service.parse_doc_date(payload["expect_delivery_date"])
                                    if payload.get("expect_delivery_date") else None)


register_doc_routes(router, prefix=REQ_PREFIX, kind="sales_request", model=SalesRequest,
                    perm_prefix="sales.request", label="销售申请单",
                    create_hook=_apply_request_fields, update_hook=_apply_request_fields,
                    export_perm="sales.request.export")


@router.post(REQ_PREFIX + "/{doc_id}/push", tags=["sales"], summary="销售申请下推销售订单")
def push_to_order(doc_id: int, request: Request, payload: dict = Body(default={}),
                  user: User = Depends(require_perm("sales.order.create")),
                  db: Session = Depends(get_db)):
    """按剩余量（或指定行与数量）生成销售订单草稿。"""
    doc = _guard(db, doc_service.get_doc, db, SalesRequest, doc_id)
    so = _guard(db, push_service.push_sales_order, db, doc, user,
                customer_id=(payload or {}).get("customer_id") or doc.customer_id,
                doc_date=(payload or {}).get("doc_date"),
                rows=(payload or {}).get("items"),
                remark=(payload or {}).get("remark"))
    audit_service.log(db, user, module="sales", action="push",
                      object_type="sales_order", object_id=so.id, object_no=so.doc_no,
                      detail=f"由销售申请单 {doc.doc_no} 下推", request=request)
    db.commit()
    return doc_service.fmt_doc(db, so)


# ==================== 销售订单 ====================

ORDER_PREFIX = "/api/sales/orders"


def _apply_order_fields(db: Session, doc: SalesOrder, payload: dict) -> None:
    if "customer_id" in payload or doc.customer_id is None:
        customer = doc_service.require_customer(db, payload.get("customer_id") or doc.customer_id)
        doc.customer_id = customer.id
        doc.customer_name = customer.name
    if "sales_dept_id" in payload:
        doc.sales_dept_id = payload.get("sales_dept_id") or None
    if "delivery_date" in payload:
        doc.delivery_date = (doc_service.parse_doc_date(payload["delivery_date"])
                             if payload.get("delivery_date") else None)
    for field in ("delivery_address", "contact_name", "contact_phone"):
        if field in payload:
            setattr(doc, field, str(payload.get(field) or "").strip() or None)
    if "currency" in payload:
        doc.currency = str(payload.get("currency") or "CNY").strip().upper() or "CNY"
    if "ship_warehouse_id" in payload:
        warehouse_id = payload.get("ship_warehouse_id") or None
        if warehouse_id:
            doc_service.require_warehouse(db, warehouse_id)
        doc.ship_warehouse_id = warehouse_id or None


register_doc_routes(router, prefix=ORDER_PREFIX, kind="sales_order", model=SalesOrder,
                    perm_prefix="sales.order", label="销售订单",
                    create_hook=_apply_order_fields, update_hook=_apply_order_fields,
                    export_perm="sales.order.export")


@router.post(ORDER_PREFIX + "/{doc_id}/push", tags=["sales"], summary="销售订单下推出库单")
def push_to_stock_out(doc_id: int, request: Request, payload: dict = Body(default={}),
                      user: User = Depends(require_perm("sales.order.push")),
                      db: Session = Depends(get_db)):
    """按剩余量生成出库单草稿；出库单审核时校验可用库存（AC-V2-20/21）。"""
    doc = _guard(db, doc_service.get_doc, db, SalesOrder, doc_id)
    stock_out = _guard(db, push_service.push_stock_out, db, doc, user,
                       doc_date=(payload or {}).get("doc_date"),
                       rows=(payload or {}).get("items"),
                       warehouse_id=(payload or {}).get("warehouse_id"),
                       out_type=(payload or {}).get("out_type"),
                       remark=(payload or {}).get("remark"))
    audit_service.log(db, user, module="sales", action="push",
                      object_type="stock_out", object_id=stock_out.id, object_no=stock_out.doc_no,
                      detail=f"由销售订单 {doc.doc_no} 下推", request=request)
    db.commit()
    return doc_service.fmt_doc(db, stock_out)


@router.get("/api/sales/contract-options", tags=["sales"], summary="可关联的销售合同下拉")
def order_contract_options(keyword: str | None = None,
                           _user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """仅返回**销售方向**（类型码 SAL）的合同，供销售订单关联（AC-V2-31 同构）。"""
    from ..dicts import type_code_of
    from ..models import Contract

    query = db.query(Contract).filter(Contract.deleted == False)  # noqa: E712
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(Contract.name.like(like) | Contract.contract_no.like(like))
    rows = query.order_by(Contract.id.desc()).limit(100).all()
    return [{"id": c.id, "contract_no": c.contract_no, "name": c.name}
            for c in rows if type_code_of(db, c.type) == "SAL"]
