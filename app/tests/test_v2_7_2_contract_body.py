"""CR-045 回归：合同模板/正文/我方签署/对方扫描件置生效。"""
from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models import Contract
from app.models_auth import User


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


def _contract() -> int:
    with SessionLocal() as db:
        sfx = uuid.uuid4().hex[:6]
        c = Contract(contract_no=f"HT{sfx}", name="正文测试合同", type="采购",
                     party_a="智澈公司", party_b="测试供应商", amount=1000)
        db.add(c)
        db.commit()
        return c.id


@pytest.fixture(scope="module")
def tpl(client, h):
    r = client.post("/api/contract-templates", headers=h, json={
        "name": "标准采购合同", "contract_type": "采购",
        "body_html": "<h1>采购合同</h1><p>甲方：{{party_a}}</p><p>乙方：{{party_b}}</p><p>金额：{{amount}} 元</p>",
        "fields": [
            {"key": "party_a", "label": "甲方", "type": "text", "required": True},
            {"key": "party_b", "label": "乙方", "type": "text", "required": True},
            {"key": "amount", "label": "金额", "type": "number", "required": True},
        ]})
    assert r.status_code == 200, r.text
    return r.json()


def test_body_render_and_snapshot(client, h, tpl):
    cid = _contract()
    vals = {"party_a": "智澈公司", "party_b": "测试供应商", "amount": 1000}
    r = client.put(f"/api/contracts/{cid}/body", headers=h,
                   json={"template_id": tpl["id"], "field_values": vals})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "智澈公司" in body["body_html"] and "1000" in body["body_html"]
    assert "{{" not in body["body_html"]
    assert len(body["body_hash"]) == 64
    assert body["sign_status"] == "none"

    # 必填缺失 422
    bad = client.put(f"/api/contracts/{cid}/body", headers=h,
                     json={"template_id": tpl["id"], "field_values": {"party_a": "X"}})
    assert bad.status_code == 422

    # 无签名不能签署（其它用例可能已上传过管理员签名，这里先清掉，避免顺序依赖）
    from sqlalchemy import select

    from app.services import signature_service

    with SessionLocal() as db:
        admin = db.execute(select(User).where(User.username == ADMIN_USERNAME)).scalar_one()
        admin_id = admin.id
    signature_service.delete_signature(admin_id)
    n = client.post(f"/api/contracts/{cid}/sign", headers=h)
    assert n.status_code == 422 and "签名" in n.json()["detail"]

    # 上传签名（1x1 PNG）后签署
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
                        "890000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082")
    up = client.post(f"/api/system/users/{admin_id}/signature", headers=h,
                     files={"file": ("sig.png", png, "image/png")})
    assert up.status_code == 200, up.text
    s = client.post(f"/api/contracts/{cid}/sign", headers=h)
    assert s.status_code == 200, s.text
    assert s.json()["sign_status"] == "our_signed"

    # 签署后正文只读
    ro = client.put(f"/api/contracts/{cid}/body", headers=h,
                    json={"template_id": tpl["id"], "field_values": vals})
    assert ro.status_code == 422

    # 上传对方扫描件 → 生效
    scan = client.post(f"/api/contracts/{cid}/counterpart-scan", headers=h,
                       files={"file": ("counterpart.png", png, "image/png")})
    assert scan.status_code == 200, scan.text
    assert scan.json()["sign_status"] == "completed"


def test_template_html_sanitized(client, h):
    """CR-048：模板正文做白名单清洗（脚本/事件属性/javascript: 链接被移除）。"""
    r = client.post("/api/contract-templates", headers=h, json={
        "name": "清洗测试模板", "contract_type": "采购",
        "body_html": '<script>alert(1)</script><p onclick="alert(2)">正文</p>'
                     '<a href="javascript:alert(3)">链接</a><h2>标题</h2>',
        "fields": []})
    assert r.status_code == 200, r.text
    body = r.json()["body_html"]
    assert "<script" not in body.lower() and "onclick" not in body.lower()
    assert "javascript:" not in body.lower()
    assert "正文" in body and "<h2>" in body


def test_span_tokens_render(client, h):
    """CR-049：富文本令牌 <span data-key> 也能被渲染成字段值（显示【字段名】）。"""
    tpl = client.post("/api/contract-templates", headers=h, json={
        "name": "令牌渲染模板", "contract_type": "采购",
        "body_html": '<p>甲方：<span class="ct-field" data-key="party_a">【甲方名称】</span></p>',
        "fields": [{"key": "party_a", "label": "甲方名称", "type": "text", "required": True}]})
    assert tpl.status_code == 200, tpl.text
    cid = _contract()
    r = client.put(f"/api/contracts/{cid}/body", headers=h, json={
        "template_id": tpl.json()["id"], "field_values": {"party_a": "智澈公司"}})
    assert r.status_code == 200, r.text
    body = r.json()["body_html"]
    assert "智澈公司" in body and "【甲方名称】" not in body


def _tiny_docx() -> bytes:
    import io
    import zipfile

    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body>'
           '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>购销服务合同</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>甲方：{{party_a}}</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>产品名称</w:t></w:r></w:p></w:tc>'
           '<w:tc><w:p><w:r><w:t>数量</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           '</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_import_word_docx(client, h):
    """CR-049：上传 .docx 解析为 HTML（标题/段落/表格）。"""
    r = client.post("/api/contract-templates/import-docx", headers=h,
                    files={"file": ("合同.docx", _tiny_docx(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 200, r.text
    html = r.json()["html"]
    assert "<h1>购销服务合同</h1>" in html
    assert "{{party_a}}" in html
    assert "<table" in html and "产品名称" in html
    # 非 docx 拒绝
    bad = client.post("/api/contract-templates/import-docx", headers=h,
                      files={"file": ("a.txt", b"x", "text/plain")})
    assert bad.status_code == 422
