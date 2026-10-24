"""CR-022 回归：出库单「更多 → 退库」（生成退库入库单，支持部分退、防超退）。

覆盖：
1. 预览返回 已出/已退/可退；
2. 部分退 → 生成草稿入库单（in_type=退库入库、来源指向出库单、行项 src_item_id 关联）；
3. 重复退库累计已退（草稿也计入，防超退）；超量 → 422；
4. 未审核出库单不可退库 → 422。
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_doc import StockOutOrder, StockOutOrderItem
from app.tools import seed_stock_demo10 as demo10


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


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    demo10.purge_all()
    demo10.seed_ten(abnormal=False)
    yield
    demo10.purge_all()


def _out_id(doc_no: str) -> int:
    with SessionLocal() as db:
        return int(db.execute(select(StockOutOrder.id).where(
            StockOutOrder.doc_no == doc_no)).scalar_one())


def _item_id(out_id: int) -> int:
    with SessionLocal() as db:
        return int(db.execute(select(StockOutOrderItem.id).where(
            StockOutOrderItem.doc_id == out_id)).scalar_one())


def test_preview_and_partial_return(client, h):
    out_id = _out_id(f"{demo10.PREFIX}-OUT-1")
    item_id = _item_id(out_id)

    prev = client.get(f"/api/stock/out-orders/{out_id}/return-preview", headers=h)
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert body["doc_no"].endswith("OUT-1")
    row = body["rows"][0]
    assert row["qty"] == 130.0 and row["returned_qty"] == 0.0 and row["returnable_qty"] == 130.0

    # 部分退 10
    resp = client.post(f"/api/stock/out-orders/{out_id}/return",
                       json={"rows": [{"item_id": item_id, "qty": 10}]}, headers=h)
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["doc_no"].startswith("IN")
    assert created["in_type"] == "退库入库"
    assert created["source_doc_no"].endswith("OUT-1")
    assert created["status"] == "draft"
    assert created["items"][0]["qty"] == 10.0
    assert created["items"][0]["src_item_id"] == item_id

    # 预览：已退 10、可退 120（草稿计入）
    prev2 = client.get(f"/api/stock/out-orders/{out_id}/return-preview", headers=h).json()
    assert prev2["rows"][0]["returned_qty"] == 10.0
    assert prev2["rows"][0]["returnable_qty"] == 120.0

    # 超退 → 422
    over = client.post(f"/api/stock/out-orders/{out_id}/return",
                       json={"rows": [{"item_id": item_id, "qty": 121}]}, headers=h)
    assert over.status_code == 422
    assert "超过可退数量" in over.json()["detail"]

    # 未审核出库单 → 422
    with SessionLocal() as db:
        draft = StockOutOrder(doc_no="OUT-DRAFT-TEST", doc_date=None, status="draft",
                              warehouse_id=1, warehouse_name="X", out_type="其他出库")
        db.add(draft)
        db.commit()
        draft_id = draft.id
    bad = client.post(f"/api/stock/out-orders/{draft_id}/return",
                      json={"rows": [{"item_id": 1, "qty": 1}]}, headers=h)
    assert bad.status_code == 422
    assert "已审核" in bad.json()["detail"]


def test_approved_return_posts_to_stock(client, h):
    """退库入库单审核后：结存增加、流水出现「退库入库」。"""
    from app.models_stock import Stock, StockLedger
    from sqlalchemy import func

    out_id = _out_id(f"{demo10.PREFIX}-OUT-2")
    item_id = _item_id(out_id)
    resp = client.post(f"/api/stock/out-orders/{out_id}/return",
                       json={"rows": [{"item_id": item_id, "qty": 20}]}, headers=h)
    assert resp.status_code == 200, resp.text
    new_doc = resp.json()

    with SessionLocal() as db:
        before = float(db.execute(select(func.coalesce(func.sum(Stock.qty), 0))).scalar())
    assert client.post(f"/api/stock/in-orders/{new_doc['id']}/submit", headers=h).status_code == 200
    assert client.post(f"/api/stock/in-orders/{new_doc['id']}/approve", headers=h).status_code == 200
    with SessionLocal() as db:
        after = float(db.execute(select(func.coalesce(func.sum(Stock.qty), 0))).scalar())
        led = db.execute(select(StockLedger).where(
            StockLedger.doc_no == new_doc["doc_no"], StockLedger.qty_change > 0)).scalars().first()
    assert after == before + 20
    assert led is not None and led.biz_type == "退库入库"
