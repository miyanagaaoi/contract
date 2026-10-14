"""电子签名（V2.8）：账号预存签名图片 + 打印单据嵌入签名。

覆盖：
1. 上传 / 查看 / 删除签名 API（权限：超管任意、普通账号仅本人 → 否则 403）；
2. 上传校验：非图片扩展名 → 422、超过 500KB → 422；
3. 打印 `signers` 新口径（值为账号 id）：有签名 → 嵌 `data:image` 图且不印姓名/下划线；
   无签名 → 退回「姓名 + 下划线」；旧格式（姓名字符串）→ 仍只印文字（兼容）；
4. 删除签名后打印退回文字（文件即状态，无库表列）。
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_auth import User
from app.security import hash_password
from app.services import print_service, signature_service

# 极小 PNG 头（本项目不解析像素，只校验扩展名与字节数，见 signature_service 注释）
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


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
def sig_dir(tmp_path, monkeypatch):
    """签名目录指到临时目录：不污染真实 uploads，用例间互不影响。"""
    monkeypatch.setattr(signature_service, "SIGNATURE_DIR", tmp_path)
    return tmp_path


def _make_user(real_name: str) -> tuple[int, dict]:
    """直建启用账号并登录（不走管理接口，避免与角色/密码强度耦合）。"""
    username = f"sig_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        user = User(username=username, real_name=real_name,
                    password_hash=hash_password("init12345"), status="enabled")
        db.add(user)
        db.commit()
        uid = user.id
    with TestClient(app) as c:
        token = c.post("/api/auth/login",
                       json={"username": username, "password": "init12345"}).json()["token"]
    return uid, {"Authorization": f"Bearer {token}"}


def _cleanup_user(uid: int) -> None:
    with SessionLocal() as db:
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def _upload(client, headers, uid: int, *, filename="sign.png", content=PNG_BYTES):
    return client.post(f"/api/system/users/{uid}/signature", headers=headers,
                       files={"file": (filename, content, "image/png")})


# ===================== A. 上传 / 查看 / 删除与权限 =====================

def test_upload_view_and_delete_roundtrip(client, admin, sig_dir):
    uid, own = _make_user("张签名")
    try:
        resp = _upload(client, own, uid)
        assert resp.status_code == 200, resp.text
        assert signature_service.find_signature(uid) is not None
        # 账号列表附带 has_signature（前端据此标注状态）
        listed = client.get("/api/system/users", headers=admin,
                            params={"keyword": "张签名"}).json()
        row = next(i for i in listed["items"] if i["id"] == uid)
        assert row["has_signature"] is True
        # 查看接口：FileResponse 带正确 Content-Type（预览用）
        view = client.get(f"/api/system/users/{uid}/signature", headers=own)
        assert view.status_code == 200
        assert view.headers["content-type"].startswith("image/png")
        # 删除：本人可删；再删 404
        assert client.delete(f"/api/system/users/{uid}/signature",
                             headers=own).status_code == 200
        assert signature_service.find_signature(uid) is None
        assert client.delete(f"/api/system/users/{uid}/signature",
                             headers=own).status_code == 404
    finally:
        _cleanup_user(uid)


def test_superadmin_can_upload_for_others(client, admin, sig_dir):
    uid, _ = _make_user("李被代传")
    try:
        assert _upload(client, admin, uid).status_code == 200
    finally:
        _cleanup_user(uid)


def test_non_self_upload_forbidden(client, sig_dir):
    uid_a, _ = _make_user("王目标")
    _, other = _make_user("赵他人")
    try:
        # 普通账号给**别人**上传 → 403（只能传自己的）
        assert _upload(client, other, uid_a).status_code == 403
        assert client.delete(f"/api/system/users/{uid_a}/signature",
                             headers=other).status_code == 403
        assert signature_service.find_signature(uid_a) is None
    finally:
        _cleanup_user(uid_a)


def test_upload_rejects_bad_ext_and_oversize(client, sig_dir):
    uid, own = _make_user("钱校验")
    try:
        assert _upload(client, own, uid, filename="sign.gif").status_code == 422
        assert _upload(client, own, uid, filename="sign.png",
                       content=b"\x89PNG" + b"0" * (signature_service.MAX_SIGNATURE_BYTES + 1)
                       ).status_code == 422
        assert signature_service.find_signature(uid) is None
    finally:
        _cleanup_user(uid)


# ===================== B. 打印嵌入签名 =====================

@pytest.fixture()
def box(client, admin):
    from app.tests.test_v2_docs import Box

    instance = Box(client, admin)
    try:
        yield instance
    finally:
        instance.cleanup()


def _make_stock_in(box) -> tuple[int, dict]:
    product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
    warehouse = box.warehouse()
    doc = box.create_doc("/api/stock/in-orders", box.headers("keeper"), {
        "warehouse_id": warehouse["id"], "in_type": "其他入库",
        "items": [{"product_id": product["id"], "qty": 3, "unit_price": 10}]})
    return doc["id"], box.client


def test_print_embeds_signature_image(box, sig_dir):
    """有签名：HTML 含 data:image 与 <img>，且不再印姓名文字与下划线（图即签名）。"""
    uid, _ = _make_user("张签名")
    doc_id, client = _make_stock_in(box)
    try:
        assert _upload(client, box.admin, uid).status_code == 200
        resp = client.get(f"/api/stock/in-orders/{doc_id}/print",
                          headers=box.headers("keeper"),
                          params={"signers": json.dumps({"库管员": uid})})
        assert resp.status_code == 200, resp.text
        assert 'src="data:image/png;base64,' in resp.text
        assert '<img class="sig-img"' in resp.text
        assert f"库管员：张签名{chr(95) * print_service.PREFILL_BLANKS}" not in resp.text
    finally:
        _cleanup_user(uid)


def test_print_falls_back_to_name_for_user_without_signature(box, sig_dir):
    """无签名：退回「姓名 + 手写下划线留白」（回归）。"""
    uid, _ = _make_user("李无签")
    doc_id, client = _make_stock_in(box)
    try:
        resp = client.get(f"/api/stock/in-orders/{doc_id}/print",
                          headers=box.headers("keeper"),
                          params={"signers": json.dumps({"库管员": uid})})
        assert resp.status_code == 200, resp.text
        assert "data:image" not in resp.text
        assert "<img" not in resp.text
        assert (f"库管员：李无签{chr(95) * print_service.PREFILL_BLANKS}") in resp.text
    finally:
        _cleanup_user(uid)


def test_print_accepts_legacy_string_signers(box, sig_dir):
    """旧格式（姓名字符串）兼容：仍只印文字，不嵌图。"""
    doc_id, client = _make_stock_in(box)
    resp = client.get(f"/api/stock/in-orders/{doc_id}/print",
                      headers=box.headers("keeper"),
                      params={"signers": json.dumps({"库管员": "王&五"})})
    assert resp.status_code == 200, resp.text
    assert "data:image" not in resp.text
    assert "库管员：王&amp;五" + "_" * print_service.PREFILL_BLANKS in resp.text


def test_print_falls_back_after_delete(box, sig_dir):
    """删除签名后：文件即状态，打印退回姓名文字。"""
    uid, own = _make_user("张签名")
    doc_id, client = _make_stock_in(box)
    try:
        assert _upload(client, own, uid).status_code == 200
        assert client.delete(f"/api/system/users/{uid}/signature",
                             headers=own).status_code == 200
        html = client.get(f"/api/stock/in-orders/{doc_id}/print",
                          headers=box.headers("keeper"),
                          params={"signers": json.dumps({"库管员": uid})}).text
        assert "data:image" not in html
        assert (f"库管员：张签名{chr(95) * print_service.PREFILL_BLANKS}") in html
    finally:
        _cleanup_user(uid)


def test_parse_signers_accepts_int_and_string():
    assert print_service.parse_signers('{"库管员": 12}') == {"库管员": 12}
    assert print_service.parse_signers('{"库管员": "张三"}') == {"库管员": "张三"}
    assert print_service.parse_signers('{"库管员": true}') == {}
