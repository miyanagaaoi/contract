"""CR-034 回归：采购退货单 / 销售退货单。

覆盖：
1. 采购退货：出库过账（减库存）+ 回冲采购单 received_qty；反审核恢复；
2. 销售退货：入库过账（加库存）+ 回冲销售订单 shipped_qty；
3. 编号前缀 PRT / SRT；红冲流水业务类型正确。
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
from app.models_doc import (PurchaseOrder, PurchaseOrderItem, PurchaseReturnOrder,
                            SalesOrder, SalesOrderItem, SalesReturnOrder)
from app.models_master import Customer, Product, ProductType, Supplier, Uom, Warehouse
from app.models_stock import Stock, StockLedger

PR = "/api/stock/purchase-returns"
SR = "/api/stock/sales-returns"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def h(client):
    r = client.post("/api/auth/login",
                    json={"username": ADMIN_USERNAME, "password": ADMIN_INIT_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _masters(with_qty: str = "10") -> dict:
    with SessionLocal() as db:
        sfx = uuid.uuid4().hex[:6]
        uom = Uom(code=f"U{sfx}", name=f"个{sfx}", decimals=0)
        db.add(uom)
        db.flush()
        pt = ProductType(name=f"类型{sfx}")
        db.add(pt)
        db.flush()
        p = Product(code=f"P{sfx}", name=f"物料{sfx}", product_type_id=pt.id, uom_id=uom.id)
        wh = Warehouse(code=f"W{sfx}", name=f"仓{sfx}")
        sup = Supplier(code=f"S{sfx}", name=f"供{sfx}")
        cus = Customer(code=f"C{sfx}", name=f"客{sfx}")
        db.add_all([p, wh, sup, cus])
        db.flush()
        db.add(Stock(product_id=p.id, warehouse_id=wh.id, qty=Decimal(with_qty),
                     stock_value=Decimal(with_qty) * Decimal("5")))
        db.add(StockLedger(product_id=p.id, warehouse_id=wh.id, biz_type="采购入库",
                           doc_type="stock_in", doc_id=1, doc_no=f"SEED{sfx}",
                           qty_change=Decimal(with_qty), qty_after=Decimal(with_qty),
                           unit_price=Decimal("5")))
        # 来源采购单（含已收 10）
        po = PurchaseOrder(doc_no=f"PO{sfx}", doc_date=None, status="approved",
                           supplier_id=sup.id, supplier_name=sup.name)
        db.add(po)
        db.flush()
        poi = PurchaseOrderItem(seq=1, product_id=p.id, product_code=p.code,
                                product_name=p.name, uom_name="个", uom_decimals=0,
                                qty=Decimal("10"), unit_price=Decimal("5"),
                                amount=Decimal("50"), received_qty=Decimal("10"))
        po.items.append(poi)
        # 来源销售订单（含已发 10）
        so = SalesOrder(doc_no=f"SO{sfx}", doc_date=None, status="approved",
                        customer_id=cus.id, customer_name=cus.name)
        db.add(so)
        db.flush()
        soi = SalesOrderItem(seq=1, product_id=p.id, product_code=p.code,
                             product_name=p.name, uom_name="个", uom_decimals=0,
                             qty=Decimal("10"), unit_price=Decimal("8"),
                             amount=Decimal("80"), shipped_qty=Decimal("10"))
        so.items.append(soi)
        db.commit()
        return {"product": p.id, "wh": wh.id, "sup": sup.id, "cus": cus.id,
                "po": po.id, "poi": poi.id, "so": so.id, "soi": soi.id}


def _create_approve(client, h, base, payload):
    doc = client.post(base, headers=h, json=payload).json()
    client.post(f"{base}/{doc['id']}/submit", headers=h)
    r = client.post(f"{base}/{doc['id']}/approve", headers=h)
    assert r.status_code == 200, r.text
    return doc


def test_purchase_return_post_out_and_rollback_received(client, h):
    m = _masters()
    doc = _create_approve(client, h, PR, {
        "doc_date": "2026-11-01", "warehouse_id": m["wh"], "supplier_id": m["sup"],
        "subject_code": "ZC", "source_doc_type": "purchase_order",
        "source_doc_id": m["po"], "source_doc_no": "PO-TEST",
        "items": [{"product_id": m["product"], "qty": 4, "unit_price": 5,
                   "src_item_id": m["poi"]}]})
    assert doc["doc_no"].startswith("PRT")

    with SessionLocal() as db:
        st = db.execute(select(Stock).where(Stock.product_id == m["product"],
                                            Stock.warehouse_id == m["wh"])).scalar_one()
        assert Decimal(st.qty) == Decimal("6")
        assert Decimal(st.stock_value) == Decimal("30")
        line = db.get(PurchaseOrderItem, m["poi"])
        assert Decimal(line.received_qty) == Decimal("6")
        led = db.execute(select(StockLedger).where(
            StockLedger.doc_type == "purchase_return",
            StockLedger.doc_id == doc["id"])).scalars().first()
        assert led is not None and led.qty_change == Decimal("-4")
        assert led.biz_type == "采购退货"

    # 反审核：库存与已收数量恢复
    client.post(f"{PR}/{doc['id']}/unapprove", headers=h, json={"reason": "测试"})
    with SessionLocal() as db:
        st = db.execute(select(Stock).where(Stock.product_id == m["product"],
                                            Stock.warehouse_id == m["wh"])).scalar_one()
        assert Decimal(st.qty) == Decimal("10")
        assert Decimal(db.get(PurchaseOrderItem, m["poi"]).received_qty) == Decimal("10")


def test_sales_return_post_in_and_rollback_shipped(client, h):
    m = _masters()
    doc = _create_approve(client, h, SR, {
        "doc_date": "2026-11-01", "warehouse_id": m["wh"], "customer_id": m["cus"],
        "subject_code": "ZC", "source_doc_type": "sales_order",
        "source_doc_id": m["so"], "source_doc_no": "SO-TEST",
        "items": [{"product_id": m["product"], "qty": 3, "unit_price": 8,
                   "src_item_id": m["soi"]}]})
    assert doc["doc_no"].startswith("SRT")

    with SessionLocal() as db:
        st = db.execute(select(Stock).where(Stock.product_id == m["product"],
                                            Stock.warehouse_id == m["wh"])).scalar_one()
        assert Decimal(st.qty) == Decimal("13")
        assert Decimal(db.get(SalesOrderItem, m["soi"]).shipped_qty) == Decimal("7")
        led = db.execute(select(StockLedger).where(
            StockLedger.doc_type == "sales_return",
            StockLedger.doc_id == doc["id"])).scalars().first()
        assert led is not None and led.qty_change == Decimal("3")
        assert led.biz_type == "销售退货"


# ==================== CR-037：成本口径（移动加权平均） ====================

def test_moving_avg_cost_method(client, h):
    """切换为移动加权：入库按单据价、出库按当前均价结转。"""
    from app import dicts as app_dicts

    m = _masters(with_qty="0")
    with SessionLocal() as db:
        params = app_dicts.get_sys_params(db)
        params["cost_method"] = "moving_avg"
        app_dicts.set_sys_params(db, {"cost_method": "moving_avg"})
        db.commit()
    try:
        def do_in(qty: str, price: str):
            doc = client.post("/api/stock/in-orders", headers=h, json={
                "doc_date": "2026-11-01", "in_type": "其他入库",
                "warehouse_id": m["wh"], "subject_code": "ZC",
                "items": [{"product_id": m["product"], "qty": qty, "unit_price": price}]}).json()
            client.post(f"/api/stock/in-orders/{doc['id']}/submit", headers=h)
            assert client.post(f"/api/stock/in-orders/{doc['id']}/approve",
                               headers=h).status_code == 200
            return doc

        do_in(10, 10)          # 库存 10，金额 100
        do_in(10, 20)          # 库存 20，金额 300（均价 15）
        out = client.post("/api/stock/out-orders", headers=h, json={
            "doc_date": "2026-11-02", "out_type": "其他出库",
            "warehouse_id": m["wh"], "subject_code": "ZC",
            "items": [{"product_id": m["product"], "qty": 5, "unit_price": 15}]}).json()
        client.post(f"/api/stock/out-orders/{out['id']}/submit", headers=h)
        assert client.post(f"/api/stock/out-orders/{out['id']}/approve",
                           headers=h).status_code == 200

        with SessionLocal() as db:
            st = db.execute(select(Stock).where(Stock.product_id == m["product"],
                                                Stock.warehouse_id == m["wh"])).scalar_one()
            assert Decimal(st.qty) == Decimal("15")
            assert Decimal(st.stock_value) == Decimal("225")   # 300 - 5×15
    finally:
        with SessionLocal() as db:
            app_dicts.set_sys_params(db, {"cost_method": "fifo"})
            db.commit()


def test_cost_method_param_meta_exposed(client, h):
    data = client.get("/api/system/params", headers=h).json()
    meta = {m["key"]: m for m in data["meta"]}
    assert meta["cost_method"]["type"] == "select"
    assert data["params"]["cost_method"] in ("fifo", "moving_avg")
