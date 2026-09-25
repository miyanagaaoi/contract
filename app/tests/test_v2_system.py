"""T-V2-12 系统管理整合测试：系统参数 / 编号规则 / 操作日志 / 变更历史 / 备份 / 关于。

对应验收场景：
- AC-V2-38 系统管理整合（各子页签接口可用、原 /settings 保留）
- AC-V2-39 手动备份下载（生成 zip + 写操作日志 + 路径穿越防护）
- AC-V2-36 操作日志按动作/时间筛选
- AC-V2-37 变更历史带操作人（V1.0 历史为空）

测试自建数据并在结束时清理（含生成的备份文件）。
"""
from __future__ import annotations

import uuid
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.dicts import DEFAULT_NUMBER_RULES, DEFAULT_SYS_PARAMS
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models import ChangeLog, Contract, ContractItem, contract_tag
from app.models_auth import OperationLog, Role, User
from app.models_master import Customer
from app.security import hash_password

API = "/api/system"


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
def restore_number_rules(client, h):
    """编号规则是**全局配置**：本模块用例会临时改前缀，结束后必须还原（防污染开发库）。"""
    before = client.get(f"{API}/number-rules", headers=h).json()["rules"]
    yield
    client.put(f"{API}/number-rules", headers=h, json={"rules": before})


def _mk_user_with_role(role_code: str) -> int:
    username = f"s_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        role = db.query(Role).filter(Role.code == role_code).one()
        user = User(username=username, real_name="系统管理测试账号",
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


# ===================== 系统参数（AC-V2-38） =====================

class TestSysParams:
    def test_get_params_with_meta(self, client, h):
        data = client.get(f"{API}/params", headers=h).json()
        assert set(DEFAULT_SYS_PARAMS) <= set(data["params"])
        keys = {m["key"] for m in data["meta"]}
        assert keys == set(DEFAULT_SYS_PARAMS)
        assert all(m["label"] for m in data["meta"])

    def test_update_params_and_restore(self, client, h):
        before = client.get(f"{API}/params", headers=h).json()["params"]
        try:
            resp = client.put(f"{API}/params", headers=h,
                              json={"params": {"warranty_window_days": 45,
                                               "allow_negative_stock": True}})
            assert resp.status_code == 200, resp.text
            assert resp.json()["params"]["warranty_window_days"] == 45
            assert resp.json()["params"]["allow_negative_stock"] is True
        finally:
            client.put(f"{API}/params", headers=h, json={"params": {
                "warranty_window_days": before["warranty_window_days"],
                "allow_negative_stock": before["allow_negative_stock"],
            }})

    def test_reject_invalid_param_value(self, client, h):
        resp = client.put(f"{API}/params", headers=h,
                          json={"params": {"warranty_window_days": "abc"}})
        assert resp.status_code == 422
        assert "非法" in resp.json()["detail"]

    def test_reject_too_short_password_length(self, client, h):
        resp = client.put(f"{API}/params", headers=h, json={"params": {"pwd_min_length": 3}})
        assert resp.status_code == 422
        assert "密码最小长度" in resp.json()["detail"]

    def test_unknown_keys_ignored(self, client, h):
        resp = client.put(f"{API}/params", headers=h,
                          json={"params": {"not_a_param": 1}})
        assert resp.status_code == 200
        assert "not_a_param" not in resp.json()["params"]


# ===================== 编号规则 =====================

class TestNumberRules:
    def test_list_with_previews(self, client, h):
        data = client.get(f"{API}/number-rules", headers=h).json()
        assert set(DEFAULT_NUMBER_RULES) <= set(data["rules"])
        assert data["labels"]["customer"] == "客户编码"
        # 主数据编号已实现 → 有预览值；单据类（M2）尚未实现 → None
        assert (data["previews"]["customer"] or "").startswith(
            data["rules"]["customer"]["prefix"])
        assert data["previews"]["purchase_order"] is None

    def test_update_prefix_and_seq_len(self, client, h):
        before = client.get(f"{API}/number-rules", headers=h).json()["rules"]
        try:
            resp = client.put(f"{API}/number-rules", headers=h,
                              json={"rules": {"customer": {"prefix": "KH", "seq_len": 6}}})
            assert resp.status_code == 200, resp.text
            assert resp.json()["rules"]["customer"]["prefix"] == "KH"
            assert resp.json()["rules"]["customer"]["seq_len"] == 6
        finally:
            client.put(f"{API}/number-rules", headers=h,
                       json={"rules": {"customer": before["customer"]}})

    def test_reject_invalid_prefix_and_length(self, client, h):
        resp = client.put(f"{API}/number-rules", headers=h,
                          json={"rules": {"customer": {"prefix": "中文"}}})
        assert resp.status_code == 422
        assert "前缀" in resp.json()["detail"]

        resp = client.put(f"{API}/number-rules", headers=h,
                          json={"rules": {"customer": {"seq_len": 99}}})
        assert resp.status_code == 422
        assert "序号长度" in resp.json()["detail"]

    def test_changed_prefix_used_by_new_code(self, client, h):
        """改前缀后新档案编码使用新规则（规则真实生效）。"""
        before = client.get(f"{API}/number-rules", headers=h).json()["rules"]["customer"]
        customer_id = None
        try:
            client.put(f"{API}/number-rules", headers=h,
                       json={"rules": {"customer": {"prefix": "TST"}}})
            resp = client.post("/api/master/customers", headers=h,
                               json={"name": f"编号规则客户_{uuid.uuid4().hex[:6]}"})
            assert resp.status_code == 200, resp.text
            customer_id = resp.json()["id"]
            assert resp.json()["code"].startswith("TST")
        finally:
            client.put(f"{API}/number-rules", headers=h,
                       json={"rules": {"customer": before}})
            if customer_id:
                client.delete(f"/api/master/customers/{customer_id}", headers=h)


# ===================== 操作日志（AC-V2-36） =====================

class TestOperationLogs:
    def test_login_only_denied_for_plain_role(self, client):
        uid = _mk_user_with_role("buyer")
        try:
            headers = {"Authorization": f"Bearer {_token_of(client, uid)}"}
            resp = client.get(f"{API}/logs", headers=headers)
            assert resp.status_code == 403
            assert "system.log.view" in resp.json()["detail"]
        finally:
            _drop_user(uid)

    def test_unauthenticated_denied(self, client):
        assert client.get(f"{API}/logs").status_code == 401

    def test_filter_by_action_and_time_range(self, client, h):
        # 制造一条 create 日志
        name = f"日志客户_{uuid.uuid4().hex[:6]}"
        created = client.post("/api/master/customers", headers=h, json={"name": name})
        assert created.status_code == 200
        cid = created.json()["id"]
        try:
            data = client.get(f"{API}/logs", headers=h,
                              params={"module": "master", "action": "create",
                                      "keyword": name, "page_size": 50}).json()
            assert data["total"] >= 1
            row = data["items"][0]
            assert row["action"] == "create"
            assert row["module"] == "master"
            assert row["username"] == ADMIN_USERNAME
            assert row["created_at"]

            today = row["created_at"][:10]
            in_range = client.get(f"{API}/logs", headers=h,
                                  params={"action": "create", "date_from": today,
                                          "date_to": today}).json()
            assert in_range["total"] >= 1

            out_of_range = client.get(f"{API}/logs", headers=h,
                                      params={"action": "create", "date_from": "2000-01-01",
                                              "date_to": "2000-01-02"}).json()
            assert out_of_range["total"] == 0
        finally:
            client.delete(f"/api/master/customers/{cid}", headers=h)

    def test_reject_bad_date(self, client, h):
        resp = client.get(f"{API}/logs", headers=h, params={"date_from": "2026/01/01"})
        assert resp.status_code == 422
        assert "YYYY-MM-DD" in resp.json()["detail"]

    def test_filter_options_present(self, client, h):
        data = client.get(f"{API}/logs", headers=h).json()
        assert "login" in data["actions"]
        assert "master" in data["modules"]


# ===================== 变更历史（AC-V2-37） =====================

class TestChangeLogs:
    @pytest.fixture()
    def contract(self, client, h):
        resp = client.post("/api/contracts", headers=h, json={
            "name": f"变更历史合同_{uuid.uuid4().hex[:6]}", "type": "COO",
            "subject_code": "ZC", "amount": 10000})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        try:
            yield data
        finally:
            with SessionLocal() as db:
                db.execute(contract_tag.delete().where(contract_tag.c.contract_id == data["id"]))
                db.query(ChangeLog).filter(ChangeLog.contract_id == data["id"]).delete()
                db.query(ContractItem).filter(ContractItem.contract_id == data["id"]).delete()
                db.query(Contract).filter(Contract.id == data["id"]).delete()
                db.commit()

    def test_amount_change_records_operator(self, client, h, contract):
        resp = client.put(f"/api/contracts/{contract['id']}", headers=h,
                          json={"amount": 20000})
        assert resp.status_code == 200, resp.text

        data = client.get(f"{API}/changelogs", headers=h,
                          params={"keyword": contract["contract_no"], "page_size": 50}).json()
        rows = [r for r in data["items"] if r["field_name"] == "amount"]
        assert rows, "金额变更应写入变更历史"
        row = rows[0]
        assert "10000" in row["old_value"]
        assert "20000" in row["new_value"]
        assert row["operator_name"], "V2.0 变更历史必须带操作人"
        assert row["contract_no"] == contract["contract_no"]

    def test_filter_by_field_name(self, client, h, contract):
        client.put(f"/api/contracts/{contract['id']}", headers=h, json={"owner_name": "张三"})
        data = client.get(f"{API}/changelogs", headers=h,
                          params={"field_name": "owner_name",
                                  "keyword": contract["contract_no"]}).json()
        assert all(r["field_name"] == "owner_name" for r in data["items"])

    def test_requires_permission(self, client):
        uid = _mk_user_with_role("buyer")
        try:
            headers = {"Authorization": f"Bearer {_token_of(client, uid)}"}
            resp = client.get(f"{API}/changelogs", headers=headers)
            assert resp.status_code == 403
            assert "system.changelog.view" in resp.json()["detail"]
        finally:
            _drop_user(uid)


# ===================== 备份（AC-V2-39） =====================

class TestBackup:
    def test_create_list_download_delete(self, client, h):
        created = client.post(f"{API}/backup", headers=h)
        assert created.status_code == 200, created.text
        info = created.json()
        assert info["name"].startswith("ctms_backup_") and info["name"].endswith(".zip")
        assert info["size_bytes"] > 0

        try:
            listed = client.get(f"{API}/backup", headers=h).json()["items"]
            assert any(item["name"] == info["name"] for item in listed)

            downloaded = client.get(f"{API}/backup/{info['name']}", headers=h)
            assert downloaded.status_code == 200
            assert downloaded.headers["content-type"] in ("application/zip", "application/x-zip-compressed")
            with zipfile.ZipFile(BytesIO(downloaded.content)) as zf:
                names = zf.namelist()
                assert "ctms.db" in names, "备份应包含 SQLite 数据文件"
                assert "backup_info.txt" in names

            # 备份动作写入操作日志
            logs = client.get(f"{API}/logs", headers=h,
                              params={"module": "system", "action": "backup"}).json()
            assert any(r["object_no"] == info["name"] for r in logs["items"])
        finally:
            assert client.delete(f"{API}/backup/{info['name']}", headers=h).status_code == 200
        assert client.get(f"{API}/backup/{info['name']}", headers=h).status_code == 422

    def test_reject_path_traversal_name(self, client, h):
        for bad in ("../ctms.db", "..%2Fctms.db", "evil.zip", "ctms_backup_x.zip"):
            resp = client.get(f"{API}/backup/{bad}", headers=h)
            assert resp.status_code in (404, 422), bad

    def test_download_requires_permission(self, client):
        uid = _mk_user_with_role("buyer")
        try:
            headers = {"Authorization": f"Bearer {_token_of(client, uid)}"}
            assert client.get(f"{API}/backup", headers=headers).status_code == 403
            assert client.post(f"{API}/backup", headers=headers).status_code == 403
        finally:
            _drop_user(uid)


# ===================== 关于（AC-V2-38） =====================

class TestAbout:
    def test_about_payload(self, client, h):
        data = client.get(f"{API}/about", headers=h).json()
        assert data["app"] == "CTMS"
        assert data["version"]
        assert data["database"]["kind"] == "sqlite"
        for key in ("contracts", "users", "products", "operation_logs"):
            assert key in data["counts"]
        assert data["permission_count"] > 0

    def test_about_requires_permission(self, client):
        uid = _mk_user_with_role("buyer")
        try:
            headers = {"Authorization": f"Bearer {_token_of(client, uid)}"}
            assert client.get(f"{API}/about", headers=headers).status_code == 403
        finally:
            _drop_user(uid)
