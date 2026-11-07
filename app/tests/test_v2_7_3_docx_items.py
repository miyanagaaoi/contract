"""CR-051 回归：mammoth 保真导入 + 合同标的物表格（CR-052）。"""
from __future__ import annotations

import io
import uuid

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models import Contract, ContractItem

import base64

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


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


def _rich_docx() -> bytes:
    doc = Document()
    doc.add_heading("购销服务合同", level=1)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("甲方：{{party_a}}")
    run.bold = True
    run.font.size = Pt(16)
    body = doc.add_paragraph("本合同经双方协商一致签订。")
    body.paragraph_format.first_line_indent = Pt(21)
    table = doc.add_table(rows=2, cols=2)
    merged = table.cell(0, 0).merge(table.cell(0, 1))
    merged.text = "产品明细"
    table.cell(1, 0).text = "产品名称"
    table.cell(1, 1).text = "数量"
    tmp = io.BytesIO(PNG)
    doc.add_picture(tmp)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_import_word_with_mammoth(client, h):
    """mammoth 解析：标题/居中加粗字号/首行缩进/合并单元格/图片。"""
    r = client.post("/api/contract-templates/import-docx", headers=h,
                    files={"file": ("合同.docx", _rich_docx(),
                                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 200, r.text
    html = r.json()["html"]
    assert "<h1" in html and "购销服务合同" in html
    assert "text-align:center" in html
    assert "<strong>" in html or "font-weight" in html
    assert "font-size:" in html
    assert "text-indent:2em" in html
    assert "<table" in html and "colspan" in html
    assert "data:image/" in html


def _contract_with_item() -> int:
    with SessionLocal() as db:
        sfx = uuid.uuid4().hex[:6]
        c = Contract(contract_no=f"HTI{sfx}", name="标的表格合同", type="采购",
                     party_a="智澈公司", party_b="供应商", amount=1000)
        db.add(c)
        db.flush()
        db.add(ContractItem(contract_id=c.id, seq=1, name="球阀", spec="DN25",
                            qty=2, unit_price=500, total=1000))
        db.commit()
        return c.id


def test_items_table_in_body(client, h):
    """CR-052：模板里的标的物表格令牌会被合同行项渲染为表格。"""
    tpl = client.post("/api/contract-templates", headers=h, json={
        "name": "标的表格模板", "contract_type": "采购",
        "body_html": '<h2>第一条 合同标的</h2>'
                     '<p><span class="ct-field" data-key="items_table">【标的物表格】</span></p>',
        "fields": []})
    assert tpl.status_code == 200, tpl.text
    cid = _contract_with_item()
    r = client.put(f"/api/contracts/{cid}/body", headers=h,
                   json={"template_id": tpl.json()["id"], "field_values": {}})
    assert r.status_code == 200, r.text
    body = r.json()["body_html"]
    assert "<table" in body and "球阀" in body and "DN25" in body
    assert "【标的物表格】" not in body
    edit = client.put(f"/api/contracts/{cid}/body-html", headers=h,
                      json={"body_html": body.replace("球阀", "球阀（改）")})
    assert edit.status_code == 200, edit.text
    assert "球阀（改）" in edit.json()["body_html"]


def test_warning_filter_ignores_tblprex():
    """w:tblPrEx 等无害提示不应展示给用户；真实告警保留。"""
    from types import SimpleNamespace

    from app.services.docx_import_service import _filter_warnings

    msgs = [
        SimpleNamespace(type="warning", message="An unrecognised element was ignored: w:tblPrEx"),
        SimpleNamespace(type="warning", message="An unrecognised element was ignored: w:proofErr"),
        SimpleNamespace(type="warning", message="图片格式不支持"),
        SimpleNamespace(type="error", message="An unrecognised element was ignored: w:tblPrEx"),
    ]
    assert _filter_warnings(msgs) == ["图片格式不支持"]
