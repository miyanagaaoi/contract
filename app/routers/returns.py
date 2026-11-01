"""退货单据（CR-034）：采购退货单 / 销售退货单。

口径：
- **采购退货单**：出库方向（货退回供应商）；审核后**回冲采购单 `received_qty`**；
- **销售退货单**：入库方向（客户退货入库）；审核后**回冲销售订单 `shipped_qty`**；
- 复用通用单据框架（列表/详情/编辑/提交/审核/红冲/导出），过账走 `posting_service` 的退货审核函数。
"""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy.orm import Session

from ..models_doc import PurchaseReturnOrder, SalesReturnOrder
from ..services import doc_service, posting_service
from .doc_routes import register_doc_routes

router = APIRouter(tags=["stock"])

PURCHASE_RETURN_PREFIX = "/api/stock/purchase-returns"
SALES_RETURN_PREFIX = "/api/stock/sales-returns"


def _apply_purchase_return_fields(db: Session, doc: PurchaseReturnOrder, payload: dict) -> None:
    if "warehouse_id" in payload or doc.warehouse_id is None:
        warehouse = doc_service.require_warehouse(db, payload.get("warehouse_id") or doc.warehouse_id)
        doc.warehouse_id = warehouse.id
        doc.warehouse_name = doc_service.warehouse_display_name(db, warehouse)
    if "supplier_id" in payload:
        supplier_id = payload.get("supplier_id") or None
        if supplier_id:
            supplier = doc_service.require_supplier(db, supplier_id)
            doc.supplier_id, doc.supplier_name = supplier.id, supplier.name
        else:
            doc.supplier_id, doc.supplier_name = None, None


def _apply_sales_return_fields(db: Session, doc: SalesReturnOrder, payload: dict) -> None:
    if "warehouse_id" in payload or doc.warehouse_id is None:
        warehouse = doc_service.require_warehouse(db, payload.get("warehouse_id") or doc.warehouse_id)
        doc.warehouse_id = warehouse.id
        doc.warehouse_name = doc_service.warehouse_display_name(db, warehouse)
    if "customer_id" in payload:
        customer_id = payload.get("customer_id") or None
        if customer_id:
            customer = doc_service.require_customer(db, customer_id)
            doc.customer_id, doc.customer_name = customer.id, customer.name
        else:
            doc.customer_id, doc.customer_name = None, None


register_doc_routes(router, prefix=PURCHASE_RETURN_PREFIX, kind="purchase_return",
                    model=PurchaseReturnOrder, perm_prefix="stock.out", label="采购退货单",
                    create_hook=_apply_purchase_return_fields,
                    update_hook=_apply_purchase_return_fields,
                    approve_handler=posting_service.approve_purchase_return,
                    unapprove_handler=posting_service.unapprove_purchase_return,
                    export_perm="stock.out.export")

register_doc_routes(router, prefix=SALES_RETURN_PREFIX, kind="sales_return",
                    model=SalesReturnOrder, perm_prefix="stock.in", label="销售退货单",
                    create_hook=_apply_sales_return_fields,
                    update_hook=_apply_sales_return_fields,
                    approve_handler=posting_service.approve_sales_return,
                    unapprove_handler=posting_service.unapprove_sales_return,
                    export_perm="stock.in.export")
