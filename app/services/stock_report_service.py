"""库存批次配对报表（V2.6.1）：入库批次 → 出库 FIFO 配对明细。

口径（2026-10-18 业务确认）：
- 每行 = 一个**入库批次**与它被消耗的出库配对；同一批次分多次出库就拆多行；
- 只出现在库存货行（未消耗部分）：出库列留空，库存数量/金额 = 剩余量/金额；
- 出库项目 ← 出库单备注；领用方 ← 出库单领用人（V2.6.1 新增字段）；
- 资产编号 = 物料编码；
- 库存金额 = 剩余数量 × 该批次入库单价（系统只记数量不记成本，此为"批次价"近似口径）。
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models_doc import StockOutOrder, StockLedger
from ..models_master import Product, Warehouse

ZERO = Decimal("0")


def _out_docs_meta(db: Session, doc_ids: list[int]) -> dict[int, dict]:
    """出库单附加信息（备注=出库项目、领用人、出库类型）。"""
    if not doc_ids:
        return {}
    rows = (db.query(StockOutOrder.id, StockOutOrder.remark, StockOutOrder.issue_party_name,
                     StockOutOrder.out_type)
            .filter(StockOutOrder.id.in_(doc_ids)).all())
    return {r[0]: {"remark": r[1], "issue_name": r[2], "out_type": r[3]} for r in rows}


def build_batches(db: Session, *, warehouse_id: int | None = None,
                  product_id: int | None = None,
                  warehouse_ids: list[int] | None = None,
                  date_from: str | None = None, date_to: str | None = None,
                  keyword: str | None = None) -> list[dict]:
    """按 (仓库, 物料) 回放流水，FIFO 配对，返回报表行（已按入库时间倒序）。"""
    query = db.query(StockLedger)
    if warehouse_ids:
        query = query.filter(StockLedger.warehouse_id.in_(warehouse_ids))
    elif warehouse_id:
        query = query.filter(StockLedger.warehouse_id == warehouse_id)
    if product_id:
        query = query.filter(StockLedger.product_id == product_id)
    rows = query.order_by(StockLedger.id.asc()).all()

    # 物料/仓库名称
    product_ids = {r.product_id for r in rows}
    wh_ids = {r.warehouse_id for r in rows}
    products = ({p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()}
                if product_ids else {})
    warehouses = ({w.id: w for w in db.query(Warehouse).filter(Warehouse.id.in_(wh_ids)).all()}
                  if wh_ids else {})
    kw = (keyword or "").strip().lower()
    if kw:
        rows = [r for r in rows
                if kw in ((products.get(r.product_id).name or "").lower()
                          if products.get(r.product_id) else "")
                or kw in ((products.get(r.product_id).code or "").lower()
                          if products.get(r.product_id) else "")
                or kw in ((products.get(r.product_id).spec or "").lower()
                          if products.get(r.product_id) else "")]

    out_meta = _out_docs_meta(db, [r.doc_id for r in rows if r.doc_type == "stock_out"])

    # 分组回放
    groups: dict[tuple[int, int], list] = defaultdict(list)
    for r in rows:
        groups[(r.warehouse_id, r.product_id)].append(r)

    result: list[dict] = []
    for (wh_id, pid), ledgers in groups.items():
        product, warehouse = products.get(pid), warehouses.get(wh_id)
        batches: list[dict] = []          # FIFO 队列
        stock_qty = ZERO
        stock_value = ZERO
        for lg in ledgers:
            price = lg.unit_price or ZERO
            if (lg.qty_change or ZERO) > 0:          # 入库（含期初、红冲出库的反向）
                batches.append({
                    "qty_rem": lg.qty_change or ZERO,
                    "qty": lg.qty_change or ZERO,
                    "price": price,
                    "doc_no": lg.doc_no, "time": lg.created_at,
                    "src_doc_no": lg.src_doc_no,
                })
                stock_qty += lg.qty_change or ZERO
                stock_value += (lg.qty_change or ZERO) * price
                continue
            # 出库：FIFO 消耗
            need = -(lg.qty_change or ZERO)
            meta = out_meta.get(lg.doc_id, {})
            while need > ZERO and batches:
                batch = batches[0]
                take = min(need, batch["qty_rem"])
                batch["qty_rem"] -= take
                need -= take
                stock_qty -= take
                stock_value -= take * batch["price"]
                result.append({
                    "warehouse": (warehouse.display_name or warehouse.name) if warehouse else "",
                    "in_no": batch["doc_no"],
                    "in_time": batch["time"].isoformat(sep=" ", timespec="seconds")
                    if batch["time"] else None,
                    "product_code": product.code if product else "",
                    "product_name": product.name if product else "",
                    "spec": product.spec if product else "",
                    "uom": product.uom.name if product and product.uom else "",
                    "qty": float(batch["qty"]),
                    "price": float(batch["price"]),
                    "amount": float(batch["qty"] * batch["price"]),
                    "out_no": lg.doc_no,
                    "out_time": lg.created_at.isoformat(sep=" ", timespec="seconds")
                    if lg.created_at else None,
                    "out_qty": float(take),
                    "out_amount": float(take * batch["price"]),
                    "out_type": meta.get("out_type"),
                    "out_project": meta.get("remark"),
                    "issue_party": meta.get("issue_name"),
                    "stock_qty": float(batch["qty_rem"]),
                    "stock_amount": float(batch["qty_rem"] * batch["price"]),
                })
                if batch["qty_rem"] <= ZERO:
                    batches.pop(0)
            if need > ZERO:                            # 库存不足（历史遗留/期初缺失）
                result.append({
                    "warehouse": (warehouse.display_name or warehouse.name) if warehouse else "",
                    "in_no": "", "in_time": None,
                    "product_code": product.code if product else "",
                    "product_name": product.name if product else "",
                    "spec": product.spec if product else "",
                    "uom": product.uom.name if product and product.uom else "",
                    "qty": 0.0, "price": 0.0, "amount": 0.0,
                    "out_no": lg.doc_no,
                    "out_time": lg.created_at.isoformat(sep=" ", timespec="seconds")
                    if lg.created_at else None,
                    "out_qty": float(need), "out_amount": 0.0,
                    "out_type": meta.get("out_type"),
                    "out_project": meta.get("remark"),
                    "issue_party": meta.get("issue_name"),
                    "stock_qty": 0.0, "stock_amount": 0.0,
                })
        # 剩余批次 = 当前库存行
        for batch in batches:
            if batch["qty_rem"] <= ZERO:
                continue
            result.append({
                "warehouse": (warehouse.display_name or warehouse.name) if warehouse else "",
                "in_no": batch["doc_no"],
                "in_time": batch["time"].isoformat(sep=" ", timespec="seconds")
                if batch["time"] else None,
                "product_code": product.code if product else "",
                "product_name": product.name if product else "",
                "spec": product.spec if product else "",
                "uom": product.uom.name if product and product.uom else "",
                "qty": float(batch["qty"]),
                "price": float(batch["price"]),
                "amount": float(batch["qty"] * batch["price"]),
                "out_no": "", "out_time": None, "out_qty": 0.0, "out_amount": 0.0,
                "out_type": None, "out_project": None, "issue_party": None,
                "stock_qty": float(batch["qty_rem"]),
                "stock_amount": float(batch["qty_rem"] * batch["price"]),
            })

    # 时间过滤（按入库时间，缺省不过滤）
    if date_from:
        result = [r for r in result if (r["in_time"] or "")[:10] >= date_from]
    if date_to:
        result = [r for r in result if (r["in_time"] or "")[:10] <= date_to]
    result.sort(key=lambda r: (r["in_time"] or ""), reverse=True)
    return result


BATCH_COLUMNS: list[tuple[str, int]] = [
    ("仓库", 14), ("入库单号", 18), ("入库时间", 20), ("资产编号", 14), ("物料名称", 24),
    ("规格", 16), ("单位", 8), ("数量", 10), ("单价", 12), ("金额", 14),
    ("出库单号", 18), ("出库时间", 20), ("出库数量", 10), ("出库金额", 14),
    ("出库类型", 12), ("出库项目", 24), ("领用方", 14), ("库存数量", 10), ("库存金额", 14),
]

BATCH_KEYS = ["warehouse", "in_no", "in_time", "product_code", "product_name", "spec",
              "uom", "qty", "price", "amount", "out_no", "out_time", "out_qty",
              "out_amount", "out_type", "out_project", "issue_party", "stock_qty",
              "stock_amount"]
