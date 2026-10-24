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

from ..models_doc import StockOutOrder
from ..models_stock import StockLedger
from .doc_service import warehouse_display_name
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


def _row_common(*, db, warehouse, product, meta) -> dict:
    """报表行的公共列（三类行共用）。"""
    return {
        "warehouse": warehouse_display_name(db, warehouse) if warehouse else "",
        "product_code": product.code if product else "",
        "product_name": product.name if product else "",
        "spec": product.spec if product else "",
        "uom": product.uom.name if product and product.uom else "",
        "out_type": meta.get("out_type") if meta else None,
        "out_project": meta.get("remark") if meta else None,
        "issue_party": meta.get("issue_name") if meta else None,
    }


def build_batches(db: Session, *, warehouse_id: int | None = None,
                  product_id: int | None = None,
                  warehouse_ids: list[int] | None = None,
                  date_from: str | None = None, date_to: str | None = None,
                  keyword: str | None = None) -> list[dict]:
    """按 (仓库, 物料) 回放流水，FIFO 配对，返回报表行（带 `row_kind`）。

    V2.6.1 / CR-018：`row_kind` 三类——
      - `normal`   正常配对（入库批次 <-> 出库）与未消耗剩余行；
      - `reversal` 红冲行（`biz_type` 以「红冲-」开头）：红冲入库回减原批次，
                   红冲出库按消耗记录 LIFO 归还；单列展示，不计入正常出库量；
      - `orphan`   无入库批次的出库（负库存/期初缺失），单列展示。
    口径不变：剩余只由未消耗批次行体现（出库/红冲行不记剩余）。
    """
    query = db.query(StockLedger)
    if warehouse_ids:
        query = query.filter(StockLedger.warehouse_id.in_(warehouse_ids))
    elif warehouse_id:
        query = query.filter(StockLedger.warehouse_id == warehouse_id)
    if product_id:
        query = query.filter(StockLedger.product_id == product_id)
    rows = query.order_by(StockLedger.id.asc()).all()

    product_ids = {r.product_id for r in rows}
    wh_ids = {r.warehouse_id for r in rows}
    products = ({p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()}
                if product_ids else {})
    warehouses = ({w.id: w for w in db.query(Warehouse).filter(Warehouse.id.in_(wh_ids)).all()}
                  if wh_ids else {})
    kw = (keyword or "").strip().lower()
    if kw:
        def _hit(r) -> bool:
            prod = products.get(r.product_id)
            if prod is None:
                return False
            return any(kw in (v or "").lower() for v in (prod.name, prod.code, prod.spec))
        rows = [r for r in rows if _hit(r)]

    out_meta = _out_docs_meta(db, [r.doc_id for r in rows if r.doc_type == "stock_out"])

    groups: dict[tuple[int, int], list] = defaultdict(list)
    for r in rows:
        groups[(r.warehouse_id, r.product_id)].append(r)

    result: list[dict] = []
    for (wh_id, pid), ledgers in groups.items():
        product, warehouse = products.get(pid), warehouses.get(wh_id)
        batches: list[dict] = []
        consumed: dict[int, list] = defaultdict(list)      # 出库单 doc_id -> [(batch, take)]
        for lg in ledgers:
            price = lg.unit_price or ZERO
            qty = lg.qty_change or ZERO
            is_rev = str(lg.biz_type or "").startswith("红冲")
            meta = out_meta.get(lg.doc_id, {})
            base = _row_common(db=db, warehouse=warehouse, product=product, meta=meta)
            ts = lg.created_at.isoformat(sep=" ", timespec="seconds") if lg.created_at else None

            # ---------- 红冲行：单独类型，不参与正常 FIFO 统计 ----------
            if is_rev:
                row = dict(base)
                row.update({
                    "row_kind": "reversal",
                    "in_no": lg.doc_no if qty < ZERO else "",
                    "in_time": ts if qty < ZERO else None,
                    "qty": 0.0, "price": float(price), "amount": 0.0,
                    "out_no": lg.doc_no, "out_time": ts,
                    "out_qty": float(abs(qty)),
                    "out_amount": float(abs(qty) * price),
                    "stock_qty": None, "stock_amount": None,
                })
                if qty < ZERO:          # 红冲入库：回减原批次剩余
                    amount = -qty
                    for b in batches:
                        if b["doc_no"] == lg.doc_no and b["qty_rem"] > ZERO:
                            b["qty_rem"] = max(ZERO, b["qty_rem"] - amount)
                            break
                else:                   # 红冲出库：按该单消耗记录 LIFO 归还
                    restore = qty
                    for batch, take in reversed(consumed.get(lg.doc_id, [])):
                        give = min(restore, take)
                        batch["qty_rem"] += give
                        restore -= give
                        # 该批次可能已因耗尽被移出 FIFO 队列 → 归还后按原始顺序放回，
                        # 否则剩余行丢失（CR-018 实测：A2 归还 10 未体现）
                        if batch not in batches:
                            batches.append(batch)
                            batches.sort(key=lambda b: b.get("seq", 0))
                        if restore <= ZERO:
                            break
                result.append(row)
                continue

            # ---------- 正常入库：形成批次 ----------
            if qty > ZERO:
                batches.append({"qty_rem": qty, "qty": qty, "price": price,
                                "doc_no": lg.doc_no, "time": lg.created_at,
                                "seq": lg.id})
                continue

            # ---------- 正常出库：FIFO 消耗 ----------
            need = -qty
            while need > ZERO and batches:
                batch = batches[0]
                take = min(need, batch["qty_rem"])
                batch["qty_rem"] -= take
                need -= take
                consumed[lg.doc_id].append((batch, take))
                row = dict(base)
                row.update({
                    "row_kind": "normal",
                    "in_no": batch["doc_no"],
                    "in_time": (batch["time"].isoformat(sep=" ", timespec="seconds")
                                if batch["time"] else None),
                    "qty": float(batch["qty"]), "price": float(batch["price"]),
                    "amount": float(batch["qty"] * batch["price"]),
                    "out_no": lg.doc_no, "out_time": ts,
                    "out_qty": float(take),
                    "out_amount": float(take * batch["price"]),
                    "stock_qty": None, "stock_amount": None,
                })
                result.append(row)
                if batch["qty_rem"] <= ZERO:
                    batches.pop(0)
            if need > ZERO:             # 无入库批次可配
                row = dict(base)
                row.update({
                    "row_kind": "orphan",
                    "in_no": "", "in_time": None,
                    "qty": 0.0, "price": 0.0, "amount": 0.0,
                    "out_no": lg.doc_no, "out_time": ts,
                    "out_qty": float(need), "out_amount": 0.0,
                    "stock_qty": None, "stock_amount": None,
                })
                result.append(row)

        # ---------- 未消耗批次 = 当前库存行 ----------
        for batch in batches:
            if batch["qty_rem"] <= ZERO:
                continue
            row = _row_common(db=db, warehouse=warehouse, product=product, meta={})
            row.update({
                "row_kind": "normal",
                "in_no": batch["doc_no"],
                "in_time": (batch["time"].isoformat(sep=" ", timespec="seconds")
                            if batch["time"] else None),
                "qty": float(batch["qty"]), "price": float(batch["price"]),
                "amount": float(batch["qty"] * batch["price"]),
                "out_no": "", "out_time": None, "out_qty": 0.0, "out_amount": 0.0,
                "stock_qty": float(batch["qty_rem"]),
                "stock_amount": float(batch["qty_rem"] * batch["price"]),
            })
            result.append(row)

    if date_from:
        result = [r for r in result if (r["in_time"] or "")[:10] >= date_from]
    if date_to:
        result = [r for r in result if (r["in_time"] or "")[:10] <= date_to]
    result.sort(key=lambda r: (r["in_time"] or ""), reverse=True)
    return result


BATCH_COLUMNS: list[tuple[str, int]] = [
    ("行类型", 10), ("仓库", 14), ("入库单号", 18), ("入库时间", 20), ("资产编号", 14), ("物料名称", 24),
    ("规格", 16), ("单位", 8), ("数量", 10), ("单价", 12), ("金额", 14),
    ("出库单号", 18), ("出库时间", 20), ("出库数量", 10), ("出库金额", 14),
    ("出库类型", 12), ("出库项目", 24), ("领用方", 14), ("库存数量", 10), ("库存金额", 14),
]

BATCH_KEYS = ["row_kind", "warehouse", "in_no", "in_time", "product_code", "product_name", "spec",
              "uom", "qty", "price", "amount", "out_no", "out_time", "out_qty",
              "out_amount", "out_type", "out_project", "issue_party", "stock_qty",
              "stock_amount"]

ROW_KIND_LABELS: dict[str, str] = {
    "normal": "正常配对",
    "reversal": "红冲",
    "orphan": "无批次出库",
}
