"""CR-044 回归：询价报价（部门内部版）。

覆盖：建单→发布→录入两家报价→比价（最低/次低/差额/差额率/合计）→截止；
草稿不可录报价；导出 xlsx。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_master import Supplier

RFQ = "/api/rfq"


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


@pytest.fixture(scope="module")
def suppliers():
    with SessionLocal() as db:
        out = []
        for tag in ("A", "B"):
            sfx = uuid.uuid4().hex[:6]
            sup = Supplier(code=f"S{tag}{sfx}", name=f"报价供应商{tag}{sfx}")
            db.add(sup)
            db.commit()
            out.append({"id": sup.id, "name": sup.name})
        return out


def _create(client, h) -> dict:
    r = client.post(RFQ, headers=h, json={
        "title": "钢材询价（测试）", "project": "测试项目",
        "deadline": "2026-11-30T18:00", "remark": "内部询价",
        "lines": [
            {"material_name": "螺纹钢", "spec": "HRB400 Φ12", "unit": "吨",
             "qty": 10, "need_date": "2026-11-20"},
            {"material_name": "圆钢", "spec": "Q235 Φ20", "unit": "吨", "qty": 5},
        ]})
    assert r.status_code == 200, r.text
    return r.json()


def test_rfq_flow_and_compare(client, h, suppliers):
    doc = _create(client, h)
    assert doc["doc_no"].startswith("RFQ")
    assert len(doc["lines"]) == 2
    line1, line2 = doc["lines"]
    rfq_id = doc["id"]

    # 草稿不可录报价
    bad = client.put(f"{RFQ}/{rfq_id}/quotes/{suppliers[0]['id']}", headers=h,
                     json={"items": [{"line_id": line1["id"], "unit_price": 1}]})
    assert bad.status_code == 422

    assert client.post(f"{RFQ}/{rfq_id}/publish", headers=h).status_code == 200

    for sup, p1, p2 in ((suppliers[0], 4200, 4500), (suppliers[1], 4100, 4800)):
        r = client.put(f"{RFQ}/{rfq_id}/quotes/{sup['id']}", headers=h, json={
            "quote_date": "2026-11-08", "contact_name": "张三", "contact_phone": "13800000000",
            "channel": "微信", "remark": "含运费",
            "items": [
                {"line_id": line1["id"], "unit_price": p1, "tax_rate": 13, "lead_days": 7},
                {"line_id": line2["id"], "unit_price": p2, "tax_rate": 13, "lead_days": 5},
            ]})
        assert r.status_code == 200, r.text

    cmp = client.get(f"{RFQ}/{rfq_id}/compare", headers=h).json()
    assert len(cmp["rows"]) == 2
    row1 = cmp["rows"][0]
    assert row1["lowest"]["supplier_id"] == suppliers[1]["id"]
    assert row1["lowest"]["unit_price"] == 4100
    assert row1["second"]["unit_price"] == 4200
    assert row1["diff"] == pytest.approx(100)
    assert row1["diff_pct"] == pytest.approx(100 / 4100 * 100)
    assert len(cmp["supplier_totals"]) == 2

    x = client.get(f"{RFQ}/export.xlsx", headers=h)
    assert x.status_code == 200 and len(x.content) > 1000

    assert client.post(f"{RFQ}/{rfq_id}/close", headers=h).status_code == 200
    assert client.put(f"{RFQ}/{rfq_id}", headers=h,
                      json={"title": "x", "lines": []}).status_code == 422


def test_rfq_validation(client, h):
    r = client.post(RFQ, headers=h, json={"title": "", "lines": []})
    assert r.status_code == 422
    r2 = client.post(RFQ, headers=h, json={"title": "空行", "lines": []})
    assert r2.status_code == 200
    doc = r2.json()
    assert client.post(f"{RFQ}/{doc['id']}/publish", headers=h).status_code == 422
    assert client.delete(f"{RFQ}/{doc['id']}", headers=h).status_code == 200
