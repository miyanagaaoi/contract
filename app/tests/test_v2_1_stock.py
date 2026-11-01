"""库存明细「当前库存总额度」与数量/类型筛选（CR-029 口径重写）。

口径（2026-11-01 业务确认，方案 A）：
    **当前库存总额度 = Σ(该仓库该物料的 FIFO 未消耗批次剩余数量 × 批次入库单价)**
    —— 与批次配对报表「剩余金额合计」同源同口径（`stock_value_map` 复用 `build_batches`）。

因此本文件锁死的是「剩余批次金额」，而不是旧的“累计入库金额合计”：
- 入库形成批次；出库按 FIFO 消耗（金额随之减少）；红冲按反向冲减/归还；
- 调拨入库单价为 0（BR-V2.1-08），不增加金额；
- 缺失单价按 0 计。
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
from app.services.stock_report_service import stock_value_map


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


def _ledger(db, product, warehouse, biz_type: str, qty: str, price: str | None,
            after: str, doc_no: str | None = None) -> None:
    """直接写一条库存流水（绕过单据，便于精确构造口径场景）。"""
    db.add(StockLedger(
        product_id=product.id, warehouse_id=warehouse.id, biz_type=biz_type,
        doc_type="stock_in_order", doc_id=1, doc_no=doc_no or f"T{_sfx()}",
        qty_change=Decimal(qty), qty_after=Decimal(after),
        unit_price=None if price is None else Decimal(price),
    ))


def _stock_with_ledger(db, product, warehouse, qty: str, price: str = "5") -> Stock:
    """建结存并配一条等量入库流水（保持 stocks.qty == SUM(ledger.qty_change)）。"""
    amount = Decimal(qty)
    stock = Stock(product_id=product.id, warehouse_id=warehouse.id, qty=amount,
                  stock_value=amount * Decimal(price))     # CR-032：金额列与流水同步
    db.add(stock)
    _ledger(db, product, warehouse, "采购入库", qty, price, qty)
    return stock


def _stock_amount(db, product_id: int, warehouse_id: int) -> Decimal:
    return stock_value_map(db, {(warehouse_id, product_id)}).get(
        (warehouse_id, product_id), Decimal("0"))


class TestStockAmount:
    def test_入库批次剩余金额合计(self, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        _ledger(db, product, wh, "采购入库", "10", "5", "10")
        _ledger(db, product, wh, "采购入库", "5", "6", "15")
        db.commit()
        assert _stock_amount(db, product.id, wh.id) == Decimal("80")   # 10*5 + 5*6

    def test_出库按FIFO减少金额(self, db):
        """入库 10@5 + 5@6，出库 12 → 剩 3@6，金额 18。"""
        product, wh = _mk_product(db), _mk_warehouse(db)
        doc = f"T{_sfx()}"
        _ledger(db, product, wh, "采购入库", "10", "5", "10", doc_no=f"{doc}-1")
        _ledger(db, product, wh, "采购入库", "5", "6", "15", doc_no=f"{doc}-2")
        _ledger(db, product, wh, "销售出库", "-12", "5", "3", doc_no=f"{doc}-OUT")
        db.commit()
        assert _stock_amount(db, product.id, wh.id) == Decimal("18")

    def test_红冲入库冲减金额(self, db):
        """红冲入库（同单号）应冲减该批次剩余 → 金额归零。"""
        product, wh = _mk_product(db), _mk_warehouse(db)
        doc = f"T{_sfx()}"
        _ledger(db, product, wh, "采购入库", "10", "5", "10", doc_no=doc)
        _ledger(db, product, wh, "红冲-采购入库", "-10", "5", "0", doc_no=doc)
        db.commit()
        assert _stock_amount(db, product.id, wh.id) == Decimal("0")

    def test_调拨入库单价为零不增加金额(self, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        _ledger(db, product, wh, "采购入库", "10", "5", "10")
        _ledger(db, product, wh, "调拨入库", "7", "0", "17")
        db.commit()
        assert _stock_amount(db, product.id, wh.id) == Decimal("50")

    def test_其他入库与盘盈计入(self, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        _ledger(db, product, wh, "其他入库", "2", "3", "2")
        _ledger(db, product, wh, "盘盈入库", "1", "4", "3")
        db.commit()
        assert _stock_amount(db, product.id, wh.id) == Decimal("10")

    def test_缺失单价按零计入(self, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        _ledger(db, product, wh, "采购入库", "3", None, "3")
        db.commit()
        assert _stock_amount(db, product.id, wh.id) == Decimal("0")

    def test_按物料与仓库分别聚合(self, db):
        product = _mk_product(db)
        wh1, wh2 = _mk_warehouse(db), _mk_warehouse(db)
        _ledger(db, product, wh1, "采购入库", "10", "5", "10")
        _ledger(db, product, wh2, "采购入库", "2", "7", "2")
        db.commit()
        assert _stock_amount(db, product.id, wh1.id) == Decimal("50")
        assert _stock_amount(db, product.id, wh2.id) == Decimal("14")


class TestBalancesApi:
    def test_列表返回当前库存总额度(self, client, h, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        db.add(Stock(product_id=product.id, warehouse_id=wh.id, qty=Decimal("12"),
                     stock_value=Decimal("62")))
        _ledger(db, product, wh, "采购入库", "10", "5", "10")
        _ledger(db, product, wh, "采购入库", "2", "6", "12")
        db.commit()

        resp = client.get("/api/stock/balances", headers=h, params={"keyword": product.code})
        assert resp.status_code == 200, resp.text
        row = next(r for r in resp.json()["items"] if r["product_id"] == product.id)
        assert row["qty"] == 12.0
        assert row["stock_amount"] == 62.0          # 10*5 + 2*6（无出库，等于批次剩余）
        assert "inbound_amount" not in row

    def test_列表金额与批次报表剩余金额一致(self, client, h, db):
        """CR-029 核心：两处口径必须同源一致（同一 (仓库,物料)）。"""
        from app.services import stock_report_service as svc

        product, wh = _mk_product(db), _mk_warehouse(db)
        db.add(Stock(product_id=product.id, warehouse_id=wh.id, qty=Decimal("7"),
                     stock_value=Decimal("35")))
        _ledger(db, product, wh, "采购入库", "10", "5", "10")
        _ledger(db, product, wh, "销售出库", "-3", "5", "7")
        db.commit()

        resp = client.get("/api/stock/balances", headers=h, params={"keyword": product.code})
        row = next(r for r in resp.json()["items"] if r["product_id"] == product.id)

        rows = svc.build_batches(db, product_id=product.id, warehouse_id=wh.id)
        report_value = sum(r["stock_amount"] or 0 for r in rows if r["stock_qty"])
        assert row["stock_amount"] == report_value == 35.0   # 7 × 5

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
        product = Product(code=f"P{sfx}", name=f"物料{sfx}", product_type_id=child.id,
                          uom_id=uom.id)
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
