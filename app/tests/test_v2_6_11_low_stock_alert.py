"""CR-039 回归：库存低于安全库存的预警通知（飞书 outbox）。

- 出库后结存 < 安全库存 → 为有 `stock.balance.view` 权限且绑定飞书的账号入队一条 stock 通知；
- 同一物料/仓库/日期只提醒一次（event_key 幂等）；
- 反审核（红冲）不产生预警。
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
from app.models_notify import Notification
from app.models_stock import Stock, StockLedger


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


def _masters() -> dict:
    with SessionLocal() as db:
        sfx = uuid.uuid4().hex[:6]
        uom = Uom(code=f"U{sfx}", name=f"个{sfx}", decimals=0)
        db.add(uom)
        db.flush()
        pt = ProductType(name=f"类型{sfx}")
        db.add(pt)
        db.flush()
        product = Product(code=f"P{sfx}", name=f"物料{sfx}", product_type_id=pt.id,
                          uom_id=uom.id, safety_stock=Decimal("10"))
        wh = Warehouse(code=f"W{sfx}", name=f"仓{sfx}")
        db.add_all([product, wh])
        db.flush()
        db.add(Stock(product_id=product.id, warehouse_id=wh.id, qty=Decimal("12"),
                     stock_value=Decimal("120")))
        db.add(StockLedger(product_id=product.id, warehouse_id=wh.id, biz_type="采购入库",
                           doc_type="stock_in", doc_id=1, doc_no=f"SEED{sfx}",
                           qty_change=Decimal("12"), qty_after=Decimal("12"),
                           unit_price=Decimal("10")))
        db.commit()
        return {"product": product.id, "wh": wh.id, "code": product.code}


def _mk_out(client, h, m, qty: str) -> dict:
    return client.post("/api/stock/out-orders", headers=h, json={
        "doc_date": "2026-11-01", "out_type": "其他出库", "warehouse_id": m["wh"],
        "subject_code": "ZC",
        "items": [{"product_id": m["product"], "qty": qty, "unit_price": 10}]}).json()


def test_low_stock_alert_enqueued_and_deduped(client, h, monkeypatch):
    from app import config
    from app.services.feishu import identity_service

    monkeypatch.setattr(config, "feishu_ready", lambda: True)
    monkeypatch.setattr(identity_service, "bound_open_id", lambda db, uid: "ou_test")
    m = _masters()

    out = _mk_out(client, h, m, "5")          # 12 → 7 < 10
    client.post(f"/api/stock/out-orders/{out['id']}/submit", headers=h)
    assert client.post(f"/api/stock/out-orders/{out['id']}/approve",
                       headers=h).status_code == 200

    with SessionLocal() as db:
        rows = db.execute(select(Notification).where(
            Notification.category == "stock",
            Notification.event_key.like(f"stock:low:{m['product']}:%"))).scalars().all()
    assert rows, "应生成库存预警通知"
    assert all(r.status == "pending" for r in rows)
    first_count = len(rows)

    # 再出库一次（仍低于安全库存）→ 同日不重复提醒
    out2 = _mk_out(client, h, m, "1")
    client.post(f"/api/stock/out-orders/{out2['id']}/submit", headers=h)
    client.post(f"/api/stock/out-orders/{out2['id']}/approve", headers=h)
    with SessionLocal() as db:
        again = db.execute(select(Notification).where(
            Notification.category == "stock",
            Notification.event_key.like(f"stock:low:{m['product']}:%"))).scalars().all()
    assert len(again) == first_count, "同一物料/仓库/日期应幂等，只提醒一次"


def test_reverse_does_not_alert(client, h, monkeypatch):
    from app import config
    from app.services.feishu import identity_service

    monkeypatch.setattr(config, "feishu_ready", lambda: True)
    monkeypatch.setattr(identity_service, "bound_open_id", lambda db, uid: "ou_test")
    m = _masters()
    out = _mk_out(client, h, m, "5")
    client.post(f"/api/stock/out-orders/{out['id']}/submit", headers=h)
    client.post(f"/api/stock/out-orders/{out['id']}/approve", headers=h)
    with SessionLocal() as db:
        before = len(db.execute(select(Notification).where(
            Notification.category == "stock",
            Notification.event_key.like(f"stock:low:{m['product']}:%"))).scalars().all())
    client.post(f"/api/stock/out-orders/{out['id']}/unapprove", headers=h,
                json={"reason": "test"})
    with SessionLocal() as db:
        after = len(db.execute(select(Notification).where(
            Notification.category == "stock",
            Notification.event_key.like(f"stock:low:{m['product']}:%"))).scalars().all())
    assert after == before, "反审核（红冲）不应新增库存预警"
