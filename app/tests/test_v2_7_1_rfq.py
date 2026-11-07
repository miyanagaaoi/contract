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


def test_award_with_scores(client, h, suppliers):
    """CR-058：报价评分/综合得分 + 我方定标确认 + 比价单所需字段。"""
    doc = _create(client, h)
    rfq_id, line = doc["id"], doc["lines"][0]["id"]
    assert client.post(f"{RFQ}/{rfq_id}/publish", headers=h).status_code == 200
    for sup, price, ps, qs, ss in ((suppliers[0], 5700, 9, 10, 10),
                                   (suppliers[1], 4750, 10, 9, 9)):
        r = client.put(f"{RFQ}/{rfq_id}/quotes/{sup['id']}", headers=h, json={
            "delivery_period": "7-14", "payment_terms": "一次性支付",
            "after_sales": "优秀",
            "price_score": ps, "quality_score": qs, "service_score": ss,
            "items": [{"line_id": line, "unit_price": price, "tax_rate": 13}]})
        assert r.status_code == 200, r.text
    # 评分在报价行上（当前接口按行存）→ 通过 compare 检查字段存在
    cmp = client.get(f"{RFQ}/{rfq_id}/compare", headers=h).json()
    assert cmp["rows"][0]["offers"], cmp
    avgs = {o["supplier_name"]: o["score_avg"] for o in cmp["rows"][0]["offers"]}
    assert avgs[suppliers[0]["name"]] == round((9 + 10 + 10) / 3, 2)
    assert avgs[suppliers[1]["name"]] == round((10 + 9 + 9) / 3, 2)

    # 未发布供应商（不存在）不能定标
    bad = client.post(f"{RFQ}/{rfq_id}/award", headers=h, json={"supplier_id": 999999})
    assert bad.status_code == 422

    ok = client.post(f"{RFQ}/{rfq_id}/award", headers=h, json={
        "supplier_id": suppliers[0]["id"],
        "reason": "价格在第二序列，但产品质量放心",
        "conclusion": "因进度要求较高，选择天罡作为本次供货商"})
    assert ok.status_code == 200, ok.text
    head = ok.json()
    assert head["award_supplier_name"] == suppliers[0]["name"]
    assert head["award_reason"] and head["award_conclusion"]
    detail = client.get(f"{RFQ}/{rfq_id}", headers=h).json()
    assert detail["award_supplier_id"] == suppliers[0]["id"]
    # 取消定标
    clear = client.post(f"{RFQ}/{rfq_id}/award", headers=h, json={"supplier_id": None})
    assert clear.status_code == 200 and clear.json()["award_supplier_id"] is None


def test_print_template_config(client, h):
    """比价单打印模板：默认纵向一页；可改标题/区块/自定义行；非法值 422。"""
    g = client.get(f"{RFQ}/print-template", headers=h)
    assert g.status_code == 200, g.text
    assert g.json()["orientation"] == "portrait"

    r = client.put(f"{RFQ}/print-template", headers=h, json={
        "title": "比价单（长城博物馆）", "orientation": "portrait",
        "sections": {"budget": False, "conditions": True, "scores": True,
                     "reason": True, "conclusion": True},
        "extra_rows": [{"label": "备注", "value": "此报价含税含运费"}],
        "footer_note": "内部资料"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["title"] == "比价单（长城博物馆）"
    assert data["sections"]["budget"] is False
    assert data["extra_rows"][0]["value"] == "此报价含税含运费"
    assert client.get(f"{RFQ}/print-template", headers=h).json()["footer_note"] == "内部资料"

    bad = client.put(f"{RFQ}/print-template", headers=h, json={"orientation": "diagonal"})
    assert bad.status_code == 422
    too_many = client.put(f"{RFQ}/print-template", headers=h,
                          json={"extra_rows": [{"label": f"行{i}", "value": "x"} for i in range(21)]})
    assert too_many.status_code == 422

    # 还原默认
    assert client.put(f"{RFQ}/print-template", headers=h, json={
        "title": "比 价 单", "orientation": "portrait",
        "sections": {"budget": True, "conditions": True, "scores": True,
                     "reason": True, "conclusion": True},
        "extra_rows": [{"label": "备注", "value": ""}], "footer_note": ""}).status_code == 200


def test_print_template_signatures(client, h):
    """签字栏可自定义（增删/文字），非法值 422。"""
    g = client.get(f"{RFQ}/print-template", headers=h).json()
    assert g["signatures"] == ["制表人", "部门负责人", "单位负责人", "日期"]

    r = client.put(f"{RFQ}/print-template", headers=h, json={
        "signatures": ["制表人", "财务负责人", "见证人"]})
    assert r.status_code == 200, r.text
    assert r.json()["signatures"] == ["制表人", "财务负责人", "见证人"]
    assert client.get(f"{RFQ}/print-template", headers=h).json()["signatures"][1] == "财务负责人"

    too_many = client.put(f"{RFQ}/print-template", headers=h,
                          json={"signatures": [f"签字{i}" for i in range(9)]})
    assert too_many.status_code == 422
    too_long = client.put(f"{RFQ}/print-template", headers=h,
                          json={"signatures": ["超长签字项" * 5]})
    assert too_long.status_code == 422

    # 还原默认
    client.put(f"{RFQ}/print-template", headers=h,
               json={"signatures": ["制表人", "部门负责人", "单位负责人", "日期"]})


def test_signature_columns_default_three(client, h):
    """签字栏默认每行最多 3 个；可配置 1~4；越界 422。"""
    g = client.get(f"{RFQ}/print-template", headers=h).json()
    assert g["signature_columns"] == 3

    r = client.put(f"{RFQ}/print-template", headers=h, json={"signature_columns": 2})
    assert r.status_code == 200 and r.json()["signature_columns"] == 2
    assert client.put(f"{RFQ}/print-template", headers=h,
                      json={"signature_columns": 5}).status_code == 422
    assert client.put(f"{RFQ}/print-template", headers=h,
                      json={"signature_columns": 0}).status_code == 422
    client.put(f"{RFQ}/print-template", headers=h, json={"signature_columns": 3})
