"""T-V2-03 组织架构测试：树维护、路径物化、删除校验、防环、权限拦截。

对应验收场景：AC-V2-07（组织节点删除校验）、AC-V2-03/41（权限后端强制校验）。

测试在开发库中创建临时组织树并在结束时清理（fixture finally 保证）。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_auth import OperationLog, Role, User
from app.security import hash_password

API = "/api/system/org-units"


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


# ---------------- 测试数据辅助 ----------------

def _create(client, h, name, *, parent_id=None, unit_type="部门"):
    payload = {"name": name, "unit_type": unit_type}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    return client.post(API, headers=h, json=payload)


def _delete_tree(client, h, unit_id: int) -> None:
    """自底向上清理：删除要求无子节点，故先递归清理子节点。"""
    data = client.get(API, headers=h).json()
    for item in data.get("items", []):
        if item["parent_id"] == unit_id:
            _delete_tree(client, h, item["id"])
    client.delete(f"{API}/{unit_id}", headers=h)


@pytest.fixture()
def root(client, h):
    resp = _create(client, h, f"测试公司_{uuid.uuid4().hex[:6]}", unit_type="公司")
    assert resp.status_code == 200, resp.text
    node = resp.json()
    try:
        yield node
    finally:
        _delete_tree(client, h, node["id"])


def _mk_user_with_role(role_code: str) -> int:
    username = f"perm_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        role = db.query(Role).filter(Role.code == role_code).one()
        user = User(username=username, real_name="权限测试账号",
                    password_hash=hash_password("init12345"), status="enabled")
        user.roles.append(role)
        db.add(user)
        db.commit()
        return user.id


def _drop_user(uid: int) -> None:
    with SessionLocal() as db:
        db.query(OperationLog).filter(OperationLog.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def _token_of(client, uid: int) -> str:
    with SessionLocal() as db:
        username = db.get(User, uid).username
    return client.post("/api/auth/login",
                       json={"username": username, "password": "init12345"}).json()["token"]


# ===================== 树维护与路径 =====================

class TestOrgTree:
    def test_create_three_levels_with_materialized_path(self, client, h, root):
        assert root["level"] == 1
        assert root["path"] == f"/{root['id']}/"

        dept = _create(client, h, "采购部", parent_id=root["id"]).json()
        assert dept["parent_id"] == root["id"]
        assert dept["level"] == 2
        assert dept["path"] == f"{root['path']}{dept['id']}/"

        group = _create(client, h, "采购一组", parent_id=dept["id"], unit_type="岗位").json()
        assert group["level"] == 3
        assert group["path"] == f"{dept['path']}{group['id']}/"

    def test_tree_payload_is_nested(self, client, h, root):
        dept = _create(client, h, f"销售部_{uuid.uuid4().hex[:4]}", parent_id=root["id"]).json()
        _create(client, h, "销售一组", parent_id=dept["id"], unit_type="岗位")

        tree = client.get(API, headers=h).json()["tree"]
        node = _find(tree, root["id"])
        assert node is not None
        child = _find(node["children"], dept["id"])
        assert child is not None
        assert child["children"], "子节点应挂在部门下"

    def test_keyword_filter_keeps_matched_nodes(self, client, h, root):
        marker = uuid.uuid4().hex[:6]
        _create(client, h, f"市场部_{marker}", parent_id=root["id"])
        data = client.get(API, headers=h, params={"keyword": marker}).json()
        assert data["total"] >= 1
        assert all(marker in i["name"] for i in data["items"])


def _find(nodes, node_id):
    for n in nodes:
        if n["id"] == node_id:
            return n
        found = _find(n.get("children") or [], node_id)
        if found:
            return found
    return None


# ===================== 校验规则 =====================

class TestOrgValidation:
    def test_reject_empty_name(self, client, h, root):
        resp = _create(client, h, "   ", parent_id=root["id"])
        assert resp.status_code == 422
        assert "名称" in resp.json()["detail"]

    def test_reject_duplicate_sibling_name(self, client, h, root):
        name = f"重名部_{uuid.uuid4().hex[:4]}"
        assert _create(client, h, name, parent_id=root["id"]).status_code == 200
        resp = _create(client, h, name, parent_id=root["id"])
        assert resp.status_code == 422
        assert "同名" in resp.json()["detail"]

    def test_same_name_allowed_under_different_parents(self, client, h, root):
        name = f"综合部_{uuid.uuid4().hex[:4]}"
        a = _create(client, h, f"甲_{uuid.uuid4().hex[:4]}", parent_id=root["id"]).json()
        b = _create(client, h, f"乙_{uuid.uuid4().hex[:4]}", parent_id=root["id"]).json()
        assert _create(client, h, name, parent_id=a["id"]).status_code == 200
        assert _create(client, h, name, parent_id=b["id"]).status_code == 200

    def test_reject_invalid_unit_type(self, client, h, root):
        resp = client.post(API, headers=h,
                           json={"name": "非法类型", "unit_type": "分公司", "parent_id": root["id"]})
        assert resp.status_code == 422
        assert "节点类型" in resp.json()["detail"]

    def test_reject_missing_parent(self, client, h):
        resp = _create(client, h, "孤儿节点", parent_id=99999999)
        assert resp.status_code == 422
        assert "上级节点不存在" in resp.json()["detail"]

    def test_max_level_enforced(self, client, h, root):
        """最多 5 级：第 6 级应被拒绝。"""
        parent_id = root["id"]
        for i in range(2, 6):                      # 建到第 5 级
            r = _create(client, h, f"L{i}_{uuid.uuid4().hex[:4]}", parent_id=parent_id)
            assert r.status_code == 200, r.text
            parent_id = r.json()["id"]
        resp = _create(client, h, "L6_超限", parent_id=parent_id)
        assert resp.status_code == 422
        assert "最多 5 级" in resp.json()["detail"]


# ===================== 删除与移动 =====================

class TestOrgGuards:
    def test_cannot_delete_node_with_children(self, client, h, root):
        dept = _create(client, h, f"有子部_{uuid.uuid4().hex[:4]}", parent_id=root["id"]).json()
        _create(client, h, "子节点", parent_id=dept["id"])
        resp = client.delete(f"{API}/{dept['id']}", headers=h)
        assert resp.status_code == 422
        assert "子节点" in resp.json()["detail"]

    def test_cannot_delete_node_with_accounts(self, client, h, root):
        dept = _create(client, h, f"有账号部_{uuid.uuid4().hex[:4]}", parent_id=root["id"]).json()
        uid = _mk_user_with_role("buyer")
        try:
            with SessionLocal() as db:
                db.query(User).filter(User.id == uid).update({"org_id": dept["id"]})
                db.commit()
            resp = client.delete(f"{API}/{dept['id']}", headers=h)
            assert resp.status_code == 422
            assert "账号" in resp.json()["detail"]
        finally:
            _drop_user(uid)

    def test_cannot_move_node_into_own_descendant(self, client, h, root):
        dept = _create(client, h, f"父部_{uuid.uuid4().hex[:4]}", parent_id=root["id"]).json()
        child = _create(client, h, "子部", parent_id=dept["id"]).json()
        resp = client.put(f"{API}/{dept['id']}", headers=h, json={"parent_id": child["id"]})
        assert resp.status_code == 422
        assert "自己的下级" in resp.json()["detail"]

    def test_move_recalculates_descendant_paths(self, client, h, root):
        a = _create(client, h, f"甲部_{uuid.uuid4().hex[:4]}", parent_id=root["id"]).json()
        b = _create(client, h, f"乙部_{uuid.uuid4().hex[:4]}", parent_id=root["id"]).json()
        dept = _create(client, h, "搬迁部", parent_id=a["id"]).json()
        sub = _create(client, h, "随迁组", parent_id=dept["id"], unit_type="岗位").json()
        assert sub["path"].startswith(dept["path"])

        moved = client.put(f"{API}/{dept['id']}", headers=h,
                           json={"parent_id": b["id"]}).json()
        assert moved["parent_id"] == b["id"]
        assert moved["level"] == 3
        assert moved["path"] == f"{b['path']}{dept['id']}/"

        sub_after = client.get(f"{API}/{sub['id']}", headers=h).json()
        assert sub_after["path"] == f"{moved['path']}{sub['id']}/"
        assert sub_after["level"] == 4

    def test_disable_keeps_node(self, client, h, root):
        dept = _create(client, h, f"待停用部_{uuid.uuid4().hex[:4]}", parent_id=root["id"]).json()
        resp = client.put(f"{API}/{dept['id']}/status", headers=h, json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        # 不返回停用节点时被过滤
        data = client.get(API, headers=h, params={"include_disabled": False}).json()
        assert all(i["id"] != dept["id"] for i in data["items"])


# ===================== 权限（AC-V2-03 / AC-V2-41） =====================

class TestOrgPermissions:
    def test_keeper_denied_org_view(self, client):
        uid = _mk_user_with_role("keeper")
        try:
            token = _token_of(client, uid)
            resp = client.get(API, headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 403
            assert "master.org.view" in resp.json()["detail"]
        finally:
            _drop_user(uid)

    def test_buyer_denied_org_edit(self, client):
        uid = _mk_user_with_role("buyer")
        try:
            token = _token_of(client, uid)
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get(API, headers=headers).status_code == 403
            resp = client.post(API, headers=headers, json={"name": "越权节点"})
            assert resp.status_code == 403
            assert "master.org.edit" in resp.json()["detail"]
        finally:
            _drop_user(uid)

    def test_non_superadmin_with_sysadmin_role_is_allowed(self, client):
        """权限来自角色而非超管标记（超管只是快捷方式）。"""
        uid = _mk_user_with_role("sysadmin")
        try:
            token = _token_of(client, uid)
            headers = {"Authorization": f"Bearer {token}"}
            resp = client.get(API, headers=headers)
            assert resp.status_code == 200
            with SessionLocal() as db:
                assert db.get(User, uid).is_superadmin is False
        finally:
            _drop_user(uid)

    def test_unauthenticated_denied(self, client):
        assert client.get(API).status_code == 401
        assert client.post(API, json={"name": "x"}).status_code == 401
