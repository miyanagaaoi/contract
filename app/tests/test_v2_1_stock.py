"""V2.1 / T-V2.1-12 · 13 测试：库存明细「货品总额度」与数量/物料类型筛选。

覆盖 `22-v2.1-requirements.md`：
- BR-V2.1-09 / AC-V2.1-11：货品总额度 = 该 `(物料 × 仓库)` 的**入库批次金额合计**；
- AC-V2.1-12：数量区间筛选。

⚠️ 本文件重点锁死 `23-v2.1-system-design.md` §7.1 指出的两个**极易写错**的口径：
1. **不能用 `qty_change > 0` 判"入库方向"**——红冲入库的 `qty_change` 为负，若按正负过滤
   就会被漏掉，导致**冲减失效、额度虚高**；
2. **必须排除「调拨入库」**（含其红冲），否则同一批货在仓库间搬运会反复放大额度。

调拨功能（T-V2.1-13~15）尚未实现，故此处用 `StockLedger` 直接构造流水来验证聚合口径，
使该口径**不依赖调拨功能的开发进度**即可被固化。
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_master import Product, ProductType, Uom, Warehouse
from app.models_stock import Stock, StockLedger
from app.routers.stock import _inbound_amount_subquery


@pytest.fixture()
def db():
    with SessionLocal() as s:
        yield s


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def h(client):
    resp = client.post("/api/auth/login",
                       json={"username": ADMIN_USERNAME, "password": ADMIN_INIT_PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _sfx() -> str:
    return uuid.uuid4().hex[:6]


def _mk_product(db) -> Product:
    sfx = _sfx()
    uom = Uom(code=f"U{sfx}", name=f"个{sfx}", decimals=0)
    db.add(uom)
    db.flush()
    ptype = ProductType(name=f"类型{sfx}")
    db.add(ptype)
    db.flush()
    product = Product(code=f"P{sfx}", name=f"物料{sfx}", spec="规格Y",
                      product_type_id=ptype.id, uom_id=uom.id)
    db.add(product)
    db.commit()
    return product


def _mk_warehouse(db) -> Warehouse:
    sfx = _sfx()
    wh = Warehouse(code=f"W{sfx}", name=f"仓库{sfx}")
    db.add(wh)
    db.commit()
    return wh


def _ledger(db, product, warehouse, biz_type: str, qty: str, price: str, after: str) -> None:
    """直接写一条库存流水（绕过单据，便于精确构造口径场景）。"""
    db.add(StockLedger(
        product_id=product.id, warehouse_id=warehouse.id, biz_type=biz_type,
        doc_type="stock_in_order", doc_id=1, doc_no=f"T{_sfx()}",
        qty_change=Decimal(qty), qty_after=Decimal(after), unit_price=Decimal(price),
    ))


def _stock_with_ledger(db, product, warehouse, qty: str, price: str = "5") -> Stock:
    """建结存**并配一条等量入库流水**。

    ⚠️ 必须保持 `stocks.qty == SUM(stock_ledger.qty_change)` 不变式（AC-V2-26）：
    只建 `Stock` 而不写流水，会污染 `test_v2_docs.py::test_recalc_consistent`
    的全局一致性校验（recalc 会遍历所有 stocks 行）。
    """
    amount = Decimal(qty)
    stock = Stock(product_id=product.id, warehouse_id=warehouse.id, qty=amount)
    db.add(stock)
    _ledger(db, product, warehouse, "采购入库", qty, price, qty)
    return stock


def _inbound_amount(db, product_id: int, warehouse_id: int) -> Decimal:
    sub = _inbound_amount_subquery(db)
    row = (db.query(sub.c.inbound_amount)
           .filter(sub.c.product_id == product_id, sub.c.warehouse_id == warehouse_id)
           .first())
    return Decimal(row[0]) if row and row[0] is not None else Decimal("0")


# ---------------------------------------------------------------- 聚合口径（核心）

class TestInboundAmount:
    def test_入库批次金额合计(self, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        _ledger(db, product, wh, "采购入库", "10", "5", "10")
        _ledger(db, product, wh, "采购入库", "5", "6", "15")
        db.commit()

        assert _inbound_amount(db, product.id, wh.id) == Decimal("80")  # 10*5 + 5*6

    def test_红冲负向冲减(self, db):
        """⚠️ 关键回归点：若用 `qty_change > 0` 过滤，本用例会失败（冲减失效）。"""
        product, wh = _mk_product(db), _mk_warehouse(db)
        _ledger(db, product, wh, "采购入库", "10", "5", "10")
        _ledger(db, product, wh, "红冲-采购入库", "-10", "5", "0")
        db.commit()

        assert _inbound_amount(db, product.id, wh.id) == Decimal("0")

    def test_调拨入库不计入(self, db):
        """⚠️ 关键回归点：调拨是仓库间搬运，不得放大额度。"""
        product, wh = _mk_product(db), _mk_warehouse(db)
        _ledger(db, product, wh, "采购入库", "10", "5", "10")
        _ledger(db, product, wh, "调拨入库", "7", "9", "17")
        _ledger(db, product, wh, "红冲-调拨入库", "-7", "9", "10")
        db.commit()

        assert _inbound_amount(db, product.id, wh.id) == Decimal("50")

    def test_出库不影响额度(self, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        _ledger(db, product, wh, "采购入库", "10", "5", "10")
        _ledger(db, product, wh, "销售出库", "-4", "5", "6")
        db.commit()

        assert _inbound_amount(db, product.id, wh.id) == Decimal("50")

    def test_其他入库计入_盘盈计入(self, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        _ledger(db, product, wh, "其他入库", "2", "3", "2")
        _ledger(db, product, wh, "盘盈入库", "1", "4", "3")
        db.commit()

        assert _inbound_amount(db, product.id, wh.id) == Decimal("10")

    def test_缺失单价按零计入(self, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        db.add(StockLedger(product_id=product.id, warehouse_id=wh.id, biz_type="采购入库",
                           doc_type="stock_in_order", doc_id=1, doc_no=f"T{_sfx()}",
                           qty_change=Decimal("3"), qty_after=Decimal("3"), unit_price=None))
        db.commit()

        assert _inbound_amount(db, product.id, wh.id) == Decimal("0")

    def test_按物料与仓库分别聚合(self, db):
        """不跨仓库合并：同一物料在两个仓库各自独立计算。"""
        product = _mk_product(db)
        wh1, wh2 = _mk_warehouse(db), _mk_warehouse(db)
        _ledger(db, product, wh1, "采购入库", "10", "5", "10")
        _ledger(db, product, wh2, "采购入库", "2", "7", "2")
        db.commit()

        assert _inbound_amount(db, product.id, wh1.id) == Decimal("50")
        assert _inbound_amount(db, product.id, wh2.id) == Decimal("14")


# ---------------------------------------------------------------- HTTP 契约

class TestBalancesApi:
    def test_列表返回货品总额度(self, client, h, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        db.add(Stock(product_id=product.id, warehouse_id=wh.id, qty=Decimal("12")))
        _ledger(db, product, wh, "采购入库", "10", "5", "10")
        _ledger(db, product, wh, "采购入库", "2", "6", "12")
        db.commit()

        resp = client.get("/api/stock/balances", headers=h, params={"keyword": product.code})
        assert resp.status_code == 200, resp.text
        row = next(r for r in resp.json()["items"] if r["product_id"] == product.id)
        assert row["qty"] == 12.0
        assert row["inbound_amount"] == 62.0     # 10*5 + 2*6

    def test_数量区间筛选(self, client, h, db):
        low, high = _mk_product(db), _mk_product(db)
        wh = _mk_warehouse(db)
        _stock_with_ledger(db, low, wh, "3")
        _stock_with_ledger(db, high, wh, "30")
        db.commit()

        resp = client.get("/api/stock/balances", headers=h, params={"qty_min": 5, "qty_max": 50})
        assert resp.status_code == 200, resp.text
        ids = {r["product_id"] for r in resp.json()["items"]}
        assert high.id in ids
        assert low.id not in ids

    def test_物料类型筛选含父类型下全部叶子(self, client, h, db):
        sfx = _sfx()
        uom = Uom(code=f"U{sfx}", name=f"个{sfx}", decimals=0)
        db.add(uom)
        db.flush()
        parent = ProductType(name=f"父{sfx}", code=f"PT{sfx}")
        db.add(parent)
        db.flush()
        parent.path = f"/{parent.id}/"
        child = ProductType(name=f"子{sfx}", parent_id=parent.id, level=2)
        db.add(child)
        db.flush()
        child.path = f"/{parent.id}/{child.id}/"
        product = Product(code=f"P{sfx}", name=f"物料{sfx}", product_type_id=child.id, uom_id=uom.id)
        db.add(product)
        db.flush()
        wh = _mk_warehouse(db)
        _stock_with_ledger(db, product, wh, "4")
        db.commit()

        resp = client.get("/api/stock/balances", headers=h,
                          params={"product_type_id": parent.id, "keyword": product.code})
        assert resp.status_code == 200, resp.text
        assert any(r["product_id"] == product.id for r in resp.json()["items"]), \
            "选中父类型应包含其叶子类型下的物料"
