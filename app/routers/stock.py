"""库存域 API（T-V2-22/23，对应 `12-erp-system-design.md` §6.3/§6.4）。

- 入库单 `/api/stock/in-orders`：采购入库 / 其他入库；**审核即过账**（增加结存）；
- 出库单 `/api/stock/out-orders`：销售出库 / 领用出库 / 其他出库；审核过账（减少结存，负库存拦截）；
- 盘点单 `/api/stock/takes`：全盘 / 抽盘；审核按差异自动生成盘盈入库/盘亏出库单并过账；
- 库存明细 `/api/stock/balances`、流水 `/api/stock/ledger`、重算校验 `/api/stock/recalc`。

AC 对应：AC-V2-19~26、27~29。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models_auth import User
from ..models_doc import (
    IN_TYPES,
    OUT_TYPES,
    TAKE_TYPES,
    StockInOrder,
    StockOutOrder,
    StockTake,
    StockTransfer,
)
from ..models_master import Product, ProductType
from ..models_stock import Stock, StockLedger
from ..services import audit_service, doc_service, posting_service
from ..services.permission_service import require_perm
from .doc_routes import _guard, register_doc_routes

router = APIRouter(tags=["stock"])


# ==================== 入库单 ====================

IN_PREFIX = "/api/stock/in-orders"


def _apply_in_fields(db: Session, doc: StockInOrder, payload: dict) -> None:
    if "warehouse_id" in payload or doc.warehouse_id is None:
        warehouse = doc_service.require_warehouse(db, payload.get("warehouse_id") or doc.warehouse_id)
        doc.warehouse_id = warehouse.id
        doc.warehouse_name = warehouse.name
    if "in_type" in payload:
        in_type = str(payload.get("in_type") or "采购入库").strip()
        if in_type not in IN_TYPES:
            raise ValueError(f"入库类型只能是：{' / '.join(IN_TYPES)}")
        doc.in_type = in_type
    if "supplier_id" in payload:
        supplier_id = payload.get("supplier_id") or None
        if supplier_id:
            supplier = doc_service.require_supplier(db, supplier_id)
            doc.supplier_id, doc.supplier_name = supplier.id, supplier.name
        else:
            doc.supplier_id, doc.supplier_name = None, None


register_doc_routes(router, prefix=IN_PREFIX, kind="stock_in", model=StockInOrder,
                    perm_prefix="stock.in", label="入库单",
                    create_hook=_apply_in_fields, update_hook=_apply_in_fields,
                    approve_handler=posting_service.approve_stock_doc,
                    unapprove_handler=posting_service.unapprove_stock_doc,
                    export_perm="stock.in.export")


# ==================== 出库单 ====================

OUT_PREFIX = "/api/stock/out-orders"


def _apply_out_fields(db: Session, doc: StockOutOrder, payload: dict) -> None:
    if "warehouse_id" in payload or doc.warehouse_id is None:
        warehouse = doc_service.require_warehouse(db, payload.get("warehouse_id") or doc.warehouse_id)
        doc.warehouse_id = warehouse.id
        doc.warehouse_name = warehouse.name
    if "out_type" in payload:
        out_type = str(payload.get("out_type") or "销售出库").strip()
        if out_type not in OUT_TYPES:
            raise ValueError(f"出库类型只能是：{' / '.join(OUT_TYPES)}")
        doc.out_type = out_type
    if "customer_id" in payload:
        customer_id = payload.get("customer_id") or None
        if customer_id:
            customer = doc_service.require_customer(db, customer_id)
            doc.customer_id, doc.customer_name = customer.id, customer.name
        else:
            doc.customer_id, doc.customer_name = None, None


register_doc_routes(router, prefix=OUT_PREFIX, kind="stock_out", model=StockOutOrder,
                    perm_prefix="stock.out", label="出库单",
                    create_hook=_apply_out_fields, update_hook=_apply_out_fields,
                    approve_handler=posting_service.approve_stock_doc,
                    unapprove_handler=posting_service.unapprove_stock_doc,
                    export_perm="stock.out.export")


# ==================== 盘点单 ====================

TAKE_PREFIX = "/api/stock/takes"


def _apply_take_fields(db: Session, doc: StockTake, payload: dict) -> None:
    if "warehouse_id" in payload or doc.warehouse_id is None:
        warehouse = doc_service.require_warehouse(db, payload.get("warehouse_id") or doc.warehouse_id)
        doc.warehouse_id = warehouse.id
        doc.warehouse_name = warehouse.name
    if "take_type" in payload:
        take_type = str(payload.get("take_type") or "full").strip()
        if take_type not in TAKE_TYPES:
            raise ValueError("盘点方式只能是 full（全盘）或 partial（抽盘）")
        doc.take_type = take_type
    if "scope_note" in payload:
        doc.scope_note = str(payload.get("scope_note") or "").strip() or None


def _approve_take(db: Session, doc: StockTake, user) -> None:
    doc_service.assert_can_approve(db, doc, user)
    posting_service.approve_stock_take(db, doc, user)


register_doc_routes(router, prefix=TAKE_PREFIX, kind="stock_take", model=StockTake,
                    perm_prefix="stock.take", label="盘点单",
                    create_hook=_apply_take_fields, update_hook=_apply_take_fields,
                    approve_handler=_approve_take, export_perm="stock.take.export")


# ==================== 调拨单（V2.1 / N13）====================

TRANSFER_PREFIX = "/api/stock/transfers"


def _apply_transfer_fields(db: Session, doc: StockTransfer, payload: dict) -> None:
    """调拨单特有字段：调出仓 / 调入仓（均必填，且不得相同）。

    关于"同组织"（Q4 冻结结论）：仓库档案 `Warehouse` **没有 org_id 字段**，因此该约束
    在当前数据模型下**无法校验**；本版以"不提供跨组织操作入口"的方式落实范围外声明
    （见 `22-v2.1-requirements.md` §1.3）。若后续要真正约束，需先为仓库引入组织归属。
    """
    from_id = payload.get("from_warehouse_id") or doc.from_warehouse_id
    to_id = payload.get("to_warehouse_id") or doc.to_warehouse_id
    if not from_id:
        raise ValueError("请选择调出仓库")
    if not to_id:
        raise ValueError("请选择调入仓库")
    from_wh = doc_service.require_warehouse(db, from_id)
    to_wh = doc_service.require_warehouse(db, to_id)
    if from_wh.id == to_wh.id:
        raise ValueError("调出仓库与调入仓库不能相同")     # AC-V2.1-14
    doc.from_warehouse_id, doc.from_warehouse_name = from_wh.id, from_wh.name
    doc.to_warehouse_id, doc.to_warehouse_name = to_wh.id, to_wh.name


register_doc_routes(router, prefix=TRANSFER_PREFIX, kind="stock_transfer",
                    model=StockTransfer, perm_prefix="stock.transfer", label="调拨单",
                    create_hook=_apply_transfer_fields, update_hook=_apply_transfer_fields,
                    approve_handler=posting_service.approve_transfer,
                    unapprove_handler=posting_service.unapprove_transfer,
                    export_perm="stock.transfer.export")


@router.post(TAKE_PREFIX + "/{doc_id}/generate", tags=["stock"], summary="生成盘点行项")
def generate_take_items(doc_id: int, request: Request, payload: dict = Body(default={}),
                        user: User = Depends(require_perm("stock.take.edit")),
                        db: Session = Depends(get_db)):
    """按"全盘/抽盘"生成行项：账面数量取当前结存（只读），实盘数量默认为账面值（AC-V2-27/30）。"""
    doc = _guard(db, doc_service.get_doc, db, StockTake, doc_id)
    _guard(db, doc_service.assert_editable, doc)
    created = _guard(db, posting_service.generate_take_items, db, doc,
                     product_type_id=(payload or {}).get("product_type_id"),
                     product_ids=(payload or {}).get("product_ids"))
    audit_service.log(db, user, module="stock", action="generate",
                      object_type="stock_take", object_id=doc.id, object_no=doc.doc_no,
                      detail=f"生成盘点行项 {created} 行", request=request)
    db.commit()
    return doc_service.fmt_doc(db, doc)


@router.put(TAKE_PREFIX + "/{doc_id}/count", tags=["stock"], summary="录入实盘数量")
def submit_counts(doc_id: int, request: Request, payload: dict = Body(...),
                  user: User = Depends(require_perm("stock.take.edit")),
                  db: Session = Depends(get_db)):
    """录入实盘数量并计算差异（`book_qty` 只读，`diff = actual - book`）。"""
    doc = _guard(db, doc_service.get_doc, db, StockTake, doc_id)
    _guard(db, doc_service.assert_editable, doc)
    counts = (payload or {}).get("counts") or []
    by_id = {it.id: it for it in doc.items}
    for raw in counts:
        item = by_id.get(int(raw.get("id") or 0))
        if item is None:
            raise HTTPException(status_code=422, detail="盘点行项不存在")
        try:
            actual = float(raw.get("actual_qty"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="实盘数量必须是数字")
        if actual < 0:
            raise HTTPException(status_code=422, detail="实盘数量不能为负数")
        item.actual_qty = actual
        item.diff_qty = round(actual - float(item.book_qty or 0), 3)
        if "diff_reason" in raw:
            item.diff_reason = str(raw.get("diff_reason") or "").strip() or None
    doc.total_amount = doc_service.total_amount_of(doc)
    audit_service.log(db, user, module="stock", action="count",
                      object_type="stock_take", object_id=doc.id, object_no=doc.doc_no,
                      detail=f"录入实盘 {len(counts)} 行", request=request)
    db.commit()
    return doc_service.fmt_doc(db, doc)


# ==================== 库存明细 / 流水 / 重算 ====================

def _inbound_amount_subquery(db: Session):
    """V2.1（N11，BR-V2.1-09）：货品总额度 = 该 `(物料 × 仓库)` 的**入库批次金额合计**。

    ⚠️ **不能用 `qty_change > 0` 判"入库方向"**：红冲入库的 `qty_change` 为负，会被漏掉
    从而**无法冲减**（额度虚高，见 `23-v2.1-system-design.md` §7.1）。必须以 `biz_type`
    判方向，再对 `qty_change` 求和，使负向自然冲减；同时排除「调拨入库」（含其红冲），
    否则同一批货在仓库间搬运会反复放大额度。
    """
    return (db.query(
                StockLedger.product_id.label("product_id"),
                StockLedger.warehouse_id.label("warehouse_id"),
                func.sum(StockLedger.qty_change * func.coalesce(StockLedger.unit_price, 0))
                .label("inbound_amount"))
            .filter(StockLedger.biz_type.like("%入库%"),
                    StockLedger.biz_type.notlike("%调拨入库%"))
            .group_by(StockLedger.product_id, StockLedger.warehouse_id)
            .subquery())


def _balances_query(db: Session, *, keyword: str | None = None, warehouse_id: int | None = None,
                    product_type_id: int | None = None, below_safety: bool = False,
                    qty_min: float | None = None, qty_max: float | None = None):
    """库存结存查询（列表与导出共用，保证"导出口径与页面一致"，R7）。

    V2.1（N11）：同时 LEFT JOIN 出「货品总额度」，返回 `(Stock, inbound_amount)` 行；
    V2.1（N12）：新增 `qty_min` / `qty_max` 数量区间筛选。
    """
    sub = _inbound_amount_subquery(db)
    query = (db.query(Stock, sub.c.inbound_amount)
             .join(Product, Stock.product_id == Product.id)
             .outerjoin(sub, and_(sub.c.product_id == Stock.product_id,
                                  sub.c.warehouse_id == Stock.warehouse_id))
             .filter(Stock.qty != 0))
    if warehouse_id:
        query = query.filter(Stock.warehouse_id == warehouse_id)
    if product_type_id:
        node = db.get(ProductType, product_type_id)
        type_ids = [r[0] for r in db.query(ProductType.id)
                    .filter(ProductType.path.like(f"{node.path}%")).all()] if node else [product_type_id]
        query = query.filter(Product.product_type_id.in_(type_ids or [-1]))
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter((Product.name.like(like)) | (Product.code.like(like))
                             | (Product.spec.like(like)))
    if below_safety:
        query = query.filter(Product.safety_stock.isnot(None), Stock.qty < Product.safety_stock)
    if qty_min is not None:
        query = query.filter(Stock.qty >= qty_min)
    if qty_max is not None:
        query = query.filter(Stock.qty <= qty_max)
    return query


@router.get("/api/stock/balances", tags=["stock"], summary="库存结存列表")
def stock_balances(keyword: str | None = Query(None, description="物料编码/名称/规格模糊"),
                   warehouse_id: int | None = Query(None),
                   product_type_id: int | None = Query(None),
                   below_safety: bool = Query(False, description="仅看低于安全库存（T-V2-34）"),
                   qty_min: float | None = Query(None, description="结存数量下限（V2.1/N12）"),
                   qty_max: float | None = Query(None, description="结存数量上限（V2.1/N12）"),
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
                   _user: User = Depends(require_perm("stock.balance.view")),
                   db: Session = Depends(get_db)):
    query = _balances_query(db, keyword=keyword, warehouse_id=warehouse_id,
                            product_type_id=product_type_id, below_safety=below_safety,
                            qty_min=qty_min, qty_max=qty_max)
    total = int(query.count() or 0)
    rows = (query.order_by(Product.code.asc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return {
        "items": [{
            "product_id": s.product_id,
            "product_code": s.product.code if s.product else None,
            "product_name": s.product.name if s.product else None,
            "spec": s.product.spec if s.product else None,
            "product_type_name": (s.product.product_type.name
                                  if s.product and s.product.product_type else None),
            "uom_name": s.product.uom.name if s.product and s.product.uom else None,
            "uom_decimals": s.product.uom.decimals if s.product and s.product.uom else None,
            "warehouse_id": s.warehouse_id,
            "warehouse_name": s.warehouse.name if s.warehouse else None,
            "qty": float(s.qty or 0),
            # V2.1（N11）：货品总额度 —— 该 (物料 × 仓库) 的入库批次金额合计
            "inbound_amount": float(amount or 0),
            "safety_stock": float(s.product.safety_stock) if s.product and s.product.safety_stock is not None else None,
            "below_safety": bool(s.product and s.product.safety_stock is not None
                                 and (s.qty or 0) < s.product.safety_stock),
            "updated_at": s.updated_at.isoformat(sep=" ", timespec="seconds") if s.updated_at else None,
        } for s, amount in rows],
        "total": total, "page": page, "page_size": page_size,
    }


@router.get("/api/stock/ledger", tags=["stock"], summary="库存流水（按物料+仓库下钻）")
def stock_ledger(product_id: int = Query(..., description="物料 id（必填）"),
                 warehouse_id: int = Query(..., description="仓库 id（必填）"),
                 date_from: str | None = Query(None), date_to: str | None = Query(None),
                 page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                 _user: User = Depends(require_perm("stock.ledger.view")),
                 db: Session = Depends(get_db)):
    query = (db.query(StockLedger)
             .filter(StockLedger.product_id == product_id,
                     StockLedger.warehouse_id == warehouse_id))
    if date_from:
        query = query.filter(StockLedger.created_at >= doc_service.parse_doc_date(date_from))
    if date_to:
        end = doc_service.parse_doc_date(date_to)
        query = query.filter(func.date(StockLedger.created_at) <= end.isoformat())
    total = int(query.count() or 0)
    rows = (query.order_by(StockLedger.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return {
        "items": [{
            "id": r.id, "biz_type": r.biz_type, "doc_type": r.doc_type, "doc_id": r.doc_id,
            "doc_no": r.doc_no, "src_doc_no": r.src_doc_no,
            "qty_change": float(r.qty_change or 0), "qty_after": float(r.qty_after or 0),
            "unit_price": float(r.unit_price) if r.unit_price is not None else None,
            "created_by": r.created_by, "remark": r.remark,
            "created_at": r.created_at.isoformat(sep=" ", timespec="seconds") if r.created_at else None,
        } for r in rows],
        "total": total, "page": page, "page_size": page_size,
        "balance": float(posting_service.stock_balance_of(db, product_id, warehouse_id)),
    }


@router.post("/api/stock/recalc", tags=["stock"], summary="结存重算校验（运维）")
def recalc_stocks(request: Request, fix: bool = Query(False, description="true=按流水修复结存"),
                  user: User = Depends(require_perm("stock.balance.view")),
                  db: Session = Depends(get_db)):
    """校验 `stocks.qty == SUM(ledger.qty_change)`（AC-V2-26）；`fix=true` 时按流水修复。"""
    result = _guard(db, posting_service.recalc_stocks, db, fix=fix)
    audit_service.log(db, user, module="stock", action="recalc", object_type="stock",
                      result="success" if result["consistent"] else "fail",
                      detail=f"结存校验：检查 {result['checked']} 行，"
                             f"不一致 {result['mismatch_count']} 行"
                             + ("（已按流水修复）" if result["fixed"] else ""),
                      request=request)
    db.commit()
    return result


# ==================== 库存导出（T-V2-35 / AC-V2-40） ====================

@router.get("/api/stock/balances/export.xlsx", tags=["stock"], summary="库存结存导出")
def export_balances(keyword: str | None = Query(None), warehouse_id: int | None = Query(None),
                    product_type_id: int | None = Query(None),
                    below_safety: bool = Query(False),
                    qty_min: float | None = Query(None), qty_max: float | None = Query(None),
                    _user: User = Depends(require_perm("stock.balance.view")),
                    db: Session = Depends(get_db)):
    """导出当前筛选的结存清单（与列表同一查询构建，条数与内容一致）。

    V2.1：新增「货品总额度」列与数量区间筛选，保持"导出与筛选一致"（AC-V2-40）。
    """
    from .export import BALANCE_EXPORT_COLUMNS, DOC_EXPORT_LIMIT, build_xlsx_response

    rows = []
    stocks = (_balances_query(db, keyword=keyword, warehouse_id=warehouse_id,
                              product_type_id=product_type_id, below_safety=below_safety,
                              qty_min=qty_min, qty_max=qty_max)
              .order_by(Product.code.asc()).limit(DOC_EXPORT_LIMIT).all())
    for s, amount in stocks:
        product = s.product
        below = bool(product and product.safety_stock is not None
                     and (s.qty or 0) < product.safety_stock)
        rows.append([
            product.code if product else "",
            product.name if product else "",
            product.spec if product else "",
            product.product_type.name if product and product.product_type else "",
            product.uom.name if product and product.uom else "",
            s.warehouse.name if s.warehouse else "",
            float(s.qty or 0),
            float(product.safety_stock) if product and product.safety_stock is not None else "",
            float(amount or 0),
            "是" if below else "否",
            s.updated_at.isoformat(sep=" ", timespec="seconds") if s.updated_at else "",
        ])
    return build_xlsx_response("库存结存", BALANCE_EXPORT_COLUMNS, rows, "库存结存")


@router.get("/api/stock/ledger/export.xlsx", tags=["stock"], summary="库存流水导出")
def export_ledger(product_id: int = Query(...), warehouse_id: int = Query(...),
                  date_from: str | None = Query(None), date_to: str | None = Query(None),
                  _user: User = Depends(require_perm("stock.ledger.view")),
                  db: Session = Depends(get_db)):
    """导出指定物料+仓库的流水（含红冲记录，按时间倒序）。"""
    from .export import DOC_EXPORT_LIMIT, LEDGER_EXPORT_COLUMNS, build_xlsx_response

    query = (db.query(StockLedger)
             .filter(StockLedger.product_id == product_id,
                     StockLedger.warehouse_id == warehouse_id))
    if date_from:
        query = query.filter(StockLedger.created_at >= doc_service.parse_doc_date(date_from))
    if date_to:
        query = query.filter(func.date(StockLedger.created_at)
                             <= doc_service.parse_doc_date(date_to).isoformat())
    rows = []
    for r in query.order_by(StockLedger.id.desc()).limit(DOC_EXPORT_LIMIT).all():
        rows.append([
            r.created_at.isoformat(sep=" ", timespec="seconds") if r.created_at else "",
            r.biz_type,
            r.src_doc_no or r.doc_no,
            float(r.qty_change or 0),
            float(r.qty_after or 0),
            r.product.code if r.product else "",
            r.product.name if r.product else "",
            r.warehouse.name if r.warehouse else "",
            r.created_by or "",
            r.remark or "",
        ])
    return build_xlsx_response("库存流水", LEDGER_EXPORT_COLUMNS, rows, "库存流水")
