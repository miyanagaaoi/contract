"""T-V2-38 测试：首页看板按角色重规划（待办 / 库存预警 / 合同概览）。

验收要点（`11-erp-requirements.md` §15 / O15）：
- 待办按权限裁剪：有审核权限的角色看到"待我审核"，无权限则为 0；
- 库存预警：低于安全库存的「物料 × 仓库」进入预警清单；
- 合同概览：金额/已付/付款比例与状态分布，且受数据范围限制；
- 兼容性：V1.0 的 `stats`/`expiring`/`expired` 字段结构不变。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models import ChangeLog, Contract, ContractItem, contract_tag
from app.models_auth import OperationLog, Role, User
from app.models_doc import DOC_MODELS
from app.models_master import Product, ProductType, Uom, Warehouse
from app.models_stock import Stock, StockLedger
from app.security import hash_password


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


class Box:
    def __init__(self, client, admin_h):
        self.client = client
        self.admin = admin_h
        self.users: list[int] = []
        self.products: list[int] = []
        self.types: list[int] = []
        self.uoms: list[int] = []
        self.warehouses: list[int] = []
        self.contracts: list[int] = []
        self.orgs: list[int] = []
        self.docs: dict[str, list[int]] = {k: [] for k in DOC_MODELS}
        self._cache: dict[str, dict] = {}

    def product(self, safety_stock: float | None = None) -> dict:
        r = self.client.post("/api/master/product-types", headers=self.admin, json={
            "name": f"看板类型{uuid.uuid4().hex[:5]}", "code": f"D{uuid.uuid4().hex[:3].upper()}"})
        assert r.status_code == 200, r.text
        self.types.append(r.json()["id"])
        ptype = r.json()
        r = self.client.post("/api/master/uoms", headers=self.admin, json={
            "code": f"DU{uuid.uuid4().hex[:4].upper()}", "name": f"单位{uuid.uuid4().hex[:4]}",
            "decimals": 2})
        self.uoms.append(r.json()["id"])
        uom = r.json()
        payload = {"name": f"看板物料{uuid.uuid4().hex[:5]}", "product_type_id": ptype["id"],
                   "uom_id": uom["id"], "default_price": 5}
        if safety_stock is not None:
            payload["safety_stock"] = safety_stock
        r = self.client.post("/api/master/products", headers=self.admin, json=payload)
        assert r.status_code == 200, r.text
        self.products.append(r.json()["id"])
        return r.json()

    def warehouse(self) -> dict:
        r = self.client.post("/api/master/warehouses", headers=self.admin, json={
            "code": f"DW{uuid.uuid4().hex[:4].upper()}", "name": f"看板仓{uuid.uuid4().hex[:4]}"})
        assert r.status_code == 200, r.text
        self.warehouses.append(r.json()["id"])
        return r.json()

    def headers(self, role_code: str, org_id: int | None = None) -> dict:
        cache_key = f"{role_code}:{org_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        username = f"db_{role_code[:6]}_{uuid.uuid4().hex[:6]}"
        with SessionLocal() as db:
            role = db.query(Role).filter(Role.code == role_code).one()
            user = User(username=username, real_name=f"看板-{role_code}", org_id=org_id,
                        password_hash=hash_password("init12345"), status="enabled")
            user.roles.append(role)
            db.add(user)
            db.commit()
            self.users.append(user.id)
        token = self.client.post("/api/auth/login",
                                 json={"username": username, "password": "init12345"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        self._cache[cache_key] = headers
        return headers

    def org(self, name: str) -> dict:
        r = self.client.post("/api/system/org-units", headers=self.admin,
                             json={"name": name, "unit_type": "部门"})
        assert r.status_code == 200, r.text
        self.orgs.append(r.json()["id"])
        return r.json()

    def cleanup(self) -> None:
        from sqlalchemy import text

        with SessionLocal() as db:
            for kind, ids in self.docs.items():
                table = DOC_MODELS[kind].__tablename__
                for doc_id in ids:
                    db.execute(text(f"DELETE FROM {table} WHERE id = :i"), {"i": doc_id})
            db.query(ChangeLog).filter(ChangeLog.object_type.in_(list(DOC_MODELS))).delete(
                synchronize_session=False)
            for pid in self.products:
                db.query(StockLedger).filter(StockLedger.product_id == pid).delete()
                db.query(Stock).filter(Stock.product_id == pid).delete()
            for cid in self.contracts:
                db.execute(contract_tag.delete().where(contract_tag.c.contract_id == cid))
                db.query(ChangeLog).filter(ChangeLog.contract_id == cid).delete()
                db.query(ContractItem).filter(ContractItem.contract_id == cid).delete()
                db.query(Contract).filter(Contract.id == cid).delete()
            for table, ids in (("products", self.products), ("uoms", self.uoms),
                               ("warehouses", self.warehouses),
                               ("product_types", list(reversed(self.types)))):
                for obj_id in ids:
                    db.execute(text(f"DELETE FROM {table} WHERE id = :i"), {"i": obj_id})
            for uid in self.users:
                db.query(OperationLog).filter(OperationLog.user_id == uid).delete()
                db.query(User).filter(User.id == uid).delete()
            db.commit()
            from app.models_auth import OrgUnit

            for oid in self.orgs:
                node = db.get(OrgUnit, oid)
                if node is not None:
                    db.delete(node)
            db.commit()
        self.__init__(self.client, self.admin)


@pytest.fixture()
def box(client, admin):
    instance = Box(client, admin)
    try:
        yield instance
    finally:
        instance.cleanup()


class TestDashboard:
    def test_legacy_fields_kept(self, box):
        data = box.client.get("/api/dashboard", headers=box.admin).json()
        assert {"stats", "expiring", "expired"} <= set(data)
        assert data["stats"]["window_days"] >= 1
        assert "todo" in data and "stock_alerts" in data and "contract_overview" in data

    def test_todo_is_permission_aware(self, box):
        product = box.product()
        dept = box.org(f"看板部{uuid.uuid4().hex[:4]}")
        # 同一部门下的采购员与采购主管：主管（本部门及下级）可见该部门待审核单据
        buyer, manager = box.headers("buyer", dept["id"]), box.headers("purchase_manager", dept["id"])
        draft = box.client.post("/api/purchase/requests", headers=buyer, json={
            "items": [{"product_id": product["id"], "qty": 3, "unit_price": 5}]}).json()
        box.docs["purchase_request"].append(draft["id"])

        buyer_dash = box.client.get("/api/dashboard", headers=buyer).json()
        assert buyer_dash["todo"]["my_draft"]["total"] >= 1
        assert buyer_dash["todo"]["to_approve"]["total"] == 0, "采购员无审核权限，待办应为 0"

        box.client.post(f"/api/purchase/requests/{draft['id']}/submit", headers=buyer)
        buyer_dash = box.client.get("/api/dashboard", headers=buyer).json()
        assert buyer_dash["todo"]["my_submitted"]["total"] >= 1
        assert any(i["doc_no"] == draft["doc_no"]
                   for i in buyer_dash["todo"]["my_submitted"]["items"])

        manager_dash = box.client.get("/api/dashboard", headers=manager).json()
        assert manager_dash["todo"]["to_approve"]["total"] >= 1
        assert any(i["doc_no"] == draft["doc_no"]
                   for i in manager_dash["todo"]["to_approve"]["items"])
        assert manager_dash["todo"]["by_kind"]["purchase_request"]["can_approve"] is True

    def test_stock_alert_below_safety(self, box):
        product = box.product(safety_stock=10)
        warehouse, keeper = box.warehouse(), box.headers("keeper")
        doc = box.client.post("/api/stock/in-orders", headers=keeper, json={
            "warehouse_id": warehouse["id"], "in_type": "其他入库",
            "items": [{"product_id": product["id"], "qty": 2, "unit_price": 5}]}).json()
        box.docs["stock_in"].append(doc["id"])
        box.client.post(f"/api/stock/in-orders/{doc['id']}/submit", headers=keeper)
        box.client.post(f"/api/stock/in-orders/{doc['id']}/approve", headers=box.admin)

        dash = box.client.get("/api/dashboard", headers=keeper).json()
        alerts = dash["stock_alerts"]
        assert alerts["available"] is True
        assert alerts["total"] >= 1
        row = next(i for i in alerts["items"] if i["product_id"] == product["id"])
        assert row["qty"] == 2.0 and row["safety_stock"] == 10.0 and row["shortage"] == 8.0

    def test_contract_overview(self, box):
        created = box.client.post("/api/contracts", headers=box.admin, json={
            "name": f"看板合同{uuid.uuid4().hex[:5]}", "type": "COO", "subject_code": "ZC",
            "amount": 1000, "paid_amount": 250}).json()
        box.contracts.append(created["id"])
        overview = box.client.get("/api/dashboard", headers=box.admin).json()["contract_overview"]
        assert overview["total"] >= 1
        assert overview["amount_sum"] >= 1000.0 and overview["paid_sum"] >= 250.0
        assert overview["paid_ratio"] is not None

    def test_requires_login(self, client):
        assert client.get("/api/dashboard").status_code == 401
