"""采购线 API（T-V2-20/21，对应 `12-erp-system-design.md` §6.3）。

- 采购申请单 `/api/purchase/requests`：录入需求 → 提交 → 审核 → 下推采购单；
- 采购单   `/api/purchase/orders`  ：向供应商下单 → 审核 → 下推入库单。

权限点：`purchase.request.*` / `purchase.order.*`（见 `app/permissions.py`）。
下推数量受"剩余可下推量"约束（AC-V2-16 / AC-V2-18）。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models_auth import User
from ..models_doc import PurchaseOrder, PurchaseRequest
from ..services import audit_service, doc_service, push_service
from ..services.permission_service import get_current_user, require_perm
from .doc_routes import _guard, register_doc_routes

router = APIRouter(tags=["purchase"])

# ==================== 采购申请单 ====================

REQ_PREFIX = "/api/purchase/requests"


def _apply_request_fields(db: Session, doc: PurchaseRequest, payload: dict) -> None:
    if doc.status != "draft" and payload.get("items"):
        raise ValueError("非草稿状态不能修改行项")
    if "request_dept_id" in payload:
        doc.request_dept_id = payload.get("request_dept_id") or None
    if "need_date" in payload:
        doc.need_date = doc_service.parse_doc_date(payload["need_date"]) if payload.get("need_date") else None
    if "purpose" in payload:
        doc.purpose = str(payload.get("purpose") or "").strip() or None
    if "suggest_supplier_id" in payload:
        doc.suggest_supplier_id = payload.get("suggest_supplier_id") or None


register_doc_routes(router, prefix=REQ_PREFIX, kind="purchase_request", model=PurchaseRequest,
                    perm_prefix="purchase.request", label="采购申请单",
                    create_hook=_apply_request_fields, update_hook=_apply_request_fields)


@router.post(REQ_PREFIX + "/{doc_id}/push", tags=["purchase"], summary="采购申请下推采购单")
def push_to_order(doc_id: int, request: Request, payload: dict = Body(default={}),
                  user: User = Depends(require_perm("purchase.order.create")),
                  db: Session = Depends(get_db)):
    """按剩余量（或指定行与数量）生成采购单草稿（AC-V2-16）。"""
    doc = _guard(db, doc_service.get_doc, db, PurchaseRequest, doc_id)
    po = _guard(db, push_service.push_purchase_order, db, doc, user,
                supplier_id=(payload or {}).get("supplier_id"),
                doc_date=(payload or {}).get("doc_date"),
                rows=(payload or {}).get("items"),
                remark=(payload or {}).get("remark"))
    audit_service.log(db, user, module="purchase", action="push",
                      object_type="purchase_order", object_id=po.id, object_no=po.doc_no,
                      detail=f"由采购申请单 {doc.doc_no} 下推", request=request)
    db.commit()
    return doc_service.fmt_doc(db, po)


# ==================== 采购单 ====================

ORDER_PREFIX = "/api/purchase/orders"


def _apply_order_fields(db: Session, doc: PurchaseOrder, payload: dict) -> None:
    if "supplier_id" in payload or doc.supplier_id is None:
        supplier = doc_service.require_supplier(db, payload.get("supplier_id") or doc.supplier_id)
        doc.supplier_id = supplier.id
        doc.supplier_name = supplier.name
    if "purchase_dept_id" in payload:
        doc.purchase_dept_id = payload.get("purchase_dept_id") or None
    if "expected_arrival_date" in payload:
        doc.expected_arrival_date = (doc_service.parse_doc_date(payload["expected_arrival_date"])
                                     if payload.get("expected_arrival_date") else None)
    if "settle_type" in payload:
        doc.settle_type = str(payload.get("settle_type") or "").strip() or None
    if "currency" in payload:
        doc.currency = str(payload.get("currency") or "CNY").strip().upper() or "CNY"
    if "receipt_warehouse_id" in payload:
        warehouse_id = payload.get("receipt_warehouse_id") or None
        if warehouse_id:
            doc_service.require_warehouse(db, warehouse_id)
        doc.receipt_warehouse_id = warehouse_id or None


register_doc_routes(router, prefix=ORDER_PREFIX, kind="purchase_order", model=PurchaseOrder,
                    perm_prefix="purchase.order", label="采购单",
                    create_hook=_apply_order_fields, update_hook=_apply_order_fields)


@router.post(ORDER_PREFIX + "/{doc_id}/push", tags=["purchase"], summary="采购单下推入库单")
def push_to_stock_in(doc_id: int, request: Request, payload: dict = Body(default={}),
                     user: User = Depends(require_perm("purchase.order.push")),
                     db: Session = Depends(get_db)):
    """按剩余量生成入库单草稿（AC-V2-18）；入库单审核后回写采购单"已入库数量"。"""
    doc = _guard(db, doc_service.get_doc, db, PurchaseOrder, doc_id)
    stock_in = _guard(db, push_service.push_stock_in, db, doc, user,
                      doc_date=(payload or {}).get("doc_date"),
                      rows=(payload or {}).get("items"),
                      warehouse_id=(payload or {}).get("warehouse_id"),
                      in_type=(payload or {}).get("in_type"),
                      remark=(payload or {}).get("remark"))
    audit_service.log(db, user, module="purchase", action="push",
                      object_type="stock_in", object_id=stock_in.id, object_no=stock_in.doc_no,
                      detail=f"由采购单 {doc.doc_no} 下推", request=request)
    db.commit()
    return doc_service.fmt_doc(db, stock_in)


@router.get("/api/purchase/contract-options", tags=["purchase"], summary="可关联的采购合同下拉")
def order_contract_options(keyword: str | None = None,
                           _user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """仅返回**采购方向**（类型码 PUR）的合同，供采购单关联（AC-V2-31）。"""
    from ..dicts import get_contract_types, type_code_of
    from ..models import Contract

    pur_labels = {t["label"] for t in get_contract_types(db) if t["code"] == "PUR"}
    query = db.query(Contract).filter(Contract.deleted == False)  # noqa: E712
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(Contract.name.like(like) | Contract.contract_no.like(like))
    rows = query.order_by(Contract.id.desc()).limit(100).all()
    return [{"id": c.id, "contract_no": c.contract_no, "name": c.name}
            for c in rows if type_code_of(db, c.type) == "PUR" or c.type in pur_labels]
