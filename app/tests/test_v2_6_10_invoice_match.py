"""CR-038 回归：发票自动匹配核销（进项 → 采购单）。

规则：供应商名称一致 + 价税合计与未开票金额一致/接近 → 唯一高分自动绑定；
多候选或分数不足 → 只返回候选，不擅自绑定。
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_doc import INVOICE_IN, Invoice, PurchaseOrder, PurchaseOrderItem
from app.models_master import Product, ProductType, Supplier, Uom


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


def _setup_invoice(total: str = "100", supplier_name: str | None = None) -> tuple[int, int]:
    """建一张已审核采购单（总额 100）+ 一张草稿进项发票（同供应商同金额）。"""
    with SessionLocal() as db:
        sfx = uuid.uuid4().hex[:6]
        supplier_name = supplier_name or f"匹配供应商{sfx}"
        uom = Uom(code=f"U{sfx}", name=f"个{sfx}", decimals=0)
        db.add(uom)
        db.flush()
        pt = ProductType(name=f"类型{sfx}")
        db.add(pt)
        db.flush()
        product = Product(code=f"P{sfx}", name=f"物料{sfx}", product_type_id=pt.id, uom_id=uom.id)
        sup = Supplier(code=f"S{sfx}", name=supplier_name)
        db.add_all([product, sup])
        db.flush()
        po = PurchaseOrder(doc_no=f"PO{sfx}", doc_date=date(2026, 11, 1), status="approved",
                           supplier_id=sup.id, supplier_name=sup.name,
                           total_amount=Decimal(total))
        db.add(po)
        db.flush()
        po.items.append(PurchaseOrderItem(
            seq=1, product_id=product.id, product_code=product.code,
            product_name=product.name, uom_name="个", uom_decimals=0,
            qty=Decimal("1"), unit_price=Decimal(total), amount=Decimal(total)))
        inv = Invoice(doc_no=f"INV{sfx}", doc_date=date(2026, 11, 1), status="draft",
                      invoice_direction=INVOICE_IN, invoice_no=f"2614200000{uuid.uuid4().int % 10**10:010d}",
                      invoice_date=date(2026, 11, 1), total_amount=Decimal(total),
                      amount=Decimal(total), tax_amount=Decimal("0"),
                      auth_status="authenticated", bind_status="unbound",
                      seller_name=supplier_name)
        db.add(inv)
        db.commit()
        return po.id, inv.id


def test_suggest_and_auto_match(client, h):
    po_id, inv_id = _setup_invoice()
    cands = client.get(f"/api/finance/invoices/{inv_id}/match-candidates", headers=h).json()
    assert cands["candidates"], cands
    top = cands["candidates"][0]
    assert top["target_id"] == po_id and top["score"] >= 80

    res = client.post(f"/api/finance/invoices/{inv_id}/auto-match", headers=h).json()
    assert res["matched"] is True, res
    assert res["candidate"]["target_id"] == po_id

    with SessionLocal() as db:
        inv = db.get(Invoice, inv_id)
        po = db.get(PurchaseOrder, po_id)
        assert inv.bind_status == "bound" and inv.status == "confirmed"
        assert Decimal(po.invoiced_amount or 0) == Decimal("100")


def test_low_score_returns_candidates_only(client, h):
    """金额差 50% → 分不足 80，只给候选不绑定。"""
    po_id, inv_id = _setup_invoice(total="100")
    # 采购单 100、发票只有 50 → 金额差 50%，匹配度不足 → 不自动绑定
    with SessionLocal() as db:
        inv = db.get(Invoice, inv_id)
        inv.total_amount = Decimal("50")
        db.commit()
    res = client.post(f"/api/finance/invoices/{inv_id}/auto-match", headers=h).json()
    assert res["matched"] is False
    with SessionLocal() as db:
        assert db.get(Invoice, inv_id).bind_status == "unbound"
