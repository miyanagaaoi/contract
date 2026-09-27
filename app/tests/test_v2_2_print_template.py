"""V2.2 打印模板测试（BR-V2.2-02）。

覆盖：
- AC-V2.2-P1 模板列表返回八类单据 + 编辑界面元数据；
- AC-V2.2-P2 未自定义时等于出厂模板，出厂模板与旧版硬编码版面字段一致；
- AC-V2.2-P3 保存后可回读；标题/字段顺序/列显隐/签字栏都生效；
- AC-V2.2-P4 脏数据被归一（未知字段与列丢弃、非法表头列数回落）——模板坏了会打印不出来；
- AC-V2.2-P5 恢复出厂；
- AC-V2.2-P6 预览用**提交的**配置渲染样例单据；
- AC-V2.2-P7 权限：无 `system.print.view` 读也 403，无 `system.print.edit` 写 403；
- AC-V2.2-P8 打印渲染回归：默认模板下标题、合计行、签字栏仍然正确。

模板是**全局配置**，本模块用例会写库，结束后统一清空（防污染开发库）。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_auth import Role, User
from app.models_doc import PrintTemplate
from app.security import hash_password
from app.services import print_service, print_template_service

API = "/api/system/print-templates"


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
def clean_templates():
    """模板是全局配置：跑完把自定义模板全部清掉，恢复出厂版面。"""
    yield
    with SessionLocal() as db:
        db.query(PrintTemplate).delete()
        db.commit()


def _mk_user_with_role(role_code: str) -> int:
    username = f"pt_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        role = db.query(Role).filter(Role.code == role_code).one()
        user = User(username=username, real_name="打印模板测试账号",
                    password_hash=hash_password("init12345"), status="enabled")
        user.roles.append(role)
        db.add(user)
        db.commit()
        return user.id


def _drop_user(uid: int) -> None:
    with SessionLocal() as db:
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def _token_of(client, uid: int) -> str:
    with SessionLocal() as db:
        username = db.get(User, uid).username
    return client.post("/api/auth/login",
                       json={"username": username, "password": "init12345"}).json()["token"]


# ===================== 目录与默认值 =====================

def test_list_returns_all_kinds_and_meta(client, h):
    data = client.get(API, headers=h).json()
    kinds = [item["kind"] for item in data["items"]]
    assert kinds == [kind for kind, _ in print_template_service.KINDS]
    assert set(["purchase_order", "stock_take", "stock_transfer"]).issubset(set(kinds))
    meta = data["meta"]
    assert [b["key"] for b in meta["blocks"]] == ["title", "head", "items", "sign"]
    assert any(f["key"] == "doc_no" for f in meta["head_fields"])
    assert any(c["key"] == "amount" for c in meta["item_columns"])
    # 未自定义时 customized 为假
    assert all(item["customized"] is False for item in data["items"])


def test_default_template_matches_factory(client, h):
    detail = client.get(f"{API}/purchase_order", headers=h).json()
    assert detail["label"] == "采购单"
    assert detail["customized"] is False
    cfg = detail["config"]
    assert cfg == detail["factory"]
    assert cfg["title"] == "采购单"
    assert cfg["head_columns"] == 2
    assert cfg["blocks"] == ["title", "head", "items", "sign"]
    # 采购单是金额单据：单价/金额默认开，盘点专用列默认关
    enabled = {c["key"] for c in cfg["item_columns"] if c["enabled"]}
    assert {"unit_price", "amount"} <= enabled
    assert not ({"book_qty", "actual_qty", "diff_qty", "diff_reason"} & enabled)


def test_take_template_swaps_columns():
    """盘点单默认没有单价/金额，改为账面/实盘/差异列。"""
    cfg = print_template_service.default_config("stock_take")
    enabled = {c["key"] for c in cfg["item_columns"] if c["enabled"]}
    assert {"book_qty", "actual_qty", "diff_qty", "diff_reason"} <= enabled
    assert not ({"unit_price", "amount"} & enabled)
    assert cfg["signature_labels"] == print_template_service.TAKE_SIGN_LABELS


# ===================== 保存 / 归一化 / 恢复 =====================

def test_save_and_read_back(client, h):
    detail = client.get(f"{API}/purchase_order", headers=h).json()
    cfg = detail["config"]
    cfg["title"] = "采购订单（自定义）"
    cfg["subtitle"] = "某某公司"
    cfg["footer"] = "内部资料，请勿外传"
    # 把"仓库"字段提到最前并改标签
    fields = [f for f in cfg["head_fields"] if f["key"] != "warehouse"]
    fields.insert(0, {"key": "warehouse", "label": "收货仓库", "enabled": True, "full": False})
    cfg["head_fields"] = fields
    cfg["signature_labels"] = ["制单", "复核"]
    cfg["blocks"] = ["head", "items", "sign", "title"]

    saved = client.put(f"{API}/purchase_order", headers=h, json={"config": cfg})
    assert saved.status_code == 200, saved.text

    back = client.get(f"{API}/purchase_order", headers=h).json()
    assert back["customized"] is True
    got = back["config"]
    assert got["title"] == "采购订单（自定义）"
    assert got["subtitle"] == "某某公司"
    assert got["head_fields"][0]["key"] == "warehouse"
    assert got["head_fields"][0]["label"] == "收货仓库"
    assert got["signature_labels"] == ["制单", "复核"]
    assert got["blocks"] == ["head", "items", "sign", "title"]
    assert back["factory"]["title"] == "采购单"       # 出厂值不受影响


def test_save_normalizes_dirty_input(client, h):
    """未知字段/列被丢弃、非法表头列数回落、空签字栏回落默认。"""
    resp = client.put(f"{API}/purchase_order", headers=h, json={"config": {
        "title": "  脏数据模板  ",
        "head_columns": 9,
        "blocks": ["items", "不存在的区块"],
        "head_fields": [{"key": "doc_no", "label": "单号"}, {"key": "no_such_field"}],
        "item_columns": [{"key": "amount", "enabled": False}, {"key": "no_such_column"}],
        "signature_labels": ["", "   "],
    }})
    assert resp.status_code == 200, resp.text
    cfg = resp.json()["config"]
    assert cfg["title"] == "脏数据模板"                     # 去空白
    assert cfg["head_columns"] == 2                        # 非法值回落默认
    assert cfg["blocks"] == ["items", "title", "head", "sign"]   # 未知区块丢弃，缺的补齐
    keys = [f["key"] for f in cfg["head_fields"]]
    assert "no_such_field" not in keys
    assert keys[0] == "doc_no" and keys.count("doc_no") == 1
    assert "no_such_column" not in [c["key"] for c in cfg["item_columns"]]
    assert cfg["signature_labels"] == print_template_service.DEFAULT_SIGN_LABELS


def test_all_columns_disabled_falls_back(client, h):
    """所有行项列都被关掉时至少恢复默认可见列——否则明细表会退化成空表。"""
    resp = client.put(f"{API}/stock_in", headers=h, json={"config": {
        "item_columns": [{"key": key, "enabled": False}
                         for key, _, _ in print_template_service.ITEM_COLUMN_CATALOG],
    }})
    assert resp.status_code == 200, resp.text
    enabled = [c["key"] for c in resp.json()["config"]["item_columns"] if c["enabled"]]
    assert enabled, "至少要保留一列"


def test_reset_restores_factory(client, h):
    client.put(f"{API}/sales_order", headers=h, json={"config": {"title": "临时标题"}})
    assert client.get(f"{API}/sales_order", headers=h).json()["customized"] is True

    reset = client.post(f"{API}/sales_order/reset", headers=h)
    assert reset.status_code == 200, reset.text
    assert reset.json()["config"]["title"] == "销售订单"

    after = client.get(f"{API}/sales_order", headers=h).json()
    assert after["customized"] is False
    assert after["config"] == after["factory"]


def test_unknown_kind_404(client, h):
    assert client.get(f"{API}/not_a_kind", headers=h).status_code == 404
    assert client.put(f"{API}/not_a_kind", headers=h, json={"config": {}}).status_code == 422


# ===================== 预览 =====================

def test_preview_renders_submitted_config(client, h):
    # 前面的用例写过库，先恢复出厂，才能验证"预览不落库"
    client.post(f"{API}/purchase_order/reset", headers=h)
    html = client.post(f"{API}/purchase_order/preview", headers=h, json={"config": {
        "title": "预览专用标题",
        "subtitle": "",
        "show_printed_at": False,
        "footer": "预览页脚",
        "signature_labels": ["制单", "复核"],
        "item_columns": [
            {"key": "seq", "label": "序", "enabled": True},
            {"key": "product_name", "label": "品名", "enabled": True},
            {"key": "qty", "label": "数量", "enabled": True},
            {"key": "amount", "label": "金额", "enabled": True},
            {"key": "spec", "label": "规格", "enabled": False},
        ],
    }}).text
    assert "预览专用标题" in html
    assert "预览页脚" in html
    assert "复核" in html
    assert "<th>品名</th>" in html
    assert "规格" not in html          # 关掉的列不出现
    assert "单价" not in html
    # 预览不应把配置写进库
    assert client.get(f"{API}/purchase_order", headers=h).json()["customized"] is False


def test_preview_without_config_uses_stored(client, h):
    client.put(f"{API}/stock_in", headers=h, json={"config": {"title": "入库单（已保存）"}})
    html = client.post(f"{API}/stock_in/preview", headers=h, json={}).text
    assert "入库单（已保存）" in html


# ===================== 权限 =====================

def test_read_requires_perm_view(client):
    uid = _mk_user_with_role("viewer")     # viewer 没有 system.print.view
    try:
        token = _token_of(client, uid)
        resp = client.get(API, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403, resp.text
    finally:
        _drop_user(uid)


def test_write_requires_perm_edit(client):
    """只给 view 的角色能读不能写（按钮权限是独立权限点）。"""
    with SessionLocal() as db:
        role = db.query(Role).filter(Role.code == "finance").one()
        assert "system.print.view" not in set(role.perm_codes)   # 前置条件：该角色确实没有

    uid = _mk_user_with_role("finance")
    try:
        token = _token_of(client, uid)
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get(API, headers=headers).status_code == 403
        assert client.put(f"{API}/purchase_order", headers=headers,
                          json={"config": {"title": "越权"}}).status_code == 403
    finally:
        _drop_user(uid)


# ===================== 渲染回归 =====================

def test_default_rendering_keeps_legacy_layout():
    """默认模板下，打印 HTML 与旧版硬编码版面等价（标题/表头/合计/签字栏都在）。

    显式传入出厂模板：本模块前面的用例写过库，不能依赖"库里恰好没有自定义"。
    """
    with SessionLocal() as db:
        doc = print_service.sample_doc("purchase_order")
        html = print_service.build_doc_print_html(
            db, doc, print_template_service.default_config("purchase_order"))
    assert "<h1>采购单</h1>" in html
    assert "CTMS · ERP 进销存" in html
    assert "单据编号" in html and "供应商" in html
    assert "<th>物料名称</th>" in html and "<th>金额</th>" in html
    assert "合计" in html
    assert "制单：" in html and "审核：" in html
    assert "本单据由系统生成" in html


def test_window_print_toolbar_present():
    with SessionLocal() as db:
        html = print_service.build_doc_print_html(
            db, print_service.sample_doc("stock_take"),
            print_template_service.default_config("stock_take"))
    assert "window.print()" in html
    # 盘点单印账面/实盘/差异
    assert "账面数量" in html and "实盘数量" in html and "差异" in html


def test_sample_doc_covers_every_kind():
    for kind, _label in print_template_service.KINDS:
        doc = print_service.sample_doc(kind)
        assert print_service.doc_kind_of(doc) == kind
        assert len(doc.items) >= 1
