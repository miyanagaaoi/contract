"""CR-031 回归：库存单据单价/金额支持手工修改。

覆盖：
1. 入库单价手填 → 库存流水单价、批次报表「单价/库存金额」、库存明细金额一致；
2. 出库单价手填 → 出库流水单价（用于出库金额与退库金额），且不影响剩余批次金额；
3. 调拨单价手填 → 调拨两端流水同价，调入批次按该价进入「当前库存总额度」；
4. 已审核单据不可再改价（仅草稿/已提交可改）。
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_master import Product, ProductType, Uom, Warehouse
from app.models_stock import Stock, StockLedger
from app.services.stock_report_service import stock_value_map

IN = "/api/stock/in-orders"
OUT = "/api/stock/out-orders"
TRANSFER = "/api/stock/transfers"


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


@pytest.fixture()
def masters():
    """独立物料 + 两个仓库（不依赖演示数据）。"""
    with SessionLocal() as db:
        sfx = _sfx()
        uom = Uom(code=f"U{sfx}", name=f"个{sfx}", decimals=0)
        db.add(uom)
        db.flush()
        pt = ProductType(name=f"类型{sfx}")
        db.add(pt)
        db.flush()
        product = Product(code=f"P{sfx}", name=f"物料{sfx}", spec="规格P",
                          product_type_id=pt.id, uom_id=uom.id,
                          default_price=Decimal("3"))
        wh1 = Warehouse(code=f"W{sfx}1", name=f"仓1{sfx}")
        wh2 = Warehouse(code=f"W{sfx}2", name=f"仓2{sfx}")
        db.add_all([product, wh1, wh2])
        db.commit()
        ids = {"product": product.id, "wh1": wh1.id, "wh2": wh2.id}
    yield ids


def _create_in(client, h, m, qty="10", price="12", status_submit=False):
    payload = {"doc_date": "2026-11-01", "in_type": "其他入库",
               "warehouse_id": m["wh1"], "subject_code": "ZC",
               "items": [{"product_id": m["product"], "qty": qty, "unit_price": price}]}
    doc = client.post(IN, headers=h, json=payload).json()
    if status_submit:
        client.post(f"{IN}/{doc['id']}/submit", headers=h)
    return doc


def _approve(client, h, base, doc_id):
    """草稿 → 提交 → 审核（与页面流程一致）。"""
    sub = client.post(f"{base}/{doc_id}/submit", headers=h)
    assert sub.status_code in (200, 422), sub.text   # 422 = 已是待审核
    return client.post(f"{base}/{doc_id}/approve", headers=h)


class TestManualPrice:
    def test_入库单价手填生效(self, client, h, masters):
        doc = _create_in(client, h, masters, qty="10", price="12")
        assert float(doc["total_amount"]) == 120.0
        assert _approve(client, h, IN, doc["id"]).status_code == 200

        with SessionLocal() as db:
            led = db.execute(select(StockLedger).where(
                StockLedger.doc_id == doc["id"],
                StockLedger.doc_type == "stock_in")).scalars().first()
            assert led is not None and Decimal(led.unit_price) == Decimal("12")
            value = stock_value_map(db, {(masters["wh1"], masters["product"])})
        assert value[(masters["wh1"], masters["product"])] == Decimal("120")

    def test_出库单价手填影响出库流水与退库金额(self, client, h, masters):
        _approve(client, h, IN, _create_in(client, h, masters, qty="10", price="12")["id"])

        out = client.post(OUT, headers=h, json={
            "doc_date": "2026-11-02", "out_type": "其他出库", "warehouse_id": masters["wh1"],
            "subject_code": "ZC",
            "items": [{"product_id": masters["product"], "qty": 4, "unit_price": 20}]}).json()
        assert float(out["total_amount"]) == 80.0
        assert _approve(client, h, OUT, out["id"]).status_code == 200

        with SessionLocal() as db:
            led = db.execute(select(StockLedger).where(
                StockLedger.doc_id == out["id"],
                StockLedger.doc_type == "stock_out")).scalars().first()
            assert Decimal(led.unit_price) == Decimal("20")
            # 剩余批次金额仍按入库价：6 × 12 = 72（出库价不改变成本）
            value = stock_value_map(db, {(masters["wh1"], masters["product"])})
        assert value[(masters["wh1"], masters["product"])] == Decimal("72")

        preview = client.get(f"{OUT}/{out['id']}/return-preview", headers=h).json()
        assert preview["rows"][0]["unit_price"] == 20.0   # 退库单价 = 出库行单价

        # CR-032：库存明细直接读结存金额列，也必须是 72（与批次回放一致）
        row = next(r for r in client.get("/api/stock/balances", headers=h,
                                         params={"product_id": masters["product"]}).json()["items"]
                   if r["warehouse_id"] == masters["wh1"])
        assert row["stock_amount"] == 72.0

    def test_调拨单价两端同价并进入调入仓金额(self, client, h, masters):
        _approve(client, h, IN, _create_in(client, h, masters, qty="10", price="5")["id"])

        tr = client.post(TRANSFER, headers=h, json={
            "doc_date": "2026-11-03",
            "from_warehouse_id": masters["wh1"], "to_warehouse_id": masters["wh2"],
            "items": [{"product_id": masters["product"], "qty": 6, "unit_price": 5}]}).json()
        assert _approve(client, h, TRANSFER, tr["id"]).status_code == 200

        with SessionLocal() as db:
            legs = db.execute(select(StockLedger).where(
                StockLedger.doc_id == tr["id"],
                StockLedger.doc_type == "stock_transfer")).scalars().all()
            prices = {Decimal(x.unit_price) for x in legs}
            value = stock_value_map(db, {(masters["wh1"], masters["product"]),
                                         (masters["wh2"], masters["product"])})
        assert len(legs) == 2 and prices == {Decimal("5")}, "调拨两端必须同价"
        # 调出仓剩 4×5=20，调入仓 6×5=30 → 合计守恒 50
        assert value[(masters["wh1"], masters["product"])] == Decimal("20")
        assert value[(masters["wh2"], masters["product"])] == Decimal("30")
        assert sum(value.values()) == Decimal("50")

    def test_调拨手填不同于成本价时按手填计(self, client, h, masters):
        _approve(client, h, IN, _create_in(client, h, masters, qty="10", price="5")["id"])
        tr = client.post(TRANSFER, headers=h, json={
            "doc_date": "2026-11-03",
            "from_warehouse_id": masters["wh1"], "to_warehouse_id": masters["wh2"],
            "items": [{"product_id": masters["product"], "qty": 6, "unit_price": 7}]}).json()
        _approve(client, h, TRANSFER, tr["id"])
        with SessionLocal() as db:
            value = stock_value_map(db, {(masters["wh2"], masters["product"])})
        assert value[(masters["wh2"], masters["product"])] == Decimal("42")   # 6 × 7

    def test_已审核单据不可改价(self, client, h, masters):
        doc = _create_in(client, h, masters, qty="2", price="9")
        assert _approve(client, h, IN, doc["id"]).status_code == 200
        resp = client.put(f"{IN}/{doc['id']}", headers=h, json={
            "doc_date": "2026-11-01", "in_type": "其他入库",
            "warehouse_id": masters["wh1"], "subject_code": "ZC",
            "items": [{"product_id": masters["product"], "qty": 2, "unit_price": 99}]})
        assert 400 <= resp.status_code < 500, resp.text
