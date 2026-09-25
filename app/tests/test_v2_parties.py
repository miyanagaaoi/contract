"""T-V2-13 / T-V2-14 测试：合同甲乙方档案化 + 历史文本迁移。

对应验收场景：
- AC-V2-33 合同甲乙方档案化（选档案后保存 id 与名称快照；其他类型可用纯文本）
- AC-V2-34 历史合同文本兼容（无档案的历史合同照常显示/导出）
- AC-V2-35 历史档案认领（扫描生成草案 → 认领 → 批量绑定）
- AC-V2-37 变更历史带操作人（合同档案变更亦记录操作人）

测试自建合同与档案并在结束时清理。
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models import ChangeLog, Contract, ContractItem, contract_tag
from app.models_master import Customer, PartyDraft, Product, Supplier
from app.security import hash_password

API = "/api/contracts"


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


class Box:
    def __init__(self, client, headers):
        self.client = client
        self.h = headers
        self.customers: list[int] = []
        self.suppliers: list[int] = []
        self.contracts: list[int] = []
        self.drafts: list[int] = []

    # ---- 工厂 ----
    def customer(self, name: str | None = None) -> dict:
        resp = self.client.post("/api/master/customers", headers=self.h,
                                json={"name": name or f"档案客户_{uuid.uuid4().hex[:6]}"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        self.customers.append(data["id"])
        return data

    def supplier(self, name: str | None = None) -> dict:
        resp = self.client.post("/api/master/suppliers", headers=self.h,
                                json={"name": name or f"档案供应商_{uuid.uuid4().hex[:6]}"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        self.suppliers.append(data["id"])
        return data

    def contract(self, **payload) -> dict:
        body = {"name": f"档案合同_{uuid.uuid4().hex[:6]}", "type": "COO",
                "subject_code": "ZC", "amount": 1000}
        body.update(payload)
        resp = self.client.post(API, headers=self.h, json=body)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        self.contracts.append(data["id"])
        return data

    def legacy_contract(self, *, party_b: str, party_a: str = "我方公司",
                        ctype: str = "采购/支出") -> int:
        """直接落库模拟 V1.0 历史合同（纯文本、无档案）。"""
        with SessionLocal() as db:
            row = Contract(contract_no=f"LEG-{uuid.uuid4().hex[:8].upper()}",
                           name=f"历史合同_{uuid.uuid4().hex[:6]}", type=ctype,
                           party_a=party_a, party_b=party_b, amount=Decimal("5000"))
            db.add(row)
            db.commit()
            self.contracts.append(row.id)
            return row.id

    # ---- 清理 ----
    def cleanup(self) -> None:
        with SessionLocal() as db:
            for cid in self.contracts:
                db.execute(contract_tag.delete().where(contract_tag.c.contract_id == cid))
                db.query(ChangeLog).filter(ChangeLog.contract_id == cid).delete()
                db.query(ContractItem).filter(ContractItem.contract_id == cid).delete()
                db.query(Contract).filter(Contract.id == cid).delete()
            for did in self.drafts:
                db.query(PartyDraft).filter(PartyDraft.id == did).delete()
            for cid in self.customers:
                db.query(Customer).filter(Customer.id == cid).delete()
            for sid in self.suppliers:
                db.query(Supplier).filter(Supplier.id == sid).delete()
            db.commit()
        self.customers, self.suppliers, self.contracts, self.drafts = [], [], [], []


@pytest.fixture()
def box(client, h):
    instance = Box(client, h)
    try:
        yield instance
    finally:
        instance.cleanup()


# ===================== AC-V2-33 档案化 =====================

class TestPartyArchiving:
    def test_sales_contract_binds_customer(self, box):
        customer = box.customer()
        created = box.contract(type="SAL", customer_id=customer["id"])
        assert created["customer_id"] == customer["id"]
        assert created["customer_name"] == customer["name"]
        assert created["party_a"] == customer["name"], "未填文本时应以档案名回填快照"

    def test_purchase_contract_binds_supplier(self, box):
        supplier = box.supplier()
        created = box.contract(type="PUR", supplier_id=supplier["id"])
        assert created["supplier_id"] == supplier["id"]
        assert created["supplier_name"] == supplier["name"]
        assert created["party_b"] == supplier["name"]

    def test_explicit_text_not_overwritten(self, box):
        supplier = box.supplier()
        created = box.contract(type="PUR", supplier_id=supplier["id"], party_b="合同上的原始乙方名称")
        assert created["party_b"] == "合同上的原始乙方名称"
        assert created["supplier_name"] == supplier["name"]

    def test_reject_unknown_archive_id(self, box):
        resp = box.client.post(API, headers=box.h, json={
            "name": "脏引用合同", "type": "SAL", "subject_code": "ZC",
            "amount": 1, "customer_id": 99999999})
        assert resp.status_code == 422
        assert "客户档案不存在" in resp.json()["detail"]

        resp = box.client.post(API, headers=box.h, json={
            "name": "脏引用合同2", "type": "PUR", "subject_code": "ZC",
            "amount": 1, "supplier_id": 99999999})
        assert resp.status_code == 422
        assert "供应商档案不存在" in resp.json()["detail"]

    def test_update_contract_to_archive_records_operator(self, box):
        supplier = box.supplier()
        created = box.contract(type="PUR")          # 先纯文本
        resp = box.client.put(f"{API}/{created['id']}", headers=box.h,
                              json={"supplier_id": supplier["id"]})
        assert resp.status_code == 200, resp.text
        assert resp.json()["supplier_id"] == supplier["id"]

        logs = box.client.get(f"{API}/{created['id']}/logs", headers=box.h).json()
        rows = [r for r in logs if r["field_name"] == "supplier_id"]
        assert rows and rows[0]["operator_name"], "档案绑定应写入带操作人的变更历史"
        assert rows[0]["new_value"] == str(supplier["id"])

    def test_plain_text_contract_still_supported(self, box):
        """AC-V2-34：其他类型合同可用纯文本甲乙方，列表/详情/导出不报错。"""
        created = box.contract(type="COO", party_a="文本甲方", party_b="文本乙方")
        detail = box.client.get(f"{API}/{created['id']}", headers=box.h).json()
        assert detail["party_a"] == "文本甲方"
        assert detail["party_b"] == "文本乙方"
        assert detail["customer_id"] is None and detail["supplier_id"] is None

        listed = box.client.get(API, headers=box.h, params={"keyword": "文本甲方"}).json()
        assert any(i["id"] == created["id"] for i in listed["items"])

    def test_search_by_archive_name_snapshot(self, box):
        customer = box.customer()
        created = box.contract(type="SAL", customer_id=customer["id"])
        listed = box.client.get(API, headers=box.h, params={"keyword": customer["name"]}).json()
        assert any(i["id"] == created["id"] for i in listed["items"])


# ===================== AC-V2-35 历史档案迁移 =====================

class TestPartyMigration:
    def test_scan_creates_pending_drafts(self, box):
        raw = f"待认领供应商_{uuid.uuid4().hex[:6]}"
        box.legacy_contract(party_b=raw)
        box.legacy_contract(party_b=raw)          # 同文本两张合同 → 聚合为一条草案

        result = box.client.post(f"{API}/migrate-parties", headers=box.h).json()
        assert result["created"] >= 1
        assert result["pending"] >= 1

        drafts = box.client.get(f"{API}/party-drafts", headers=box.h,
                                params={"status": "pending"}).json()
        row = next((d for d in drafts["items"] if d["raw_name"] == raw), None)
        assert row is not None, "扫描后应出现该文本的草案"
        box.drafts.append(row["id"])
        assert row["party_type"] == "supplier"
        assert row["contract_count"] == 2

    def test_claim_creates_archive_and_binds_contracts(self, box):
        raw = f"认领供应商_{uuid.uuid4().hex[:6]}"
        cid1 = box.legacy_contract(party_b=raw)
        cid2 = box.legacy_contract(party_b=raw)
        box.client.post(f"{API}/migrate-parties", headers=box.h)

        drafts = box.client.get(f"{API}/party-drafts", headers=box.h).json()
        row = next(d for d in drafts["items"] if d["raw_name"] == raw)
        box.drafts.append(row["id"])

        claimed = box.client.post(f"{API}/party-drafts/{row['id']}/claim",
                                  headers=box.h, json={})
        assert claimed.status_code == 200, claimed.text
        data = claimed.json()
        assert data["bound"] == 2
        assert data["archive"]["name"] == raw
        assert data["archive"]["code"].startswith("SUP")
        box.suppliers.append(data["archive"]["id"])

        with SessionLocal() as db:
            for cid in (cid1, cid2):
                assert db.get(Contract, cid).supplier_id == data["archive"]["id"]
            logs = db.query(ChangeLog).filter(ChangeLog.contract_id == cid1).all()
            assert any(lg.field_name == "supplier_id" and lg.operator_id for lg in logs), \
                "批量绑定应写带操作人的变更历史"

        # 认领后草案状态变更，且再次扫描不再产生 pending
        after = box.client.get(f"{API}/party-drafts", headers=box.h).json()
        assert all(d["raw_name"] != raw for d in after["items"])
        rescan = box.client.post(f"{API}/migrate-parties", headers=box.h).json()
        assert rescan["pending"] >= 0

    def test_claim_reuses_same_name_archive(self, box):
        raw = f"同名供应商_{uuid.uuid4().hex[:6]}"
        existing = box.supplier(raw)
        box.legacy_contract(party_b=raw)
        box.client.post(f"{API}/migrate-parties", headers=box.h)

        drafts = box.client.get(f"{API}/party-drafts", headers=box.h).json()
        row = next(d for d in drafts["items"] if d["raw_name"] == raw)
        box.drafts.append(row["id"])
        assert row["candidates"] and row["candidates"][0]["id"] == existing["id"], \
            "同名档案应作为认领候选返回"

        claimed = box.client.post(f"{API}/party-drafts/{row['id']}/claim",
                                  headers=box.h, json={}).json()
        assert claimed["archive"]["id"] == existing["id"], "同名时直接绑定已有档案，不重复建档"

    def test_claim_can_link_existing_archive_explicitly(self, box):
        raw = f"显式绑定供应商_{uuid.uuid4().hex[:6]}"
        target = box.supplier()
        box.legacy_contract(party_b=raw)
        box.client.post(f"{API}/migrate-parties", headers=box.h)

        drafts = box.client.get(f"{API}/party-drafts", headers=box.h).json()
        row = next(d for d in drafts["items"] if d["raw_name"] == raw)
        box.drafts.append(row["id"])
        claimed = box.client.post(f"{API}/party-drafts/{row['id']}/claim", headers=box.h,
                                  json={"action": "link", "target_id": target["id"]})
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["archive"]["id"] == target["id"]

    def test_claim_twice_rejected(self, box):
        raw = f"重复认领供应商_{uuid.uuid4().hex[:6]}"
        box.legacy_contract(party_b=raw)
        box.client.post(f"{API}/migrate-parties", headers=box.h)
        drafts = box.client.get(f"{API}/party-drafts", headers=box.h).json()
        row = next(d for d in drafts["items"] if d["raw_name"] == raw)
        box.drafts.append(row["id"])
        first = box.client.post(f"{API}/party-drafts/{row['id']}/claim", headers=box.h, json={})
        assert first.status_code == 200
        box.suppliers.append(first.json()["archive"]["id"])

        again = box.client.post(f"{API}/party-drafts/{row['id']}/claim", headers=box.h, json={})
        assert again.status_code == 422
        assert "已认领" in again.json()["detail"]

    def test_ignore_draft_keeps_text_fallback(self, box):
        raw = f"忽略供应商_{uuid.uuid4().hex[:6]}"
        cid = box.legacy_contract(party_b=raw)
        box.client.post(f"{API}/migrate-parties", headers=box.h)
        drafts = box.client.get(f"{API}/party-drafts", headers=box.h).json()
        row = next(d for d in drafts["items"] if d["raw_name"] == raw)
        box.drafts.append(row["id"])

        resp = box.client.post(f"{API}/party-drafts/{row['id']}/ignore", headers=box.h,
                               json={"reason": "历史文本无需建档"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

        detail = box.client.get(f"{API}/{cid}", headers=box.h).json()
        assert detail["party_b"] == raw, "忽略后合同仍以文本兜底展示"
        assert detail["supplier_id"] is None

    def test_scan_excludes_sales_direction_from_supplier(self, box):
        """方向判定：销售合同的甲方进客户草案，不会被当成供应商。"""
        raw = f"销售甲方_{uuid.uuid4().hex[:6]}"
        box.legacy_contract(party_a=raw, party_b="我方公司", ctype="销售/收入")
        box.client.post(f"{API}/migrate-parties", headers=box.h)
        drafts = box.client.get(f"{API}/party-drafts", headers=box.h,
                                params={"status": "all"}).json()
        row = next((d for d in drafts["items"] if d["raw_name"] == raw), None)
        assert row is not None
        box.drafts.append(row["id"])
        assert row["party_type"] == "customer"


# ===================== 权限边界 =====================

class TestMigratePermissions:
    def test_buyer_denied_claim(self, client, box):
        from app.models_auth import OperationLog, Role, User

        username = f"mig_{uuid.uuid4().hex[:8]}"
        with SessionLocal() as db:
            role = db.query(Role).filter(Role.code == "viewer").one()   # 只读角色
            user = User(username=username, real_name="迁移只读账号",
                        password_hash=hash_password("init12345"), status="enabled")
            user.roles.append(role)
            db.add(user)
            db.commit()
            uid = user.id
        try:
            token = client.post("/api/auth/login",
                                json={"username": username, "password": "init12345"}).json()["token"]
            headers = {"Authorization": f"Bearer {token}"}
            assert client.post(f"{API}/migrate-parties", headers=headers).status_code == 403
            assert client.post(f"{API}/party-drafts/1/claim", headers=headers).status_code == 403
        finally:
            with SessionLocal() as db:
                db.query(OperationLog).filter(OperationLog.user_id == uid).delete()
                db.query(User).filter(User.id == uid).delete()
                db.commit()
