"""T-V2-06 合同模块权限与数据范围测试。

对应验收场景：
- AC-V2-03 菜单与按钮权限（越权返回 403）
- AC-V2-04 数据范围-本人
- AC-V2-05 数据范围-本部门及下级
- AC-V2-37 变更历史带操作人
- AC-V2-41 后端强制校验

测试自建组织/账号/合同，并在 fixture 结束时物理清理（开发库不残留）。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models import ChangeLog, Contract, ContractItem, contract_tag
from app.models_auth import OperationLog, OrgUnit, Role, User
from app.security import hash_password

API = "/api/contracts"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_h(client):
    resp = client.post("/api/auth/login",
                       json={"username": ADMIN_USERNAME, "password": ADMIN_INIT_PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


class Env:
    """一次性测试环境：组织 + 账号 + 合同，负责创建与清理。"""

    def __init__(self, client, admin_h):
        self.client = client
        self.admin_h = admin_h
        self.org_ids: list[int] = []
        self.user_ids: list[int] = []
        self.contract_ids: list[int] = []

    # ---- 构造 ----
    def org(self, name: str, parent_id: int | None = None, unit_type: str = "部门") -> dict:
        payload = {"name": name, "unit_type": unit_type}
        if parent_id:
            payload["parent_id"] = parent_id
        resp = self.client.post("/api/system/org-units", headers=self.admin_h, json=payload)
        assert resp.status_code == 200, resp.text
        node = resp.json()
        self.org_ids.append(node["id"])
        return node

    def user(self, role_code: str, org_id: int | None = None) -> int:
        username = f"t_{uuid.uuid4().hex[:8]}"
        with SessionLocal() as db:
            role = db.query(Role).filter(Role.code == role_code).one()
            user = User(username=username, real_name=f"测试-{role_code}", org_id=org_id,
                        password_hash=hash_password("init12345"), status="enabled")
            user.roles.append(role)
            db.add(user)
            db.commit()
            uid = user.id
        self.user_ids.append(uid)
        return uid

    def headers(self, uid: int) -> dict:
        with SessionLocal() as db:
            username = db.get(User, uid).username
        resp = self.client.post("/api/auth/login",
                                json={"username": username, "password": "init12345"})
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['token']}"}

    def contract(self, headers: dict, name: str | None = None, amount: float = 1000) -> dict:
        resp = self.client.post(API, headers=headers, json={
            "name": name or f"测试合同_{uuid.uuid4().hex[:6]}",
            "type": "PUR", "subject_code": "ZC", "amount": amount,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        self.contract_ids.append(data["id"])
        return data

    # ---- 清理 ----
    def cleanup(self) -> None:
        with SessionLocal() as db:
            for cid in self.contract_ids:
                db.execute(contract_tag.delete().where(contract_tag.c.contract_id == cid))
                db.query(ChangeLog).filter(ChangeLog.contract_id == cid).delete()
                db.query(ContractItem).filter(ContractItem.contract_id == cid).delete()
                db.query(Contract).filter(Contract.id == cid).delete()
            for uid in self.user_ids:
                db.query(OperationLog).filter(OperationLog.user_id == uid).delete()
                db.query(User).filter(User.id == uid).delete()
            db.commit()
            for oid in sorted(self.org_ids, reverse=True):
                node = db.get(OrgUnit, oid)
                if node is not None:
                    db.delete(node)
            db.commit()
        self.org_ids, self.user_ids, self.contract_ids = [], [], []


@pytest.fixture()
def env(client, admin_h):
    instance = Env(client, admin_h)
    try:
        yield instance
    finally:
        instance.cleanup()


# ===================== 按钮权限 =====================

class TestContractPermissionGate:
    def test_requires_login(self, client):
        assert client.get(API).status_code == 401
        assert client.post(API, json={"name": "x"}).status_code == 401

    def test_keeper_can_view_but_not_create(self, client, env):
        uid = env.user("keeper")
        headers = env.headers(uid)
        assert client.get(API, headers=headers).status_code == 200      # 矩阵：仓管员可查看合同
        resp = client.post(API, headers=headers,
                           json={"name": "越权合同", "type": "PUR", "subject_code": "ZC"})
        assert resp.status_code == 403
        assert "contract.create" in resp.json()["detail"]

    def test_buyer_can_create_but_not_delete(self, client, env):
        uid = env.user("buyer")
        headers = env.headers(uid)
        created = env.contract(headers, name=f"采购员合同_{uuid.uuid4().hex[:6]}")
        assert created["created_by"] == uid
        resp = client.delete(f"{API}/{created['id']}", headers=headers, params={"reason": "测试"})
        assert resp.status_code == 403
        assert "contract.delete" in resp.json()["detail"]

    def test_finance_is_readonly(self, client, env):
        uid = env.user("finance")
        headers = env.headers(uid)
        assert client.get(API, headers=headers).status_code == 200
        resp = client.post(API, headers=headers,
                           json={"name": "财务越权", "type": "PUR", "subject_code": "ZC"})
        assert resp.status_code == 403

    def test_admin_can_delete_own_created(self, client, env):
        created = env.contract(env.admin_h, name=f"管理员合同_{uuid.uuid4().hex[:6]}")
        resp = client.delete(f"{API}/{created['id']}", headers=env.admin_h,
                             params={"reason": "测试停用"})
        assert resp.status_code == 200
        # 已软删除：默认列表不可见
        data = client.get(API, headers=env.admin_h,
                          params={"keyword": created["name"]}).json()
        assert data["total"] == 0


# ===================== 数据范围 =====================

class TestContractDataScope:
    def test_self_scope_isolates_peers(self, client, env):
        dept_a = env.org(f"甲部_{uuid.uuid4().hex[:4]}")
        dept_b = env.org(f"乙部_{uuid.uuid4().hex[:4]}")
        user_a = env.user("buyer", dept_a["id"])
        user_b = env.user("buyer", dept_b["id"])

        marker = f"甲合同_{uuid.uuid4().hex[:6]}"
        env.contract(env.headers(user_a), name=marker)

        seen_a = client.get(API, headers=env.headers(user_a), params={"keyword": marker}).json()
        assert seen_a["total"] == 1
        seen_b = client.get(API, headers=env.headers(user_b), params={"keyword": marker}).json()
        assert seen_b["total"] == 0, "本人范围不应看到他人创建的合同"

    def test_dept_sub_scope_sees_subordinate(self, client, env):
        head = env.org(f"采购中心_{uuid.uuid4().hex[:4]}", unit_type="部门")
        sub = env.org("采购一组", parent_id=head["id"], unit_type="岗位")
        manager = env.user("purchase_manager", head["id"])     # DEPT_SUB
        staff = env.user("buyer", sub["id"])                   # SELF

        marker = f"下级合同_{uuid.uuid4().hex[:6]}"
        env.contract(env.headers(staff), name=marker)

        seen = client.get(API, headers=env.headers(manager), params={"keyword": marker}).json()
        assert seen["total"] == 1, "本部门及下级范围应看到下级部门创建的合同"

    def test_dept_scope_does_not_see_other_branch(self, client, env):
        branch = env.org(f"销售中心_{uuid.uuid4().hex[:4]}")
        other = env.org(f"外部部门_{uuid.uuid4().hex[:4]}")
        manager = env.user("purchase_manager", branch["id"])
        outsider = env.user("buyer", other["id"])

        marker = f"他部合同_{uuid.uuid4().hex[:6]}"
        env.contract(env.headers(outsider), name=marker)

        seen = client.get(API, headers=env.headers(manager), params={"keyword": marker}).json()
        assert seen["total"] == 0, "本部门及下级范围不应看到其他分支的合同"

    def test_all_scope_sees_everything(self, client, env):
        dept = env.org(f"任意部_{uuid.uuid4().hex[:4]}")
        staff = env.user("buyer", dept["id"])
        marker = f"跨部门合同_{uuid.uuid4().hex[:6]}"
        env.contract(env.headers(staff), name=marker)

        finance = env.user("finance")                 # data_scope = ALL
        seen = client.get(API, headers=env.headers(finance), params={"keyword": marker}).json()
        assert seen["total"] == 1

    def test_superadmin_bypasses_scope(self, client, env):
        dept = env.org(f"深部_{uuid.uuid4().hex[:4]}")
        staff = env.user("buyer", dept["id"])
        marker = f"深层合同_{uuid.uuid4().hex[:6]}"
        env.contract(env.headers(staff), name=marker)
        seen = client.get(API, headers=env.admin_h, params={"keyword": marker}).json()
        assert seen["total"] == 1


# ===================== 变更历史操作人（AC-V2-37） =====================

class TestChangeLogOperator:
    def test_changelog_records_operator(self, client, env):
        uid = env.user("buyer")
        headers = env.headers(uid)
        created = env.contract(headers, name=f"审计合同_{uuid.uuid4().hex[:6]}", amount=1000)

        # 修改金额 → 产生变更历史
        assert client.put(f"{API}/{created['id']}", headers=headers,
                          json={"amount": 2500}).status_code == 200

        # 用超管读取（buyer 无 contract.log.view）
        logs = client.get(f"{API}/{created['id']}/logs", headers=env.admin_h).json()
        assert logs, "应有变更历史"
        amount_log = next(lg for lg in logs if lg["field_name"] == "amount")
        # 注：V1.0 的 _log 直接 str(Decimal)，旧值带两位小数（1000.00）、新值不带（2500），
        # 故此处按数值比较；显示格式的统一留待 T-V2-12「变更历史」页面处理。
        assert float(amount_log["old_value"]) == 1000.00
        assert float(amount_log["new_value"]) == 2500.00
        assert amount_log["operator_id"] == uid
        assert amount_log["operator_name"] == "测试-buyer"

    def test_creation_is_logged_with_operator(self, client, env):
        uid = env.user("buyer")
        headers = env.headers(uid)
        created = env.contract(headers, name=f"新建审计_{uuid.uuid4().hex[:6]}")
        logs = client.get(f"{API}/{created['id']}/logs", headers=env.admin_h).json()
        summary = [lg for lg in logs if lg["field_name"] == "_summary"]
        assert summary and summary[0]["operator_id"] == uid

    def test_log_requires_perm(self, client, env):
        uid = env.user("buyer")
        headers = env.headers(uid)
        created = env.contract(headers, name=f"日志权限_{uuid.uuid4().hex[:6]}")
        # 采购员无 contract.log.view
        resp = client.get(f"{API}/{created['id']}/logs", headers=headers)
        assert resp.status_code == 403
        assert "contract.log.view" in resp.json()["detail"]


# ===================== 档案字段（T-V2-13 档案化） =====================

class TestPartyFields:
    def test_contract_accepts_party_ids(self, client, env):
        """采购合同可绑定供应商档案 id（T-V2-13）。

        V2.0 起 `supplier_id`/`customer_id` 必须是**真实存在的档案**（AC-V2-33），
        不再接受任意数字（脏引用会被 422 拒绝）。
        """
        uid = env.user("buyer")
        headers = env.headers(uid)
        created = client.post("/api/master/suppliers", headers=env.admin_h,
                              json={"name": f"权限测试供应商_{uuid.uuid4().hex[:6]}"})
        assert created.status_code == 200, created.text
        supplier_id = created.json()["id"]

        try:
            contract = env.contract(headers, name=f"档案合同_{uuid.uuid4().hex[:6]}")
            assert contract["customer_id"] is None
            assert contract["supplier_id"] is None

            resp = client.put(f"{API}/{contract['id']}", headers=headers,
                              json={"supplier_id": supplier_id, "customer_id": None})
            assert resp.status_code == 200, resp.text
            assert resp.json()["supplier_id"] == supplier_id
            assert resp.json()["supplier_name"] == created.json()["name"]

            logs = client.get(f"{API}/{contract['id']}/logs", headers=env.admin_h).json()
            assert any(lg["field_name"] == "supplier_id" for lg in logs)

            # 脏引用被拒绝
            bad = client.put(f"{API}/{contract['id']}", headers=headers,
                             json={"supplier_id": 99999999})
            assert bad.status_code == 422
            assert "供应商档案不存在" in bad.json()["detail"]
        finally:
            with SessionLocal() as db:
                from app.models_master import Supplier
                db.query(Supplier).filter(Supplier.id == supplier_id).delete()
                db.commit()
