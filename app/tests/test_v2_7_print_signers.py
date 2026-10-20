"""V2.6 改进：打印签字位「系统账号预填」与组织架构「部门负责人」。

覆盖四块：
1. 库存类单据（入库/出库/调拨/盘点）默认签字栏改为两行 5 项（3 + 2 自动换行），
   其余单据（采购/销售/财务）默认值不变；
2. 打印接口 `?signers=` 预填姓名：预填位印真实姓名 + 缩短下划线、姓名做 HTML 转义；
3. 未传 signers 时签字栏与原先完全一致（回归）；
4. org-units 接口与组织下拉暴露 `leader_user_id` / `leader_name`。
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_auth import Role, User
from app.security import hash_password
from app.services import print_service, print_template_service

BUYER, KEEPER = "buyer", "keeper"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin(client):
    resp = client.post("/api/auth/login",
                       json={"username": ADMIN_USERNAME, "password": ADMIN_INIT_PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture()
def box(client, admin):
    """复用 test_v2_docs 的单据工厂（最小版：本模块只造入库单）。"""
    from app.tests.test_v2_docs import Box

    instance = Box(client, admin)
    try:
        yield instance
    finally:
        instance.cleanup()


# ===================== A. 库存类默认签字栏（两行 5 项） =====================

def test_stock_default_signature_labels_two_rows():
    """入库/出库/调拨/盘点：默认签字栏 5 项，按每行 3 个分成 3 + 2 两行。"""
    for kind in ("stock_in", "stock_out", "stock_transfer", "stock_take"):
        cfg = print_template_service.default_config(kind)
        # V2.6.1：两个「部门负责人」用 #1/#2 内部键区分选人，显示文字不变
        assert cfg["signature_labels"] == [
            "库管员", "采购人", "财务", "部门负责人#1", "部门负责人#2"], kind
        rows = print_service._split_sign_rows(cfg["signature_labels"])
        from app.services.print_template_service import display_sign_label as _d
        assert rows == [["库管员", "采购人", "财务"],
                        ["部门负责人#1", "部门负责人#2"]], kind
        assert [_d(x) for x in rows[1]] == ["部门负责人", "部门负责人"], kind


def test_other_kinds_default_labels_unchanged():
    """非库存单据默认签字栏保持原值（采购/销售沿用通用四项，付款单六项）。"""
    for kind in ("purchase_request", "purchase_order",
                 "sales_request", "sales_order"):
        cfg = print_template_service.default_config(kind)
        assert cfg["signature_labels"] == print_template_service.DEFAULT_SIGN_LABELS, kind
    pay = print_template_service.default_config("payment")
    assert pay["signature_labels"] == print_template_service.PAYMENT_SIGN_LABELS


# ===================== B. signers 预填渲染 =====================

def test_render_sign_prefills_name_and_escapes():
    """预填姓名：印在冒号后 + 8 个下划线留白；姓名按不可信文本转义。"""
    cfg = print_template_service.normalize_config("stock_in", {
        "signature_labels": ["库管员", "采购人", "财务"]})
    doc = print_service.sample_doc("stock_in")
    html = print_service._render_sign(doc, cfg, {"库管员": "张<b>三"})
    assert "库管员：张&lt;b&gt;三" + "_" * print_service.PREFILL_BLANKS in html
    # 未选账号的签字位保持现状：只有「角色：」，无姓名、无预填下划线
    assert "<td>采购人：</td>" in html
    assert "<td>财务：</td>" in html


def test_payment_application_prefill_shortens_blanks():
    """付款申请单固定网格：预填时姓名 + 8 下划线；未预填保持 14 下划线。"""
    cfg = print_template_service.normalize_config("payment", {
        "signature_labels": ["经理", "部门负责人"]})
    doc = print_service.sample_doc("payment")
    html = print_service._render_payment_application(doc, cfg, None, {"经理": "李四"})
    assert "经理：李四" + "_" * print_service.PREFILL_BLANKS in html
    assert "部门负责人：" + "_" * 14 in html


def test_parse_signers_tolerates_bad_input():
    assert print_service.parse_signers(None) == {}
    assert print_service.parse_signers("不是json") == {}
    assert print_service.parse_signers('["数组"]') == {}
    assert print_service.parse_signers('{"库管员": "  ", "财务": "王五"}') == {"财务": "王五"}


def test_print_endpoint_accepts_signers(box):
    """打印接口：?signers= 预填姓名并转义（入库单，box 工厂造数）。"""
    product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
    warehouse, keeper = box.warehouse(), box.headers(KEEPER)
    doc = box.create_doc("/api/stock/in-orders", keeper, {
        "warehouse_id": warehouse["id"], "in_type": "其他入库",
        "items": [{"product_id": product["id"], "qty": 3, "unit_price": 10}]})
    signers = json.dumps({"库管员": "王&五"}, ensure_ascii=False)
    resp = box.client.get(f"/api/stock/in-orders/{doc['id']}/print",
                          headers=keeper, params={"signers": signers})
    assert resp.status_code == 200, resp.text
    assert "库管员：王&amp;五" + "_" * print_service.PREFILL_BLANKS in resp.text


# ===================== 回归：未传 signers 与原先一致 =====================

def test_print_without_signers_unchanged(box):
    """不带 signers 打印：签字位仍是 `角色：`，不出现预填下划线。"""
    product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
    warehouse, keeper = box.warehouse(), box.headers(KEEPER)
    doc = box.create_doc("/api/stock/in-orders", keeper, {
        "warehouse_id": warehouse["id"], "in_type": "其他入库",
        "items": [{"product_id": product["id"], "qty": 2, "unit_price": 10}]})
    html = box.client.get(f"/api/stock/in-orders/{doc['id']}/print",
                          headers=keeper).text
    assert "<td>库管员：</td>" in html
    for label in ("采购人", "财务", "部门负责人"):
        assert f"<td>{label}：</td>" in html


# ===================== C. org-units 暴露部门负责人 =====================

def test_org_units_expose_leader(client, admin):
    """创建/回读组织节点带 leader_user_id 与 leader_name；组织下拉也带负责人姓名。"""
    with SessionLocal() as db:
        role = db.query(Role).filter(Role.code == "keeper").first()
        user = User(username=f"ldr_{uuid.uuid4().hex[:8]}", real_name="负责人-测试",
                    password_hash=hash_password("init12345"), status="enabled")
        if role is not None:
            user.roles.append(role)
        db.add(user)
        db.commit()
        uid = user.id
    name = f"打印签字部{uuid.uuid4().hex[:5]}"
    try:
        created = client.post("/api/system/org-units", headers=admin,
                              json={"name": name, "unit_type": "部门",
                                    "leader_user_id": uid}).json()
        assert created["leader_user_id"] == uid
        assert created["leader_name"] == "负责人-测试"

        listed = client.get("/api/system/org-units", headers=admin).json()
        node = next(i for i in listed["items"] if i["id"] == created["id"])
        assert node["leader_user_id"] == uid and node["leader_name"] == "负责人-测试"

        # 组织下拉（登录即可）也带负责人，供打印前选人对话框默认带出
        opts = client.get("/api/master/options/org", headers=admin).json()
        opt = next(o for o in opts if o["id"] == created["id"])
        assert opt["leader_user_id"] == uid and opt["leader_name"] == "负责人-测试"

        # 清空负责人：传空即可（可清空交互的后端口径）
        cleared = client.put(f"/api/system/org-units/{created['id']}", headers=admin,
                             json={"name": name, "leader_user_id": ""}).json()
        assert cleared["leader_user_id"] is None and cleared["leader_name"] is None
    finally:
        client.delete(f"/api/system/org-units/{created['id']}", headers=admin)
        with SessionLocal() as db:
            db.query(User).filter(User.id == uid).delete()
            db.commit()
