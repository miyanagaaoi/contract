"""CR-040 回归：盘点复盘（审核后留痕，不改库存）。"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_doc import StockTake, StockTakeItem
from app.models_master import Product, ProductType, Uom, Warehouse


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


def _make_take(status: str = "approved") -> int:
    with SessionLocal() as db:
        sfx = uuid.uuid4().hex[:6]
        uom = Uom(code=f"U{sfx}", name=f"个{sfx}", decimals=0)
        db.add(uom)
        db.flush()
        pt = ProductType(name=f"类型{sfx}")
        db.add(pt)
        db.flush()
        product = Product(code=f"P{sfx}", name=f"物料{sfx}", product_type_id=pt.id, uom_id=uom.id)
        wh = Warehouse(code=f"W{sfx}", name=f"仓{sfx}")
        db.add_all([product, wh])
        db.flush()
        take = StockTake(doc_no=f"ST{sfx}", doc_date=date(2026, 11, 1), status=status,
                         warehouse_id=wh.id, warehouse_name=wh.name, take_type="partial",
                         posted=(status == "approved"))
        db.add(take)
        db.flush()
        take.items.append(StockTakeItem(
            seq=1, product_id=product.id, product_code=product.code,
            product_name=product.name, uom_name="个", uom_decimals=0,
            qty=Decimal("0"), unit_price=Decimal("0"), amount=Decimal("0"),
            book_qty=Decimal("10"), actual_qty=Decimal("8"), diff_qty=Decimal("-2"),
            warehouse_id=wh.id))
        db.commit()
        return take.id


def test_review_after_approved(client, h):
    take_id = _make_take("approved")
    r = client.post(f"/api/stock/takes/{take_id}/review", headers=h,
                    json={"note": "盘亏 2 件，已核实为损耗"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["review_status"] == "reviewed"
    assert data["review_note"].startswith("盘亏")
    assert data["reviewed_name"]

    # 重复复盘 → 422
    again = client.post(f"/api/stock/takes/{take_id}/review", headers=h, json={"note": "再来一次"})
    assert again.status_code == 422


def test_review_requires_note_and_approved(client, h):
    take_id = _make_take("submitted")
    r = client.post(f"/api/stock/takes/{take_id}/review", headers=h, json={"note": "x"})
    assert r.status_code == 422
    assert "已审核" in r.json()["detail"]

    approved = _make_take("approved")
    r2 = client.post(f"/api/stock/takes/{approved}/review", headers=h, json={"note": "   "})
    assert r2.status_code == 422
    assert "复盘说明必填" in r2.json()["detail"]
