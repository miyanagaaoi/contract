"""库存过账服务（T-V2-19，对应 `12-erp-system-design.md` §5.2）——M2 最高风险模块。

职责：
- 入库/出库单**审核即过账**：更新 `stocks` 结存 + 追加 `stock_ledger` 流水；
- 反审核**红冲**：追加负向流水（原流水保留可查，AC-V2-22）；
- 幂等：已过账的单据重复审核不再产生流水（AC-V2-23）；
- 负库存校验：默认拦截并保持"库存与单据状态都不变"（AC-V2-21）；
- 盘点审核：按差异生成盘盈入库/盘亏出库单并过账（AC-V2-28/29）；
- 运维校验：`recalc_stocks` 断言 `stocks.qty == SUM(ledger.qty_change)`（AC-V2-26）。

事务边界：本模块**不 commit**；路由层在全部步骤成功后一次提交，任一步抛错整体回滚。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..dicts import get_sys_params
from ..models_doc import DOC_STATUS, StockInOrder, StockOutOrder, StockTake
from ..models_stock import Stock, StockLedger
from . import audit_service, doc_service, numbering_service

ZERO = Decimal("0")


class BusinessError(ValueError):
    """过账类业务错误（负库存等）；继承 ValueError 以便路由层统一转 HTTP 422。"""


def _get_stock(db: Session, product_id: int, warehouse_id: int) -> Stock:
    """取结存行，不存在则新建（qty=0）。抽为独立函数便于将来切 PostgreSQL 行锁。"""
    stock = (db.query(Stock)
             .filter(Stock.product_id == product_id, Stock.warehouse_id == warehouse_id)
             .first())
    if stock is None:
        stock = Stock(product_id=product_id, warehouse_id=warehouse_id, qty=ZERO)
        db.add(stock)
        db.flush()
    return stock


def biz_type_of(doc, item=None) -> str:
    """流水业务类型：入库取入库类型、出库取出库类型、盘点调整取盘盈/盘亏。"""
    if isinstance(doc, StockInOrder):
        return getattr(doc, "in_type", None) or "其他入库"
    if isinstance(doc, StockOutOrder):
        return getattr(doc, "out_type", None) or "其他出库"
    return "其他"


def post_stock_doc(db: Session, doc, *, user, reverse: bool = False,
                   skip_negative_check: bool = False) -> int:
    """对入库/出库单过账（`reverse=True` 为红冲）。返回写入的流水条数。"""
    params = get_sys_params(db)
    if not reverse and doc.posted:
        return 0                                    # AC-V2-23 幂等：重复审核不重复过账

    sign = (1 if doc.direction > 0 else -1) * (-1 if reverse else 1)
    written = 0
    for item in doc.items:
        warehouse_id = item.warehouse_id or doc.warehouse_id
        if not warehouse_id:
            raise BusinessError(f"行 {item.seq}：缺少仓库")
        stock = _get_stock(db, item.product_id, warehouse_id)
        delta = sign * (item.qty or ZERO)
        new_qty = (stock.qty or ZERO) + delta

        if (new_qty < 0 and not reverse and not skip_negative_check
                and not params.get("allow_negative_stock", False)):
            warehouse_name = item.warehouse_name or getattr(doc, "warehouse_name", "") or f"仓库#{warehouse_id}"
            raise BusinessError(                    # AC-V2-21
                f"{warehouse_name} 物料「{item.product_name}」库存不足"
                f"（可用 {stock.qty}，需要 {item.qty}）"
            )

        stock.qty = new_qty
        stock.updated_at = datetime.now()
        base_type = biz_type_of(doc, item)
        db.add(StockLedger(
            product_id=item.product_id, warehouse_id=warehouse_id,
            biz_type=(f"红冲-{base_type}" if reverse else base_type),
            doc_type=doc.doc_type, doc_id=doc.id, doc_no=doc.doc_no,
            src_doc_no=doc.source_doc_no, qty_change=delta, qty_after=new_qty,
            unit_price=item.unit_price, org_id=doc.org_id,
            created_by=getattr(user, "id", None),
            remark="反审核红冲" if reverse else None,
        ))
        written += 1

    doc.posted = not reverse
    # 回写来源单据的已执行数量（采购单 received_qty / 销售订单 shipped_qty）
    from . import push_service

    if reverse:
        push_service.rollback_received_qty(db, doc)
    else:
        push_service.backfill_received_qty(db, doc)

    audit_service.log(db, user, module="stock",
                      action="unapprove" if reverse else "approve",
                      object_type=doc.doc_type, object_id=doc.id, object_no=doc.doc_no,
                      detail=("反审核红冲" if reverse else "审核过账") + f"（{written} 条流水）")
    return written


def approve_stock_doc(db: Session, doc, user) -> int:
    """入库/出库单审核：状态流转 + 过账（同一事务，失败整体回滚）。

    幂等（AC-V2-23）：已审核且已过账的单据重复审核时不再产生流水，直接返回当前状态。
    """
    if doc.posted and doc.status == "approved":
        return 0
    doc_service.approve(db, doc, user)
    return post_stock_doc(db, doc, user=user)


def unapprove_stock_doc(db: Session, doc, reason: str, user) -> int:
    """入库/出库单反审核：红冲库存后再回到"待审核"。"""
    doc_service.unapprove(db, doc, reason, user)      # 含下游单据校验（AC-V2-24）
    return post_stock_doc(db, doc, user=user, reverse=True)


# ==================== 盘点（AC-V2-27~29） ====================

def generate_take_items(db: Session, take: StockTake, *, product_type_id: int | None = None,
                        product_ids: list[int] | None = None) -> int:
    """生成盘点行：全盘取该仓库全部有结存物料；抽盘按商品类型或指定物料筛选。

    账面数量（`book_qty`）写入时即固定，作为差异计算基准（界面只读）。
    """
    from ..models_master import Product, ProductType

    query = (db.query(Stock)
             .filter(Stock.warehouse_id == take.warehouse_id, Stock.qty != 0))
    if take.take_type == "partial":
        if product_ids:
            query = query.filter(Stock.product_id.in_([int(p) for p in product_ids]))
        elif product_type_id:
            node = db.get(ProductType, int(product_type_id))
            if node is None:
                raise ValueError("商品类型不存在")
            type_ids = [r[0] for r in db.query(ProductType.id)
                        .filter(ProductType.path.like(f"{node.path}%")).all()] or [node.id]
            product_ids_in_type = [r[0] for r in db.query(Product.id)
                                   .filter(Product.product_type_id.in_(type_ids)).all()]
            query = query.filter(Stock.product_id.in_(product_ids_in_type or [-1]))
    rows = query.order_by(Stock.product_id.asc()).all()

    existing = {it.product_id: it for it in take.items}
    seq = 0
    created = 0
    for stock in rows:
        seq += 1
        if stock.product_id in existing:
            item = existing[stock.product_id]
            item.seq = seq
            item.book_qty = stock.qty
        else:
            product = stock.product
            item = type(take).items.property.mapper.class_()
            item.seq = seq
            item.product_id = stock.product_id
            item.product_code = product.code if product else ""
            item.product_name = product.name if product else ""
            item.spec = product.spec if product else None
            item.uom_name = product.uom.name if product and product.uom else None
            item.uom_decimals = product.uom.decimals if product and product.uom else None
            item.warehouse_id = take.warehouse_id
            item.warehouse_name = take.warehouse_name
            item.qty = ZERO
            item.unit_price = ZERO
            item.amount = ZERO
            item.book_qty = stock.qty
            item.actual_qty = stock.qty          # 默认与账面一致，由盘点人改成实盘数
            item.diff_qty = ZERO
            take.items.append(item)
            created += 1
    return created


def approve_stock_take(db: Session, take: StockTake, user) -> dict:
    """盘点审核：按差异生成盘盈入库/盘亏出库单并过账，回填生成单号。"""
    diffs = [it for it in take.items if (it.diff_qty or ZERO) != 0]
    gain = [it for it in diffs if it.diff_qty > 0]
    loss = [it for it in diffs if it.diff_qty < 0]
    result = {"gain_doc_no": None, "loss_doc_no": None, "diff_items": len(diffs)}

    if gain:
        in_doc = _create_adjust_doc(db, take, "in", gain, user)
        post_stock_doc(db, in_doc, user=user)
        take.generated_in_id, take.generated_in_no = in_doc.id, in_doc.doc_no
        result["gain_doc_no"] = in_doc.doc_no
    if loss:
        out_doc = _create_adjust_doc(db, take, "out", loss, user)
        # 盘亏豁免负库存校验：账实不符本身即差异证据，若被拦截则盘点永远无法平账
        post_stock_doc(db, out_doc, user=user, skip_negative_check=True)
        take.generated_out_id, take.generated_out_no = out_doc.id, out_doc.doc_no
        result["loss_doc_no"] = out_doc.doc_no

    take.status = "approved"
    take.approved_by = getattr(user, "id", None)
    take.approved_at = datetime.now()
    doc_service.log(db, take, "status", "submitted", "approved",
                    note=f"盘点审核：差异 {len(diffs)} 行"
                         + (f"，盘盈单 {result['gain_doc_no']}" if result["gain_doc_no"] else "")
                         + (f"，盘亏单 {result['loss_doc_no']}" if result["loss_doc_no"] else ""))
    return result


def _create_adjust_doc(db: Session, take: StockTake, direction: str, items, user):
    """由盘点差异生成调整单据（盘盈入库 / 盘亏出库），状态直接为已审核。"""
    model = StockInOrder if direction == "in" else StockOutOrder
    doc_no = numbering_service.next_doc_no(db, "stock_in" if direction == "in" else "stock_out",
                                           take.doc_date or date.today())
    doc = model(
        doc_no=doc_no, doc_date=take.doc_date or date.today(), status="approved",
        org_id=take.org_id, created_by=take.created_by,
        created_by_name=take.created_by_name,
        remark=f"盘点差异自动生成（来源 {take.doc_no}）",
        contract_id=take.contract_id, contract_no=take.contract_no,
        source_doc_type="stock_take", source_doc_id=take.id, source_doc_no=take.doc_no,
        submitted_by=getattr(user, "id", None), submitted_at=datetime.now(),
        approved_by=getattr(user, "id", None), approved_at=datetime.now(),
        warehouse_id=take.warehouse_id, warehouse_name=take.warehouse_name,
        posted=False,
    )
    if direction == "in":
        doc.in_type = "盘盈入库"
    else:
        doc.out_type = "盘亏出库"
    doc.total_amount = ZERO
    db.add(doc)
    db.flush()
    item_cls = type(doc).items.property.mapper.class_      # 行项类（注意：class_ 是类属性）
    for idx, src in enumerate(items, start=1):
        doc.items.append(item_cls(
            seq=idx, product_id=src.product_id, product_code=src.product_code,
            product_name=src.product_name, spec=src.spec, uom_name=src.uom_name,
            uom_decimals=src.uom_decimals, qty=abs(src.diff_qty), unit_price=ZERO, amount=ZERO,
            warehouse_id=take.warehouse_id, warehouse_name=take.warehouse_name,
            src_item_id=src.id, remark=src.diff_reason,
        ))
    doc_service.log(db, doc, "_origin", None, take.doc_no, note="盘点差异生成")
    return doc


# ==================== 运维校验（AC-V2-26） ====================

def recalc_stocks(db: Session, *, fix: bool = False) -> dict:
    """校验（可选修复）结存与流水累计的一致性。"""
    mismatches: list[dict] = []
    stocks = db.query(Stock).all()
    for stock in stocks:
        total = (db.query(func.coalesce(func.sum(StockLedger.qty_change), 0))
                 .filter(StockLedger.product_id == stock.product_id,
                         StockLedger.warehouse_id == stock.warehouse_id)
                 .scalar())
        total = Decimal(str(total or 0))
        if total != (stock.qty or ZERO):
            mismatches.append({
                "product_id": stock.product_id,
                "product_name": stock.product.name if stock.product else None,
                "warehouse_id": stock.warehouse_id,
                "warehouse_name": stock.warehouse.name if stock.warehouse else None,
                "stock_qty": float(stock.qty or 0),
                "ledger_qty": float(total),
            })
            if fix:
                stock.qty = total
    if fix and mismatches:
        db.commit()
    return {
        "checked": len(stocks),
        "consistent": not mismatches,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:50],
        "fixed": bool(fix and mismatches),
    }


def stock_balance_of(db: Session, product_id: int, warehouse_id: int) -> Decimal:
    stock = (db.query(Stock)
             .filter(Stock.product_id == product_id, Stock.warehouse_id == warehouse_id)
             .first())
    return (stock.qty if stock else ZERO) or ZERO


def status_label(doc) -> str:
    return DOC_STATUS.get(doc.status, doc.status)
