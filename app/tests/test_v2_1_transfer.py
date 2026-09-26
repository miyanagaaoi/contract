"""V2.1 / T-V2.1-14 · 15 · 16 测试：库存调拨单据域。

覆盖 `22-v2.1-requirements.md`：
- AC-V2.1-13 调拨单创建（自动编号、两仓、行项）
- AC-V2.1-14 两仓不可相同 + 提交待审核
- AC-V2.1-15 审核后**同事务**过账：调出仓减、调入仓加，两条同凭证号流水
- AC-V2.1-16 调出仓不足拦截（结存与状态均不变）
- AC-V2.1-17 幂等（重复审核不重复过账）
- AC-V2.1-18 反审核红冲（追加反向流水，两仓结存回滚）

调拨是本版唯一"一单双向"的单据：审核一次要同时改两个仓库，因此这里的**事务性**与
**幂等性**是关键断言点（`23-v2.1-system-design.md` §6）。
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

TRANSFER = "/api/stock/transfers"


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
    product = Product(code=f"P{sfx}", name=f"物料{sfx}", spec="规格Z",
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


def _seed_stock(db, product, warehouse, qty: str) -> None:
    """给仓库预置结存，并配等量入库流水（维持 `qty == SUM(qty_change)` 不变式）。"""
    amount = Decimal(qty)
    db.add(Stock(product_id=product.id, warehouse_id=warehouse.id, qty=amount))
    db.add(StockLedger(
        product_id=product.id, warehouse_id=warehouse.id, biz_type="采购入库",
        doc_type="stock_in_order", doc_id=1, doc_no=f"SEED{_sfx()}",
        qty_change=amount, qty_after=amount, unit_price=Decimal("5"),
    ))
    db.commit()


def _ledgers(db, doc_id: int) -> list[StockLedger]:
    return (db.query(StockLedger)
            .filter(StockLedger.doc_type == "stock_transfer", StockLedger.doc_id == doc_id)
            .order_by(StockLedger.id.asc()).all())


def _qty(db, product_id: int, warehouse_id: int) -> Decimal:
    row = (db.query(Stock)
           .filter(Stock.product_id == product_id, Stock.warehouse_id == warehouse_id).first())
    return Decimal(row.qty) if row else Decimal("0")


def _create(client, h, product, wh_from, wh_to, qty="6"):
    return client.post(TRANSFER, headers=h, json={
        "doc_date": "2026-03-01",
        "from_warehouse_id": wh_from.id, "to_warehouse_id": wh_to.id,
        "items": [{"product_id": product.id, "qty": qty, "unit_price": 0}],
    })


def _approve(client, h, doc_id: int):
    client.post(f"{TRANSFER}/{doc_id}/submit", headers=h)
    return client.post(f"{TRANSFER}/{doc_id}/approve", headers=h)


# ---------------------------------------------------------------- 创建与校验

class TestTransferCreate:
    def test_创建调拨单并自动生成编号(self, client, h, db):
        product = _mk_product(db)
        wh1, wh2 = _mk_warehouse(db), _mk_warehouse(db)

        resp = _create(client, h, product, wh1, wh2)
        assert resp.status_code == 200, resp.text
        doc = resp.json()

        assert doc["doc_no"].startswith("DB"), "调拨单编号前缀应为 DB"
        assert doc["status"] == "draft"
        assert doc["from_warehouse_name"] == wh1.name
        assert doc["to_warehouse_name"] == wh2.name
        assert doc["from_warehouse_id"] == wh1.id

    def test_两仓相同被拒(self, client, h, db):
        product = _mk_product(db)
        wh = _mk_warehouse(db)

        resp = _create(client, h, product, wh, wh)
        assert resp.status_code == 422, resp.text
        assert "不能相同" in resp.text

    def test_缺少仓库被拒(self, client, h, db):
        product = _mk_product(db)
        wh = _mk_warehouse(db)

        resp = client.post(TRANSFER, headers=h, json={
            "doc_date": "2026-03-01", "from_warehouse_id": wh.id,
            "items": [{"product_id": product.id, "qty": 1, "unit_price": 0}],
        })
        assert resp.status_code == 422, resp.text
        assert "调入仓库" in resp.text

    def test_提交后待审核(self, client, h, db):
        product = _mk_product(db)
        wh1, wh2 = _mk_warehouse(db), _mk_warehouse(db)
        doc = _create(client, h, product, wh1, wh2).json()

        resp = client.post(f"{TRANSFER}/{doc['id']}/submit", headers=h)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "submitted"


# ---------------------------------------------------------------- 过账（核心）

class TestTransferPosting:
    def test_审核后两仓同事务过账(self, client, h, db):
        product = _mk_product(db)
        wh1, wh2 = _mk_warehouse(db), _mk_warehouse(db)
        _seed_stock(db, product, wh1, "10")

        doc = _create(client, h, product, wh1, wh2, qty="6").json()
        resp = _approve(client, h, doc["id"])
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "approved"

        with SessionLocal() as s:
            assert _qty(s, product.id, wh1.id) == Decimal("4"), "调出仓应减少 6"
            assert _qty(s, product.id, wh2.id) == Decimal("6"), "调入仓应增加 6"

            rows = _ledgers(s, doc["id"])
            assert len(rows) == 2, "一张调拨单应产生两条流水"
            assert {r.biz_type for r in rows} == {"调拨出库", "调拨入库"}
            assert {r.doc_no for r in rows} == {doc["doc_no"]}, "两条流水同凭证号"
            changes = sorted(float(r.qty_change) for r in rows)
            assert changes == [-6.0, 6.0]

    def test_调出仓不足被拦截且不产生任何变更(self, client, h, db):
        product = _mk_product(db)
        wh1, wh2 = _mk_warehouse(db), _mk_warehouse(db)
        _seed_stock(db, product, wh1, "5")

        doc = _create(client, h, product, wh1, wh2, qty="8").json()
        resp = _approve(client, h, doc["id"])
        assert resp.status_code == 422, resp.text
        assert "库存不足" in resp.text

        with SessionLocal() as s:
            assert _qty(s, product.id, wh1.id) == Decimal("5"), "被拒后调出仓结存不得变化"
            assert _qty(s, product.id, wh2.id) == Decimal("0"), "不得写入调入仓"
            assert _ledgers(s, doc["id"]) == [], "不得留下任何流水"
            # 状态不得前进为已审核
            detail = client.get(f"{TRANSFER}/{doc['id']}", headers=h).json()
            assert detail["status"] != "approved"

    def test_重复审核幂等(self, client, h, db):
        product = _mk_product(db)
        wh1, wh2 = _mk_warehouse(db), _mk_warehouse(db)
        _seed_stock(db, product, wh1, "10")

        doc = _create(client, h, product, wh1, wh2, qty="3").json()
        assert _approve(client, h, doc["id"]).status_code == 200

        again = client.post(f"{TRANSFER}/{doc['id']}/approve", headers=h)
        assert again.status_code == 200, again.text

        with SessionLocal() as s:
            assert _qty(s, product.id, wh1.id) == Decimal("7"), "重复审核不得再次扣减"
            assert _qty(s, product.id, wh2.id) == Decimal("3")
            assert len(_ledgers(s, doc["id"])) == 2, "不得追加流水"

    def test_反审核红冲回滚两仓(self, client, h, db):
        product = _mk_product(db)
        wh1, wh2 = _mk_warehouse(db), _mk_warehouse(db)
        _seed_stock(db, product, wh1, "10")

        doc = _create(client, h, product, wh1, wh2, qty="4").json()
        assert _approve(client, h, doc["id"]).status_code == 200

        resp = client.post(f"{TRANSFER}/{doc['id']}/unapprove", headers=h,
                           json={"reason": "V2.1 测试红冲"})
        assert resp.status_code == 200, resp.text

        with SessionLocal() as s:
            assert _qty(s, product.id, wh1.id) == Decimal("10"), "红冲后调出仓应恢复"
            assert _qty(s, product.id, wh2.id) == Decimal("0"), "红冲后调入仓应归零"

            rows = _ledgers(s, doc["id"])
            assert len(rows) == 4, "红冲应追加两条反向流水（原流水保留可查）"
            biz = [r.biz_type for r in rows]
            assert "红冲-调拨出库" in biz and "红冲-调拨入库" in biz

    def test_调拨不产生金额且不计入货品总额度(self, client, h, db):
        """BR-V2.1-08/09：调拨是仓库间搬运，既无金额也不放大货品总额度。"""
        from app.routers.stock import _inbound_amount_subquery

        product = _mk_product(db)
        wh1, wh2 = _mk_warehouse(db), _mk_warehouse(db)
        _seed_stock(db, product, wh1, "10")          # 50 元入库金额

        doc = _create(client, h, product, wh1, wh2, qty="6").json()
        assert _approve(client, h, doc["id"]).status_code == 200

        with SessionLocal() as s:
            sub = _inbound_amount_subquery(s)
            rows = {r.warehouse_id: Decimal(r.inbound_amount or 0)
                    for r in s.query(sub).filter(sub.c.product_id == product.id).all()}

        assert rows.get(wh2.id, Decimal("0")) == Decimal("0"), \
            "调拨入库不得计入货品总额度"
        assert rows.get(wh1.id) == Decimal("50"), "调出仓的入库金额不受调拨出库影响"
