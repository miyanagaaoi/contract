"""CR-033 回归：运维与质量改进（健康检查增强 / 导出超限保护）。

- `/api/health` 在原有字段外提供 db_latency_ms / disk_free_mb / uptime_seconds / counts；
- 结存导出、批次报表导出超过上限时返回 **413 并给出缩小范围的提示**（不再静默截断）。
"""
from __future__ import annotations

from decimal import Decimal
import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_master import Product, ProductType, Uom, Warehouse
from app.models_stock import Stock


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


def test_health_has_ops_fields(client):
    data = client.get("/api/health").json()
    assert data["status"] == "ok" and data["db"] is True
    for key in ("db_latency_ms", "disk_free_mb", "uptime_seconds", "counts", "version"):
        assert key in data, f"健康检查缺少 {key}"
    assert isinstance(data["db_latency_ms"], (int, float))
    assert data["uptime_seconds"] >= 0


def _mk_stock_rows(n: int = 2) -> list[int]:
    """建 n 条结存（带入库流水），返回 product_ids。"""
    from app.models_stock import StockLedger

    ids = []
    with SessionLocal() as db:
        sfx = uuid.uuid4().hex[:6]
        uom = Uom(code=f"U{sfx}", name=f"个{sfx}", decimals=0)
        db.add(uom)
        db.flush()
        pt = ProductType(name=f"类型{sfx}")
        db.add(pt)
        db.flush()
        wh = Warehouse(code=f"W{sfx}", name=f"仓{sfx}")
        db.add(wh)
        db.flush()
        for i in range(n):
            p = Product(code=f"P{sfx}{i}", name=f"物料{sfx}{i}",
                        product_type_id=pt.id, uom_id=uom.id)
            db.add(p)
            db.flush()
            db.add(Stock(product_id=p.id, warehouse_id=wh.id, qty=Decimal("5"),
                         stock_value=Decimal("25")))
            db.add(StockLedger(product_id=p.id, warehouse_id=wh.id, biz_type="采购入库",
                               doc_type="stock_in", doc_id=1, doc_no=f"T{sfx}{i}",
                               qty_change=Decimal("5"), qty_after=Decimal("5"),
                               unit_price=Decimal("5")))
            ids.append(p.id)
        db.commit()
    return ids


def test_balances_export_over_limit_returns_413(client, h, monkeypatch):
    import app.routers.export as export_mod

    monkeypatch.setattr(export_mod, "DOC_EXPORT_LIMIT", 1)
    _mk_stock_rows(2)
    r = client.get("/api/stock/balances/export.xlsx", headers=h, params={"qty_min": 1})
    assert r.status_code == 413, r.text
    assert "缩小筛选范围" in r.json()["detail"]


def test_batch_report_export_over_limit_returns_413(client, h, monkeypatch):
    import app.routers.export as export_mod

    monkeypatch.setattr(export_mod, "DOC_EXPORT_LIMIT", 1)
    r = client.get("/api/stock/batch-report.xlsx", headers=h)
    assert r.status_code == 413, r.text
    assert "超过单次导出上限" in r.json()["detail"]
