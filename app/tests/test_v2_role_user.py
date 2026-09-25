"""T-V2-04 / T-V2-05 测试：角色管理与账号管理。

对应验收场景：AC-V2-03（菜单与按钮权限）、AC-V2-04~06（数据范围）、
AC-V2-08（首登强制改密与管理员重置）、AC-V2-41（后端强制校验）。

测试在开发库中创建临时角色/账号并在 finally 中清理，不改动 admin 密码与内置角色权限。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_auth import OperationLog, Role, User
from app.permissions import PERM_CODES
from app.security import hash_password

ROLES = "/api/system/roles"
USERS = "/api/system/users"


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


# ---------------- 辅助 ----------------

def _role_by_code(client, h, code: str) -> dict:
    items = client.get(ROLES, headers=h).json()["items"]
    return next(r for r in items if r["code"] == code)


def _mk_account(role_codes=("sysadmin",), password="init12345") -> int:
    """直连数据库建临时账号（绕过接口，便于构造前置条件）。"""
    username = f"t_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        user = User(username=username, real_name="临时账号",
                    password_hash=hash_password(password), status="enabled")
        for code in role_codes:
            role = db.query(Role).filter(Role.code == code).first()
            if role is not None:
                user.roles.append(role)
        db.add(user)
        db.commit()
        return user.id


def _drop(uid: int) -> None:
    with SessionLocal() as db:
        db.query(OperationLog).filter(OperationLog.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def _login(client, uid: int, password="init12345") -> str | None:
    with SessionLocal() as db:
        username = db.get(User, uid).username
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    return resp.json().get("token") if resp.status_code == 200 else None


# ===================== 角色管理 =====================

class TestRoleApi:
    def test_builtin_roles_listed(self, client, h):
        data = client.get(ROLES, headers=h).json()
        codes = {r["code"] for r in data["items"]}
        assert {"sysadmin", "purchase_manager", "buyer", "sales_manager",
                "seller", "keeper", "finance", "viewer"} <= codes
        assert data["perm_total"] == len(PERM_CODES)
        assert {s["code"] for s in data["data_scopes"]} == {"SELF", "DEPT", "DEPT_SUB", "ALL"}
        assert all(r["builtin"] for r in data["items"] if r["code"] == "sysadmin")

    def test_permission_metadata_grouped(self, client, h):
        data = client.get("/api/system/permissions", headers=h).json()
        modules = {g["module"] for g in data["tree"]}
        assert {"dashboard", "contract", "purchase", "sales", "stock", "master", "system"} <= modules

    def test_create_update_delete_role(self, client, h):
        code = f"tmp_{uuid.uuid4().hex[:6]}"
        resp = client.post(ROLES, headers=h, json={
            "code": code, "name": "临时角色", "data_scope": "DEPT",
            "perms": ["dashboard.view", "no.such.perm"],
        })
        assert resp.status_code == 200, resp.text
        role = resp.json()
        assert role["builtin"] is False
        assert role["data_scope"] == "DEPT"
        assert role["perms"] == ["dashboard.view"]      # 未知权限点被忽略
        try:
            updated = client.put(f"{ROLES}/{role['id']}", headers=h,
                                 json={"name": "临时角色改", "data_scope": "ALL"}).json()
            assert updated["name"] == "临时角色改"
            assert updated["data_scope"] == "ALL"

            replaced = client.put(f"{ROLES}/{role['id']}/permissions", headers=h,
                                  json={"perms": ["contract.view", "purchase.order.view"]}).json()
            assert sorted(replaced["perms"]) == ["contract.view", "purchase.order.view"]
        finally:
            assert client.delete(f"{ROLES}/{role['id']}", headers=h).status_code == 200

    def test_duplicate_code_rejected(self, client, h):
        resp = client.post(ROLES, headers=h, json={"code": "buyer", "name": "重复编码"})
        assert resp.status_code == 422
        assert "已存在" in resp.json()["detail"]

    def test_invalid_code_and_scope_rejected(self, client, h):
        assert client.post(ROLES, headers=h,
                           json={"code": "含中文", "name": "x"}).status_code == 422
        resp = client.post(ROLES, headers=h,
                           json={"code": f"ok{uuid.uuid4().hex[:4]}", "name": "x",
                                 "data_scope": "EVERYTHING"})
        assert resp.status_code == 422
        assert "数据范围" in resp.json()["detail"]

    def test_builtin_role_cannot_be_deleted(self, client, h):
        role = _role_by_code(client, h, "keeper")
        resp = client.delete(f"{ROLES}/{role['id']}", headers=h)
        assert resp.status_code == 422
        assert "内置角色" in resp.json()["detail"]

    def test_role_with_users_cannot_be_deleted(self, client, h):
        code = f"tmp_{uuid.uuid4().hex[:6]}"
        role = client.post(ROLES, headers=h, json={"code": code, "name": "占用角色"}).json()
        uname = f"u_{uuid.uuid4().hex[:6]}"
        created = client.post(USERS, headers=h, json={
            "username": uname, "real_name": "绑定用户", "password": "init12345",
            "role_ids": [role["id"]]}).json()
        try:
            resp = client.delete(f"{ROLES}/{role['id']}", headers=h)
            assert resp.status_code == 422
            assert "仍有账号" in resp.json()["detail"]
        finally:
            _drop(created["id"])
            assert client.delete(f"{ROLES}/{role['id']}", headers=h).status_code == 200

    def test_sysadmin_role_cannot_be_disabled(self, client, h):
        role = _role_by_code(client, h, "sysadmin")
        resp = client.put(f"{ROLES}/{role['id']}/status", headers=h, json={"enabled": False})
        assert resp.status_code == 422
        assert "不可停用" in resp.json()["detail"]

    def test_sysadmin_perms_always_keep_system_module(self, client, h):
        """防自锁：摘除系统管理员权限时，system.* 始终保留。"""
        role = _role_by_code(client, h, "sysadmin")
        try:
            resp = client.put(f"{ROLES}/{role['id']}/permissions", headers=h,
                              json={"perms": ["contract.view"]})
            assert resp.status_code == 200
            perms = set(resp.json()["perms"])
            assert "contract.view" in perms
            assert {c for c in perms if c.startswith("system.")} == \
                   {c for c in PERM_CODES if c.startswith("system.")}
        finally:
            client.put(f"{ROLES}/{role['id']}/permissions", headers=h,
                       json={"perms": list(PERM_CODES)})
            restored = _role_by_code(client, h, "sysadmin")
            assert set(restored["perms"]) == PERM_CODES


# ===================== 账号管理 =====================

class TestUserApi:
    def test_create_user_with_role(self, client, h):
        buyer = _role_by_code(client, h, "buyer")
        username = f"u_{uuid.uuid4().hex[:6]}"
        resp = client.post(USERS, headers=h, json={
            "username": username, "real_name": "采购小王", "password": "init12345",
            "role_ids": [buyer["id"]]})
        assert resp.status_code == 200, resp.text
        created = resp.json()
        try:
            assert created["status"] == "enabled"
            assert created["must_change_pwd"] is True     # AC-V2-08 首登强制改密
            assert created["role_names"] == ["采购员"]

            token = _login(client, created["id"])
            me = client.get("/api/auth/me",
                            headers={"Authorization": f"Bearer {token}"}).json()
            assert me["user"]["must_change_pwd"] is True
            # 采购员：可提交不可审核（权限矩阵关键约束）
            assert "purchase.order.create" in me["perms"]
            assert "purchase.order.approve" not in me["perms"]
            assert "master.user.edit" not in me["perms"]
        finally:
            _drop(created["id"])

    def test_duplicate_username_rejected(self, client, h):
        resp = client.post(USERS, headers=h, json={
            "username": ADMIN_USERNAME, "real_name": "重名", "password": "init12345"})
        assert resp.status_code == 422
        assert "登录名已存在" in resp.json()["detail"]

    def test_weak_password_rejected(self, client, h):
        username = f"u_{uuid.uuid4().hex[:6]}"
        resp = client.post(USERS, headers=h, json={
            "username": username, "real_name": "弱密码", "password": "abcdefgh"})
        assert resp.status_code == 422
        assert "字母与数字" in resp.json()["detail"]
        resp = client.post(USERS, headers=h, json={
            "username": username, "real_name": "弱密码", "password": "a1b2"})
        assert resp.status_code == 422
        assert "长度" in resp.json()["detail"]

    def test_invalid_role_rejected(self, client, h):
        resp = client.post(USERS, headers=h, json={
            "username": f"u_{uuid.uuid4().hex[:6]}", "real_name": "坏角色",
            "password": "init12345", "role_ids": [999999]})
        assert resp.status_code == 422
        assert "无效的角色" in resp.json()["detail"]

    def test_list_and_filter(self, client, h):
        uid = _mk_account(role_codes=("keeper",))
        try:
            with SessionLocal() as db:
                username = db.get(User, uid).username
            data = client.get(USERS, headers=h, params={"keyword": username}).json()
            assert data["total"] == 1
            assert data["items"][0]["username"] == username

            only_disabled = client.get(USERS, headers=h,
                                       params={"status": "disabled", "keyword": username}).json()
            assert only_disabled["total"] == 0
        finally:
            _drop(uid)

    def test_update_real_name_and_roles(self, client, h):
        uid = _mk_account(role_codes=("viewer",))
        keeper = _role_by_code(client, h, "keeper")
        try:
            resp = client.put(f"{USERS}/{uid}", headers=h,
                              json={"real_name": "改名后", "role_ids": [keeper["id"]]})
            assert resp.status_code == 200
            assert resp.json()["real_name"] == "改名后"
            assert resp.json()["role_names"] == ["仓管员"]
        finally:
            _drop(uid)

    def test_username_is_immutable(self, client, h):
        uid = _mk_account(role_codes=("viewer",))
        try:
            with SessionLocal() as db:
                before = db.get(User, uid).username
            resp = client.put(f"{USERS}/{uid}", headers=h,
                              json={"username": "hacked_name", "real_name": "试图改名"})
            assert resp.status_code == 200
            assert resp.json()["username"] == before
        finally:
            _drop(uid)

    def test_cannot_disable_self(self, client, h):
        me = client.get("/api/auth/me", headers=h).json()["user"]
        resp = client.put(f"{USERS}/{me['id']}/status", headers=h, json={"enabled": False})
        assert resp.status_code == 422
        assert "当前登录账号" in resp.json()["detail"]

    def test_cannot_disable_last_superadmin(self, client, h):
        """由非超管（但持有全部权限）操作，验证"最后一个超管"保护。"""
        admin_id = client.get("/api/auth/me", headers=h).json()["user"]["id"]
        uid = _mk_account(role_codes=("sysadmin",))
        try:
            token = _login(client, uid)
            headers = {"Authorization": f"Bearer {token}"}
            resp = client.put(f"{USERS}/{admin_id}/status", headers=headers,
                              json={"enabled": False})
            assert resp.status_code == 422
            assert "最后一个超级管理员" in resp.json()["detail"]
        finally:
            _drop(uid)

    def test_disable_and_enable_account(self, client, h):
        uid = _mk_account(role_codes=("buyer",))
        try:
            assert client.put(f"{USERS}/{uid}/status", headers=h,
                              json={"enabled": False}).json()["status"] == "disabled"
            # 停用后不可登录
            assert _login(client, uid) is None
            assert client.put(f"{USERS}/{uid}/status", headers=h,
                              json={"enabled": True}).json()["status"] == "enabled"
            assert _login(client, uid) is not None
        finally:
            _drop(uid)

    def test_reset_password_forces_change(self, client, h):
        uid = _mk_account(role_codes=("buyer",))
        try:
            resp = client.post(f"{USERS}/{uid}/reset-password", headers=h,
                               json={"new_password": "reset12345"})
            assert resp.status_code == 200
            with SessionLocal() as db:
                assert db.get(User, uid).must_change_pwd is True
            assert _login(client, uid, "reset12345") is not None
            assert _login(client, uid, "init12345") is None

            weak = client.post(f"{USERS}/{uid}/reset-password", headers=h,
                               json={"new_password": "abcdefgh"})
            assert weak.status_code == 422
        finally:
            _drop(uid)


# ===================== 权限拦截 =====================

class TestSystemPermissions:
    def test_buyer_denied_user_admin(self, client):
        uid = _mk_account(role_codes=("buyer",))
        try:
            token = _login(client, uid)
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get(USERS, headers=headers).status_code == 403
            assert client.post(USERS, headers=headers,
                               json={"username": "x", "real_name": "y",
                                     "password": "init12345"}).status_code == 403
        finally:
            _drop(uid)

    def test_keeper_denied_role_admin(self, client):
        uid = _mk_account(role_codes=("keeper",))
        try:
            token = _login(client, uid)
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get(ROLES, headers=headers).status_code == 403
        finally:
            _drop(uid)

    def test_sysadmin_role_account_has_full_access(self, client):
        uid = _mk_account(role_codes=("sysadmin",))
        try:
            token = _login(client, uid)
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get(USERS, headers=headers).status_code == 200
            assert client.get(ROLES, headers=headers).status_code == 200
            perms = client.get("/api/auth/me", headers=headers).json()["perms"]
            assert set(perms) == PERM_CODES
        finally:
            _drop(uid)
