"""库存批次配对报表（CR-011）演示数据：入库批次 + FIFO 出库消耗。

用法（项目根目录）：
    app\\.venv\\Scripts\\python.exe -m app.tools.seed_stock_demo
    app\\.venv\\Scripts\\python.exe -m app.tools.seed_stock_demo --report   # 顺便打印报表

生成的数据（固定前缀 `DEMO26`，可重复执行，已存在的编码/单号会跳过）：
  仓库：演示仓-DEMO
  物料：DEMO26-A（规格 A-100）、DEMO26-B（规格 B-200）
  入库：A 100@10 / 80@12 / 60@14；B 50@20（不同日期=不同批次）
  出库：A 120（吃掉批次1全部 + 批次2 的 20）、A 50、A 10（批次2 清空）、
        B 40（领用出库，带领用人 + 备注=出库项目）
预期：A 批次1 全部消耗、批次2 全部消耗、批次3 剩 60；B 剩 10。
全部单据**真实过账**（stock + ledger 同步），因此报表与结存口径可交叉验证。
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
from app.services import posting_service

PREFIX = "DEMO26"
SUBJECT = ("ZC", "智澈公司")


def _admin(db) -> User:
    user = db.execute(select(User).where(User.username == "admin")).scalar_one_or_none()
    if user is None:
        user = db.execute(select(User)).scalars().first()
    assert user is not None, "没有可用账号，请先运行 python -m app.init_db"
    return user


def _ensure_masters(db):
    uom = db.execute(select(Uom).where(Uom.code == f"{PREFIX}-PCS")).scalar_one_or_none()
    if uom is None:
        uom = Uom(code=f"{PREFIX}-PCS", name="个", decimals=0)
        db.add(uom)
        db.flush()
    ptype = db.execute(select(ProductType).where(ProductType.code == f"{PREFIX}-T")).scalar_one_or_none()
    if ptype is None:
        ptype = ProductType(code=f"{PREFIX}-T", name="演示类型", path="/", level=1)
        db.add(ptype)
        db.flush()
    warehouse = db.execute(select(Warehouse).where(Warehouse.code == f"{PREFIX}-WH")).scalar_one_or_none()
    if warehouse is None:
        warehouse = Warehouse(code=f"{PREFIX}-WH", name="演示仓-DEMO", enabled=True,
                              subject_code=SUBJECT[0])
        db.add(warehouse)
        db.flush()
    products = {}
    for suffix, name, spec, price in (("A", "演示物料A", "A-100", "10"),
                                      ("B", "演示物料B", "B-200", "20")):
        code = f"{PREFIX}-{suffix}"
        p = db.execute(select(Product).where(Product.code == code)).scalar_one_or_none()
        if p is None:
            p = Product(code=code, name=name, spec=spec, product_type_id=ptype.id,
                        uom_id=uom.id, default_price=Decimal(price), status="enabled")
            db.add(p)
            db.flush()
        products[suffix] = p
    db.commit()
    return warehouse, products


def _exists(db, model, doc_no: str) -> bool:
    return db.execute(select(model.id).where(model.doc_no == doc_no)).first() is not None


def _make_in(db, warehouse, product, qty: str, price: str, doc_date: date, no: str):
    if _exists(db, StockInOrder, no):
        return None
    admin = _admin(db)
    doc = StockInOrder(
        doc_no=no, doc_date=doc_date, status="approved",
        created_by=admin.id, created_by_name=admin.real_name,
        subject_code=SUBJECT[0], subject_name=SUBJECT[1],
        warehouse_id=warehouse.id, warehouse_name=warehouse.name,
        in_type="采购入库", posted=False,
    )
    db.add(doc)
    db.flush()
    doc.items.append(StockInOrderItem(
        seq=1, product_id=product.id, product_code=product.code, product_name=product.name,
        spec=product.spec, uom_name="个", uom_decimals=0,
        qty=Decimal(qty), unit_price=Decimal(price),
        amount=Decimal(qty) * Decimal(price), warehouse_id=warehouse.id,
    ))
    db.commit()
    posting_service.post_stock_doc(db, doc, user=admin)
    db.commit()
    return doc


def _make_out(db, warehouse, product, qty: str, doc_date: date, no: str, *,
              out_type: str = "销售出库", issue: tuple[str, int, str] | None = None,
              remark: str | None = None):
    if _exists(db, StockOutOrder, no):
        return None
    admin = _admin(db)
    doc = StockOutOrder(
        doc_no=no, doc_date=doc_date, status="submitted",
        created_by=admin.id, created_by_name=admin.real_name,
        subject_code=SUBJECT[0], subject_name=SUBJECT[1],
        warehouse_id=warehouse.id, warehouse_name=warehouse.name,
        out_type=out_type, posted=False, remark=remark,
    )
    if issue:
        doc.issue_party_type, doc.issue_party_id, doc.issue_party_name = issue
    db.add(doc)
    db.flush()
    doc.items.append(StockOutOrderItem(
        seq=1, product_id=product.id, product_code=product.code, product_name=product.name,
        spec=product.spec, uom_name="个", uom_decimals=0,
        qty=Decimal(qty), unit_price=Decimal("0"), amount=Decimal("0"),
        warehouse_id=warehouse.id,
    ))
    db.commit()
    posting_service.approve_stock_doc(db, doc, user=admin)
    db.commit()
    return doc


def seed(abnormal: bool = False) -> dict:
    """造演示数据。`abnormal=True` 时额外造：① 红冲（反审核 OUT-A3）
    ② 无入库批次的出库流水（直接插 ledger，模拟期初缺失——过账层会拦负库存，故只能这样演示）。"""
    with SessionLocal() as db:
        warehouse, products = _ensure_masters(db)
        a, b = products["A"], products["B"]
        # 入库批次
        _make_in(db, warehouse, a, "100", "10", date(2026, 9, 1), f"{PREFIX}-IN-A1")
        _make_in(db, warehouse, a, "80", "12", date(2026, 9, 5), f"{PREFIX}-IN-A2")
        _make_in(db, warehouse, a, "60", "14", date(2026, 9, 10), f"{PREFIX}-IN-A3")
        _make_in(db, warehouse, b, "50", "20", date(2026, 9, 2), f"{PREFIX}-IN-B1")
        # 出库（FIFO 消耗）
        _make_out(db, warehouse, a, "120", date(2026, 9, 12), f"{PREFIX}-OUT-A1",
                  remark="演示项目-首批出库")
        _make_out(db, warehouse, a, "50", date(2026, 9, 18), f"{PREFIX}-OUT-A2",
                  remark="演示项目-补货出库")
        _make_out(db, warehouse, a, "10", date(2026, 9, 20), f"{PREFIX}-OUT-A3",
                  remark="演示项目-零头出库")
        _make_out(db, warehouse, b, "40", date(2026, 9, 15), f"{PREFIX}-OUT-B1",
                  out_type="领用出库", issue=("user", _admin(db).id, "演示领用人"),
                  remark="演示项目-领用")
        info = {"warehouse_id": warehouse.id, "product_ids": [a.id, b.id]}
        if abnormal:
            info["abnormal"] = "reversal+orphan"
            # ① 红冲：反审核 OUT-A3（10 个），产生「红冲-销售出库」流水
            out_a3 = db.execute(select(StockOutOrder).where(
                StockOutOrder.doc_no == f"{PREFIX}-OUT-A3")).scalar_one_or_none()
            if out_a3 is not None and out_a3.status == "approved":
                posting_service.unapprove_stock_doc(db, out_a3, "演示红冲", _admin(db))
                db.commit()
            # ② 无批次出库：期末缺失场景——物料 C 没有任何入库批次，只有一条出库流水
            c = db.execute(select(Product).where(
                Product.code == f"{PREFIX}-C")).scalar_one_or_none()
            if c is None:
                c = Product(code=f"{PREFIX}-C", name="演示物料C（期初缺失）", spec="C-300",
                            product_type_id=a.product_type_id, uom_id=a.uom_id,
                            default_price=Decimal("30"), status="enabled")
                db.add(c)
                db.flush()
                db.commit()
            if c.id not in info["product_ids"]:
                info["product_ids"].append(c.id)
            exists = db.execute(select(StockLedger.id).where(
                StockLedger.doc_no == f"{PREFIX}-ORPHAN-OUT1")).first()
            if exists is None:
                db.add(StockLedger(
                    product_id=c.id, warehouse_id=warehouse.id,
                    biz_type="历史出库补录", doc_type="stock_out", doc_id=0,
                    doc_no=f"{PREFIX}-ORPHAN-OUT1", src_doc_no=None,
                    qty_change=Decimal("-15"), qty_after=Decimal("0"),
                    unit_price=Decimal("30"), remark="演示：期初缺失导致的出库无批次",
                ))
                db.commit()
        return info


def purge() -> dict:
    """清除本脚本产生的演示数据（单据/流水/结存/主数据），供测试清理与重跑。"""
    from sqlalchemy import delete as _delete

    from app.models_stock import Stock, StockLedger
    from app.models_doc import StockInOrderItem, StockOutOrderItem

    removed = {}
    with SessionLocal() as db:
        in_ids = [r[0] for r in db.execute(
            select(StockInOrder.id).where(StockInOrder.doc_no.like(f"{PREFIX}-%"))).all()]
        out_ids = [r[0] for r in db.execute(
            select(StockOutOrder.id).where(StockOutOrder.doc_no.like(f"{PREFIX}-%"))).all()]
        prod_ids = [r[0] for r in db.execute(
            select(Product.id).where(Product.code.like(f"{PREFIX}-%"))).all()]

        if prod_ids:
            removed["ledger"] = db.execute(
                _delete(StockLedger).where(StockLedger.product_id.in_(prod_ids))).rowcount
            removed["stock"] = db.execute(
                _delete(Stock).where(Stock.product_id.in_(prod_ids))).rowcount
        if in_ids:
            removed["in_items"] = db.execute(
                _delete(StockInOrderItem).where(StockInOrderItem.doc_id.in_(in_ids))).rowcount
            removed["in_docs"] = db.execute(
                _delete(StockInOrder).where(StockInOrder.id.in_(in_ids))).rowcount
        if out_ids:
            removed["out_items"] = db.execute(
                _delete(StockOutOrderItem).where(StockOutOrderItem.doc_id.in_(out_ids))).rowcount
            removed["out_docs"] = db.execute(
                _delete(StockOutOrder).where(StockOutOrder.id.in_(out_ids))).rowcount
        if prod_ids:
            removed["products"] = db.execute(
                _delete(Product).where(Product.id.in_(prod_ids))).rowcount
        wh_ids = [r[0] for r in db.execute(
            select(Warehouse.id).where(Warehouse.code.like(f"{PREFIX}-%"))).all()]
        if wh_ids:
            removed["warehouses"] = db.execute(
                _delete(Warehouse).where(Warehouse.id.in_(wh_ids))).rowcount
        pt_ids = [r[0] for r in db.execute(
            select(ProductType.id).where(ProductType.code.like(f"{PREFIX}-%"))).all()]
        if pt_ids:
            removed["ptypes"] = db.execute(
                _delete(ProductType).where(ProductType.id.in_(pt_ids))).rowcount
        u_ids = [r[0] for r in db.execute(
            select(Uom.id).where(Uom.code.like(f"{PREFIX}-%"))).all()]
        if u_ids:
            removed["uoms"] = db.execute(_delete(Uom).where(Uom.id.in_(u_ids))).rowcount
        db.commit()
    return removed


def print_report() -> None:
    from app.services import stock_report_service as svc

    with SessionLocal() as db:
        rows = svc.build_batches(db, warehouse_id=None, keyword=PREFIX)
    if not rows:
        print("（没有报表数据）")
        return
    cols = ["warehouse", "in_no", "product_code", "qty", "price", "out_no", "out_qty",
            "out_amount", "out_type", "out_project", "issue_party", "stock_qty", "stock_amount"]
    head = ["仓库", "入库单号", "物料", "入库量", "单价", "出库单号", "出库量",
            "出库金额", "类型", "出库项目", "领用方", "剩余", "剩余金额"]
    print(" | ".join(f"{h}" for h in head))
    print("-" * 120)
    for r in rows:
        vals = []
        for k in cols:
            v = r.get(k)
            vals.append(ROW_KIND_LABELS.get(v, v) if k == "row_kind" else ("" if v is None else v))
        print(" | ".join(str(v) for v in vals))
    print("-" * 120)
    def _s(key):
        return sum((r[key] or 0) for r in rows)
    counts = {}
    for r in rows:
        counts[r["row_kind"]] = counts.get(r["row_kind"], 0) + 1
    print(f"共 {len(rows)} 行（" + "、".join(
        f"{ROW_KIND_LABELS.get(k, k)} {v}" for k, v in counts.items()) + "）；"
          f"正常出库量 {sum(r['out_qty'] for r in rows if r['row_kind'] == 'normal'):.0f}，"
          f"剩余合计 {_s('stock_qty'):.0f}，剩余金额 {_s('stock_amount'):.2f}")


if __name__ == "__main__":
    info = seed(abnormal="--abnormal" in sys.argv)
    print("演示数据就绪:", info)
    if "--purge" in sys.argv:
        print("清理结果:", purge())
        sys.exit(0)
    if "--report" in sys.argv or "--abnormal" in sys.argv:
        print()
        print_report()
