"""T-V2-02 接口测试：认证、授权与改密。

对应验收场景：AC-V2-01（登录与鉴权）、AC-V2-02（未登录拦截）、
AC-V2-08（首登强制改密/管理员重置）、AC-V2-41（后端强制校验）。

说明：测试直接操作开发库，因此**不修改 admin 密码**；
改密与停用相关用例使用临时账号并在结束时清理。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_auth import OperationLog, User
from app.security import hash_password


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:      # 触发 lifespan：建表 + 增量迁移 + 种子（幂等）
        yield c


@pytest.fixture(scope="module")
def admin_token(client):
    resp = client.post("/api/auth/login",
                       json={"username": ADMIN_USERNAME, "password": ADMIN_INIT_PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _mk_user(client, prefix: str, *, status: str = "enabled", password: str = "init12345"):
    """建一个临时账号，返回 (id, username, token|None)。"""
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        user = User(username=username, real_name="临时测试账号",
                    password_hash=hash_password(password), status=status)
        db.add(user)
        db.commit()
        uid = user.id
    token = None
    if status == "enabled":
        token = client.post("/api/auth/login",
                            json={"username": username, "password": password}).json()["token"]
    return uid, username, token


def _drop_user(uid: int) -> None:
    with SessionLocal() as db:
        db.query(OperationLog).filter(OperationLog.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


# ===================== 登录与鉴权 =====================

class TestLogin:
    def test_requires_auth_without_token(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_wrong_password_rejected(self, client):
        resp = client.post("/api/auth/login",
                           json={"username": ADMIN_USERNAME, "password": "wrong-pass-1"})
        assert resp.status_code == 401
        assert "用户名或密码错误" in resp.json()["detail"]

    def test_unknown_user_same_message(self, client):
        # 不区分"账号不存在/密码错误"，避免账号枚举
        resp = client.post("/api/auth/login",
                           json={"username": "no_such_user_xyz", "password": "whatever1"})
        assert resp.status_code == 401
        assert "用户名或密码错误" in resp.json()["detail"]

    def test_login_success(self, client, admin_token):
        assert admin_token

    def test_me_returns_perms_and_menus(self, client, admin_token):
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["username"] == ADMIN_USERNAME
        assert data["user"]["is_superadmin"] is True
        assert "purchase.order.approve" in data["perms"]
        assert "system.backup.download" in data["perms"]
        assert data["menus"], "超管应返回完整菜单树"
        assert {n["key"] for n in data["menus"]} >= {"dashboard", "purchase", "stock", "master"}

    def test_me_requires_change_flag_on_fresh_account(self, client):
        uid, uname, token = _mk_user(client, "fp")
        try:
            data = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
            assert data["user"]["must_change_pwd"] is False   # 直接建的账号未置标记
        finally:
            _drop_user(uid)

    def test_tampered_token_rejected(self, client):
        bogus = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.not-a-signature"
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {bogus}"})
        assert resp.status_code == 401

    def test_garbage_token_rejected(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer abc.def"})
        assert resp.status_code == 401

    def test_disabled_account_cannot_login(self, client):
        uid, uname, _ = _mk_user(client, "dis", status="disabled")
        try:
            resp = client.post("/api/auth/login",
                               json={"username": uname, "password": "init12345"})
            assert resp.status_code == 403
            assert "停用" in resp.json()["detail"]
        finally:
            _drop_user(uid)

    def test_disabling_account_invalidates_existing_token(self, client):
        """停用立即失效：无状态令牌靠每次请求回查账号状态实现。"""
        uid, uname, token = _mk_user(client, "inv")
        try:
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/api/auth/me", headers=headers).status_code == 200
            with SessionLocal() as db:
                db.query(User).filter(User.id == uid).update({"status": "disabled"})
                db.commit()
            assert client.get("/api/auth/me", headers=headers).status_code == 401
        finally:
            _drop_user(uid)


# ===================== 操作日志 =====================

class TestAuditLog:
    def test_login_writes_operation_log(self, client, admin_token):
        with SessionLocal() as db:
            rows = (db.query(OperationLog)
                    .filter(OperationLog.module == "auth", OperationLog.action == "login")
                    .count())
        assert rows > 0

    def test_failed_login_is_logged(self, client):
        client.post("/api/auth/login",
                    json={"username": ADMIN_USERNAME, "password": "definitely-wrong-1"})
        with SessionLocal() as db:
            rows = (db.query(OperationLog)
                    .filter(OperationLog.action == "login", OperationLog.result == "fail")
                    .count())
        assert rows > 0

    def test_logout_writes_log(self, client):
        uid, uname, token = _mk_user(client, "out")
        try:
            with SessionLocal() as db:
                before = db.query(OperationLog).filter(OperationLog.action == "logout").count()
            resp = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200
            with SessionLocal() as db:
                after = db.query(OperationLog).filter(OperationLog.action == "logout").count()
            assert after == before + 1
        finally:
            _drop_user(uid)


# ===================== 修改密码（AC-V2-08） =====================

class TestChangePassword:
    def test_full_flow_on_temporary_account(self, client):
        uid, uname, token = _mk_user(client, "pwd")
        headers = {"Authorization": f"Bearer {token}"}
        try:
            # 原密码错误
            resp = client.post("/api/auth/change-password", headers=headers,
                               json={"old_password": "nope12345", "new_password": "newpass123"})
            assert resp.status_code == 422
            assert "原密码" in resp.json()["detail"]

            # 强度不足：无数字
            resp = client.post("/api/auth/change-password", headers=headers,
                               json={"old_password": "init12345", "new_password": "abcdefghij"})
            assert resp.status_code == 422
            assert "字母与数字" in resp.json()["detail"]

            # 强度不足：过短
            resp = client.post("/api/auth/change-password", headers=headers,
                               json={"old_password": "init12345", "new_password": "a1b2"})
            assert resp.status_code == 422
            assert "长度" in resp.json()["detail"]

            # 与原密码相同
            resp = client.post("/api/auth/change-password", headers=headers,
                               json={"old_password": "init12345", "new_password": "init12345"})
            assert resp.status_code == 422

            # 成功
            resp = client.post("/api/auth/change-password", headers=headers,
                               json={"old_password": "init12345", "new_password": "newpass123"})
            assert resp.status_code == 200

            # 旧密码失效、新密码可登录
            assert client.post("/api/auth/login",
                               json={"username": uname, "password": "init12345"}).status_code == 401
            assert client.post("/api/auth/login",
                               json={"username": uname, "password": "newpass123"}).status_code == 200
        finally:
            _drop_user(uid)

    def test_clears_must_change_flag(self, client):
        """管理员重置后的账号（must_change_pwd=True）改密后标记清除。"""
        uid, uname, token = _mk_user(client, "mcp")
        try:
            with SessionLocal() as db:
                db.query(User).filter(User.id == uid).update({"must_change_pwd": True})
                db.commit()
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/api/auth/me", headers=headers).json()["user"]["must_change_pwd"] is True
            client.post("/api/auth/change-password", headers=headers,
                        json={"old_password": "init12345", "new_password": "reset12345"})
            assert client.get("/api/auth/me", headers=headers).json()["user"]["must_change_pwd"] is False
        finally:
            _drop_user(uid)

    def test_requires_login(self, client):
        resp = client.post("/api/auth/change-password",
                           json={"old_password": "a", "new_password": "b"})
        assert resp.status_code == 401

    def test_admin_password_untouched(self, client, admin_token):
        """确认测试没有改动 admin 密码（否则会破坏本地开发环境）。"""
        resp = client.post("/api/auth/login",
                           json={"username": ADMIN_USERNAME, "password": ADMIN_INIT_PASSWORD})
        assert resp.status_code == 200
