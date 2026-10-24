"""演示数据（10 条入库批次）——批次配对报表验收用。

用法（项目根目录）：
    python -m app.tools.seed_stock_demo10            # 清空全部演示数据后重建 10 批次
    python -m app.tools.seed_stock_demo10 --report   # 建完并打印报表（三类行）
    python -m app.tools.seed_stock_demo10 --purge    # 只清理，不建

口径说明：
- 清理范围=脚本生成的全部演示数据（DEMO26*/DEMO27* 前缀的仓库/物料/单据/流水/结存），
  **不触碰**业务真实数据与 `init_db --demo` 的历史演示数据；
- 10 个入库批次（3 个物料），配 4 张出库单（含 FIFO 跨批次）、1 张红冲（反审核）、
  1 条「无批次出库」流水（模拟期初缺失），用于同时验收正常/红冲/无批次三类行。
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models_auth import User
from app.models_doc import StockInOrder, StockInOrderItem, StockOutOrder, StockOutOrderItem
from app.models_master import Product, ProductType, Uom, Warehouse
from app.models_stock import Stock, StockLedger
from app.services import posting_service, stock_report_service

from . import seed_stock_demo as demo

PREFIX = "DEMO27"
SUBJECT = demo.SUBJECT

# (物料, 批次序号, 数量, 单价, 入库日期)
BATCHES = [
    ("P1", 1, "100", "10", date(2026, 10, 1)),
    ("P1", 2, "120", "11", date(2026, 10, 3)),
    ("P1", 3, "80", "12", date(2026, 10, 5)),
    ("P1", 4, "60", "13", date(2026, 10, 7)),
    ("P2", 1, "90", "20", date(2026, 10, 2)),
    ("P2", 2, "70", "21", date(2026, 10, 4)),
    ("P2", 3, "50", "22", date(2026, 10, 6)),
    ("P3", 1, "40", "30", date(2026, 10, 1)),
    ("P3", 2, "40", "31", date(2026, 10, 8)),
    ("P3", 3, "40", "32", date(2026, 10, 9)),
]

# (物料, 出库数量, 出库日期, 序号, 出库类型, 备注)
OUTS = [
    ("P1", "130", date(2026, 10, 10), 1, "销售出库", "演示-十月首单"),
    ("P2", "120", date(2026, 10, 11), 2, "销售出库", "演示-十月次单"),
    ("P1", "200", date(2026, 10, 12), 3, "销售出库", "演示-十月三单"),
    ("P3", "50", date(2026, 10, 13), 4, "领用出库", "演示-领用出库"),
]

PRODUCT_META = {
    "P1": ("演示物料P1", "P1-100", "10"),
    "P2": ("演示物料P2", "P2-200", "20"),
    "P3": ("演示物料P3", "P3-300", "30"),
}


def _admin(db) -> User:
    return demo._admin(db)


def _ensure_masters(db):
    uom = db.execute(select(Uom).where(Uom.code == f"{PREFIX}-PCS")).scalar_one_or_none()
    if uom is None:
        uom = Uom(code=f"{PREFIX}-PCS", name="个", decimals=0)
        db.add(uom)
        db.flush()
    ptype = db.execute(select(ProductType).where(
        ProductType.code == f"{PREFIX}-T")).scalar_one_or_none()
    if ptype is None:
        ptype = ProductType(code=f"{PREFIX}-T", name="演示类型-10批次", path="/", level=1)
        db.add(ptype)
        db.flush()
    warehouse = db.execute(select(Warehouse).where(
        Warehouse.code == f"{PREFIX}-WH")).scalar_one_or_none()
    if warehouse is None:
        warehouse = Warehouse(code=f"{PREFIX}-WH", name="演示仓-10批次", enabled=True,
                              subject_code=SUBJECT[0])
        db.add(warehouse)
        db.flush()
    products = {}
    for key, (name, spec, price) in PRODUCT_META.items():
        code = f"{PREFIX}-{key}"
        p = db.execute(select(Product).where(Product.code == code)).scalar_one_or_none()
        if p is None:
            p = Product(code=code, name=name, spec=spec, product_type_id=ptype.id,
                        uom_id=uom.id, default_price=Decimal(price), status="enabled")
            db.add(p)
            db.flush()
        products[key] = p
    db.commit()
    return warehouse, products


def _purge_derived_returns() -> int:
    """清理由演示出库单派生出的入库单（退库单号不以 DEMO 开头，需按来源单号清）。"""
    from sqlalchemy import delete as _delete

    from app.models_doc import StockInOrderItem

    removed = 0
    with SessionLocal() as db:
        ids = [r[0] for r in db.execute(
            select(StockInOrder.id).where(
                StockInOrder.source_doc_no.like(f"{PREFIX}-%")
                | StockInOrder.source_doc_no.like("DEMO26-%"))).all()]
        if ids:
            db.execute(_delete(StockInOrderItem).where(StockInOrderItem.doc_id.in_(ids)))
            removed = int(db.execute(_delete(StockInOrder).where(
                StockInOrder.id.in_(ids))).rowcount or 0)
            db.commit()
    return removed


def purge_all() -> dict:
    """清理脚本生成的全部演示数据（两个数据集前缀 + 由其派生的退库入库单）。"""
    derived = _purge_derived_returns()
    return {"derived_returns": derived,
            "DEMO26": demo.purge("DEMO26"), "DEMO27": demo.purge("DEMO27")}


def seed_ten(abnormal: bool = True) -> dict:
    with SessionLocal() as db:
        warehouse, products = _ensure_masters(db)
        for prod_key, seq, qty, price, d in BATCHES:
            demo._make_in(db, warehouse, products[prod_key], qty, price, d,
                          f"{PREFIX}-IN-{prod_key}{seq}")
        out_docs = {}
        for prod_key, qty, d, seq, out_type, remark in OUTS:
            issue = None
            if out_type == "领用出库":
                issue = ("user", _admin(db).id, "演示领用人")
            doc = demo._make_out(db, warehouse, products[prod_key], qty, d,
                                 f"{PREFIX}-OUT-{seq}", out_type=out_type,
                                 issue=issue, remark=remark)
            out_docs[seq] = doc
        info = {"warehouse_id": warehouse.id,
                "product_ids": [p.id for p in products.values()],
                "batches": len(BATCHES), "outs": len(OUTS)}
        if abnormal:
            # 红冲：反审核第 4 张出库（领用 50）→ 归还批次并产生红冲行
            d4 = out_docs.get(4)
            if d4 is not None and d4.status == "approved":
                posting_service.unapprove_stock_doc(db, d4, "演示红冲", _admin(db))
                db.commit()
            # 无批次出库：物料 P4 只有一条出库流水（模拟期初缺失）
            p4 = db.execute(select(Product).where(
                Product.code == f"{PREFIX}-P4")).scalar_one_or_none()
            if p4 is None:
                p4 = Product(code=f"{PREFIX}-P4", name="演示物料P4（期初缺失）", spec="P4-400",
                             product_type_id=products["P1"].product_type_id,
                             uom_id=products["P1"].uom_id,
                             default_price=Decimal("40"), status="enabled")
                db.add(p4)
                db.flush()
                info["product_ids"].append(p4.id)
            exists = db.execute(select(StockLedger.id).where(
                StockLedger.doc_no == f"{PREFIX}-ORPHAN-OUT1")).first()
            if exists is None:
                db.add(StockLedger(
                    product_id=p4.id, warehouse_id=warehouse.id,
                    biz_type="历史出库补录", doc_type="stock_out", doc_id=0,
                    doc_no=f"{PREFIX}-ORPHAN-OUT1", qty_change=Decimal("-25"),
                    qty_after=Decimal("0"), unit_price=Decimal("40"),
                    remark="演示：期初缺失导致出库无批次"))
                db.commit()
        return info


def print_summary() -> None:
    from app.services.stock_report_service import ROW_KIND_LABELS

    with SessionLocal() as db:
        rows = stock_report_service.build_batches(db, keyword=PREFIX)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["row_kind"]] = counts.get(r["row_kind"], 0) + 1
    print("数据集:", PREFIX, "| 行数:", len(rows), "|",
          "、".join(f"{ROW_KIND_LABELS[k]} {v}" for k, v in counts.items()))
    print("剩余合计:", sum(r["stock_qty"] or 0 for r in rows),
          "| 剩余金额:", round(sum(r["stock_amount"] or 0 for r in rows), 2))
    for r in rows:
        if r["row_kind"] != "normal":
            print(f"  [{ROW_KIND_LABELS[r['row_kind']]}] 出库={r['out_no']} "
                  f"数量={r['out_qty']:.0f} 物料={r['product_code']}")


if __name__ == "__main__":
    if "--purge" in sys.argv:
        print("清理结果:", purge_all())
        sys.exit(0)
    # 默认：先清空全部演示数据，再建 10 批次
    print("清理旧演示数据:", purge_all())
    info = seed_ten(abnormal="--no-abnormal" not in sys.argv)
    print("已生成 10 个批次:", info)
    if "--report" in sys.argv:
        print()
        print_summary()
