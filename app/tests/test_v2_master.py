"""T-V2-07~11 主数据测试：客户/供应商、商品类型树、计量单位、仓库、物料。

对应验收场景：
- AC-V2-10（物料编码自动生成、类型叶子校验、单位绑定、停用）
- AC-V2-11（计量单位小数位；前置：单位字典可用）
- AC-V2-12（客户/供应商档案与编码自动生成）
- AC-V2-09（商品类型树：叶子校验、删除校验）
- AC-V2-03/41（权限后端强制：查看/维护权限点分离）

测试自建档案并在 fixture 结束时按依赖顺序清理。
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
from app.models_master import Customer, PartyDraft, Product, ProductType, Supplier, Uom, Warehouse
from app.security import hash_password

API = "/api/master"


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


def _mk_user_with_role(role_code: str) -> int:
    username = f"m_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        role = db.query(Role).filter(Role.code == role_code).one()
        user = User(username=username, real_name="主数据测试账号",
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


class Box:
    """测试数据工厂 + 依赖顺序清理。"""

    def __init__(self, client, headers):
        self.client = client
        self.h = headers
        self.products: list[int] = []
        self.uoms: list[int] = []
        self.warehouses: list[int] = []
        self.types: list[int] = []
        self.customers: list[int] = []
        self.suppliers: list[int] = []
        self.contracts: list[int] = []

    # ---- 工厂 ----
    def customer(self, name: str | None = None, **extra) -> dict:
        payload = {"name": name or f"客户_{uuid.uuid4().hex[:6]}", **extra}
        resp = self.client.post(f"{API}/customers", headers=self.h, json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        self.customers.append(data["id"])
        return data

    def supplier(self, name: str | None = None, **extra) -> dict:
        payload = {"name": name or f"供应商_{uuid.uuid4().hex[:6]}", **extra}
        resp = self.client.post(f"{API}/suppliers", headers=self.h, json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        self.suppliers.append(data["id"])
        return data

    def ptype(self, name: str | None = None, parent_id: int | None = None, **extra) -> dict:
        payload = {"name": name or f"类型_{uuid.uuid4().hex[:6]}", **extra}
        if parent_id is not None:
            payload["parent_id"] = parent_id
        resp = self.client.post(f"{API}/product-types", headers=self.h, json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        self.types.append(data["id"])
        return data

    def uom(self, code: str | None = None, decimals: int = 2) -> dict:
        payload = {"code": code or f"U{uuid.uuid4().hex[:4].upper()}",
                   "name": f"单位_{uuid.uuid4().hex[:4]}", "decimals": decimals}
        resp = self.client.post(f"{API}/uoms", headers=self.h, json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        self.uoms.append(data["id"])
        return data

    def warehouse(self) -> dict:
        payload = {"code": f"W{uuid.uuid4().hex[:4].upper()}",
                   "name": f"仓库_{uuid.uuid4().hex[:4]}"}
        resp = self.client.post(f"{API}/warehouses", headers=self.h, json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        self.warehouses.append(data["id"])
        return data

    def product(self, *, ptype_id: int, uom_id: int, name: str | None = None, **extra) -> dict:
        payload = {"name": name or f"物料_{uuid.uuid4().hex[:6]}",
                   "product_type_id": ptype_id, "uom_id": uom_id, **extra}
        resp = self.client.post(f"{API}/products", headers=self.h, json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        self.products.append(data["id"])
        return data

    def contract(self, *, customer_id: int | None = None, supplier_id: int | None = None) -> dict:
        payload = {"name": f"主数据关联合同_{uuid.uuid4().hex[:6]}", "type": "SAL",
                   "subject_code": "ZC", "amount": 100}
        if customer_id:
            payload["customer_id"] = customer_id
        if supplier_id:
            payload["type"] = "PUR"
            payload["supplier_id"] = supplier_id
        resp = self.client.post("/api/contracts", headers=self.h, json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        self.contracts.append(data["id"])
        return data

    # ---- 清理 ----
    def cleanup_contracts(self) -> None:
        """仅清理合同（用于验证"解除引用后可删除档案"）。"""
        with SessionLocal() as db:
            for cid in self.contracts:
                db.execute(contract_tag.delete().where(contract_tag.c.contract_id == cid))
                db.query(ChangeLog).filter(ChangeLog.contract_id == cid).delete()
                db.query(ContractItem).filter(ContractItem.contract_id == cid).delete()
                db.query(Contract).filter(Contract.id == cid).delete()
            db.commit()
        self.contracts = []

    def cleanup(self) -> None:
        with SessionLocal() as db:
            for cid in self.contracts:
                db.execute(contract_tag.delete().where(contract_tag.c.contract_id == cid))
                db.query(ChangeLog).filter(ChangeLog.contract_id == cid).delete()
                db.query(ContractItem).filter(ContractItem.contract_id == cid).delete()
                db.query(Contract).filter(Contract.id == cid).delete()
            for pid in self.products:
                db.query(Product).filter(Product.id == pid).delete()
            for uid in self.uoms:
                db.query(Uom).filter(Uom.id == uid).delete()
            for wid in self.warehouses:
                db.query(Warehouse).filter(Warehouse.id == wid).delete()
            for tid in sorted(self.types, reverse=True):
                db.query(ProductType).filter(ProductType.id == tid).delete()
            for cid in self.customers:
                db.query(Customer).filter(Customer.id == cid).delete()
            for sid in self.suppliers:
                db.query(Supplier).filter(Supplier.id == sid).delete()
            db.query(PartyDraft).delete()
            db.commit()
        self.products, self.uoms, self.warehouses = [], [], []
        self.types, self.customers, self.suppliers, self.contracts = [], [], [], []


@pytest.fixture()
def box(client, h):
    instance = Box(client, h)
    try:
        yield instance
    finally:
        instance.cleanup()


# ===================== 客户 / 供应商（AC-V2-12） =====================

class TestParty:
    def test_customer_auto_code_and_name(self, box):
        created = box.customer()
        assert created["code"].startswith("CUS")
        assert created["status"] == "enabled"

    def test_supplier_auto_code_starts_with_sup(self, box):
        created = box.supplier()
        assert created["code"].startswith("SUP")

    def test_supplier_extra_fields(self, box):
        created = box.supplier(supply_scope="钢材/五金", payment_days=45)
        assert created["supply_scope"] == "钢材/五金"
        assert created["payment_days"] == 45

    def test_reject_duplicate_name(self, box):
        name = f"重名客户_{uuid.uuid4().hex[:6]}"
        box.customer(name)
        resp = box.client.post(f"{API}/customers", headers=box.h, json={"name": name})
        assert resp.status_code == 422
        assert "同名" in resp.json()["detail"]

    def test_reject_duplicate_manual_code(self, box):
        first = box.customer()
        resp = box.client.post(f"{API}/customers", headers=box.h,
                               json={"name": f"另一个_{uuid.uuid4().hex[:6]}", "code": first["code"]})
        assert resp.status_code == 422
        assert "编码已存在" in resp.json()["detail"]

    def test_reject_empty_name(self, box):
        resp = box.client.post(f"{API}/customers", headers=box.h, json={"name": "   "})
        assert resp.status_code == 422
        assert "名称不能为空" in resp.json()["detail"]

    def test_update_and_disable(self, box):
        created = box.customer()
        resp = box.client.put(f"{API}/customers/{created['id']}", headers=box.h,
                              json={"contact_name": "王采购", "contact_phone": "13800000000",
                                    "level": "A", "credit_limit": 50000})
        assert resp.status_code == 200, resp.text
        assert resp.json()["contact_name"] == "王采购"
        assert resp.json()["credit_limit"] == 50000

        disabled = box.client.put(f"{API}/customers/{created['id']}/status",
                                  headers=box.h, json={"enabled": False})
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "disabled"

        listed = box.client.get(f"{API}/customers", headers=box.h,
                                params={"status": "disabled", "keyword": created["name"]}).json()
        assert listed["total"] == 1

    def test_delete_referenced_customer_rejected(self, box):
        created = box.customer()
        box.contract(customer_id=created["id"])
        resp = box.client.delete(f"{API}/customers/{created['id']}", headers=box.h)
        assert resp.status_code == 422
        assert "引用" in resp.json()["detail"]

        # 合同清理后方可删除
        box.cleanup_contracts()
        assert box.client.delete(f"{API}/customers/{created['id']}", headers=box.h).status_code == 200

    def test_delete_free_customer_ok(self, box):
        created = box.customer()
        assert box.client.delete(f"{API}/customers/{created['id']}", headers=box.h).status_code == 200

    def test_options_return_only_enabled(self, box):
        keep = box.customer()
        hidden = box.customer()
        box.client.put(f"{API}/customers/{hidden['id']}/status", headers=box.h, json={"enabled": False})
        rows = box.client.get(f"{API}/options/customer", headers=box.h).json()
        ids = [r["id"] for r in rows]
        assert keep["id"] in ids
        assert hidden["id"] not in ids

    def test_pagination_payload(self, box):
        for _ in range(3):
            box.customer()
        data = box.client.get(f"{API}/customers", headers=box.h,
                              params={"page": 1, "page_size": 2}).json()
        assert data["page"] == 1 and data["page_size"] == 2
        assert len(data["items"]) <= 2
        assert data["total"] >= 3


# ===================== 商品类型树（AC-V2-09） =====================

class TestProductType:
    def test_tree_path_and_level(self, box):
        root = box.ptype(code="RAW")
        child = box.ptype(parent_id=root["id"])
        assert root["level"] == 1 and root["path"] == f"/{root['id']}/"
        assert child["level"] == 2
        assert child["path"] == f"{root['path']}{child['id']}/"
        assert child["parent_id"] == root["id"]

    def test_tree_payload_nested_and_leaf_flag(self, box):
        root = box.ptype()
        child = box.ptype(parent_id=root["id"])
        payload = box.client.get(f"{API}/product-types", headers=box.h,
                                 params={"keyword": root["name"]}).json()

        def find(nodes, node_id):
            for n in nodes:
                if n["id"] == node_id:
                    return n
                got = find(n.get("children") or [], node_id)
                if got:
                    return got
            return None

        node = find(payload["tree"], root["id"])
        assert node is not None
        assert node["is_leaf"] is False, "有子类型时不是叶子"
        leaf = find(node["children"], child["id"])
        assert leaf is not None and leaf["is_leaf"] is True

    def test_reject_duplicate_sibling_name(self, box):
        root = box.ptype()
        name = f"重名类型_{uuid.uuid4().hex[:4]}"
        box.ptype(name, parent_id=root["id"])
        resp = box.client.post(f"{API}/product-types", headers=box.h,
                               json={"name": name, "parent_id": root["id"]})
        assert resp.status_code == 422
        assert "同名" in resp.json()["detail"]

    def test_cannot_delete_type_with_children(self, box):
        root = box.ptype()
        box.ptype(parent_id=root["id"])
        resp = box.client.delete(f"{API}/product-types/{root['id']}", headers=box.h)
        assert resp.status_code == 422
        assert "子类型" in resp.json()["detail"]

    def test_cannot_delete_type_with_products(self, box):
        leaf = box.ptype(code=f"T{uuid.uuid4().hex[:3].upper()}")
        uom = box.uom()
        box.product(ptype_id=leaf["id"], uom_id=uom["id"])
        resp = box.client.delete(f"{API}/product-types/{leaf['id']}", headers=box.h)
        assert resp.status_code == 422
        assert "物料" in resp.json()["detail"]

    def test_disable_type(self, box):
        leaf = box.ptype()
        resp = box.client.put(f"{API}/product-types/{leaf['id']}/status",
                              headers=box.h, json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False


# ===================== 计量单位（AC-V2-11） =====================

class TestUom:
    def test_create_with_decimals(self, box):
        created = box.uom(decimals=3)
        assert created["decimals"] == 3

    def test_reject_decimals_out_of_range(self, box):
        resp = box.client.post(f"{API}/uoms", headers=box.h,
                               json={"code": f"X{uuid.uuid4().hex[:3].upper()}",
                                     "name": "非法单位", "decimals": 9})
        assert resp.status_code == 422
        assert "小数位" in resp.json()["detail"]

    def test_reject_duplicate_code(self, box):
        created = box.uom()
        resp = box.client.post(f"{API}/uoms", headers=box.h,
                               json={"code": created["code"], "name": "重复编码单位"})
        assert resp.status_code == 422
        assert "已存在" in resp.json()["detail"]

    def test_cannot_delete_uom_in_use(self, box):
        leaf = box.ptype()
        uom = box.uom()
        box.product(ptype_id=leaf["id"], uom_id=uom["id"])
        resp = box.client.delete(f"{API}/uoms/{uom['id']}", headers=box.h)
        assert resp.status_code == 422
        assert "物料" in resp.json()["detail"]
        # 停用是允许的
        assert box.client.put(f"{API}/uoms/{uom['id']}/status", headers=box.h,
                              json={"enabled": False}).status_code == 200


# ===================== 仓库 =====================

class TestWarehouse:
    def test_crud_and_disable(self, box):
        created = box.warehouse()
        resp = box.client.put(f"{API}/warehouses/{created['id']}", headers=box.h,
                              json={"address": "上海市浦东新区", "remark": "主仓"})
        assert resp.status_code == 200
        assert resp.json()["address"] == "上海市浦东新区"

        assert box.client.put(f"{API}/warehouses/{created['id']}/status", headers=box.h,
                              json={"enabled": False}).json()["enabled"] is False
        rows = box.client.get(f"{API}/warehouses", headers=box.h,
                              params={"include_disabled": False}).json()["items"]
        assert all(r["id"] != created["id"] for r in rows)

    def test_reject_duplicate_name(self, box):
        created = box.warehouse()
        resp = box.client.post(f"{API}/warehouses", headers=box.h,
                               json={"code": f"W{uuid.uuid4().hex[:4].upper()}",
                                     "name": created["name"]})
        assert resp.status_code == 422
        assert "已存在" in resp.json()["detail"]


# ===================== 物料（AC-V2-10） =====================

class TestProduct:
    def test_auto_code_uses_type_code(self, box):
        leaf = box.ptype(code="RAW")
        uom = box.uom()
        first = box.product(ptype_id=leaf["id"], uom_id=uom["id"])
        second = box.product(ptype_id=leaf["id"], uom_id=uom["id"])
        assert first["code"].startswith("RAW")
        assert first["code"] != second["code"]
        assert int(second["code"][len("RAW"):]) == int(first["code"][len("RAW"):]) + 1

    def test_auto_code_with_numeric_prefix_not_duplicated(self, box):
        """类型码含数字时（如 L476）不得把前缀数字并进序号（曾生成 L4764760002）。"""
        code = f"L{uuid.uuid4().int % 900 + 100}"
        leaf = box.ptype(code=code)
        uom = box.uom()
        first = box.product(ptype_id=leaf["id"], uom_id=uom["id"])
        second = box.product(ptype_id=leaf["id"], uom_id=uom["id"])
        assert first["code"] == f"{code}0001", first["code"]
        assert second["code"] == f"{code}0002", second["code"]

    def test_manual_code_kept(self, box):
        leaf = box.ptype()
        uom = box.uom()
        created = box.product(ptype_id=leaf["id"], uom_id=uom["id"], code="MANUAL-001")
        assert created["code"] == "MANUAL-001"

    def test_snapshot_fields_of_type_and_uom(self, box):
        leaf = box.ptype(code="STL")
        uom = box.uom(decimals=3)
        created = box.product(ptype_id=leaf["id"], uom_id=uom["id"])
        assert created["product_type_name"] == leaf["name"]
        assert created["uom_name"] == uom["name"]
        assert created["uom_decimals"] == 3

    def test_reject_parent_type(self, box):
        root = box.ptype()
        box.ptype(parent_id=root["id"])
        uom = box.uom()
        resp = box.client.post(f"{API}/products", headers=box.h,
                               json={"name": "非法挂载物料", "product_type_id": root["id"],
                                     "uom_id": uom["id"]})
        assert resp.status_code == 422
        assert "叶子" in resp.json()["detail"]

    def test_reject_missing_type_or_uom(self, box):
        uom = box.uom()
        resp = box.client.post(f"{API}/products", headers=box.h,
                               json={"name": "缺类型", "uom_id": uom["id"]})
        assert resp.status_code == 422
        assert "商品类型" in resp.json()["detail"]

        leaf = box.ptype()
        resp = box.client.post(f"{API}/products", headers=box.h,
                               json={"name": "缺单位", "product_type_id": leaf["id"]})
        assert resp.status_code == 422
        assert "计量单位" in resp.json()["detail"]

    def test_reject_disabled_uom(self, box):
        leaf = box.ptype()
        uom = box.uom()
        box.client.put(f"{API}/uoms/{uom['id']}/status", headers=box.h, json={"enabled": False})
        resp = box.client.post(f"{API}/products", headers=box.h,
                               json={"name": "停用单位物料", "product_type_id": leaf["id"],
                                     "uom_id": uom["id"]})
        assert resp.status_code == 422
        assert "已停用" in resp.json()["detail"]

    def test_safety_stock_and_price(self, box):
        leaf = box.ptype()
        uom = box.uom()
        created = box.product(ptype_id=leaf["id"], uom_id=uom["id"],
                              default_price=12.5, safety_stock=100)
        assert created["default_price"] == 12.5
        assert created["safety_stock"] == 100

    def test_disable_and_filter(self, box):
        leaf = box.ptype()
        uom = box.uom()
        created = box.product(ptype_id=leaf["id"], uom_id=uom["id"])
        box.client.put(f"{API}/products/{created['id']}/status", headers=box.h,
                       json={"enabled": False})
        rows = box.client.get(f"{API}/products", headers=box.h,
                              params={"status": "disabled", "keyword": created["name"]}).json()
        assert rows["total"] == 1
        assert rows["items"][0]["status"] == "disabled"

    def test_options_exclude_disabled(self, box):
        leaf = box.ptype()
        uom = box.uom()
        active = box.product(ptype_id=leaf["id"], uom_id=uom["id"])
        inactive = box.product(ptype_id=leaf["id"], uom_id=uom["id"])
        box.client.put(f"{API}/products/{inactive['id']}/status", headers=box.h,
                       json={"enabled": False})
        ids = [r["id"] for r in box.client.get(f"{API}/options/product", headers=box.h).json()]
        assert active["id"] in ids
        assert inactive["id"] not in ids


# ===================== 权限与登录门禁（AC-V2-03 / AC-V2-41） =====================

class TestMasterPermissions:
    def test_unauthenticated_denied(self, client):
        assert client.get(f"{API}/customers").status_code == 401
        assert client.get(f"{API}/products").status_code == 401
        assert client.get(f"{API}/options/customer").status_code == 401
        assert client.post(f"{API}/uoms", json={"code": "X", "name": "y"}).status_code == 401

    def test_buyer_can_view_product_but_not_edit(self, client):
        uid = _mk_user_with_role("buyer")
        try:
            headers = {"Authorization": f"Bearer {_token_of(client, uid)}"}
            assert client.get(f"{API}/products", headers=headers).status_code == 200
            resp = client.post(f"{API}/products", headers=headers, json={"name": "越权物料"})
            assert resp.status_code == 403
            assert "master.product.edit" in resp.json()["detail"]
        finally:
            _drop_user(uid)

    def test_keeper_denied_customer_view(self, client):
        uid = _mk_user_with_role("keeper")
        try:
            headers = {"Authorization": f"Bearer {_token_of(client, uid)}"}
            resp = client.get(f"{API}/customers", headers=headers)
            assert resp.status_code == 403
            assert "master.customer.view" in resp.json()["detail"]
            # 但下拉数据登录即可（单据页要用）
            assert client.get(f"{API}/options/customer", headers=headers).status_code == 200
        finally:
            _drop_user(uid)

    def test_meta_requires_login_only(self, client):
        uid = _mk_user_with_role("keeper")
        try:
            headers = {"Authorization": f"Bearer {_token_of(client, uid)}"}
            data = client.get(f"{API}/meta", headers=headers).json()
            assert data["party_statuses"] == ["enabled", "disabled"]
            assert data["uom_decimals_range"] == [0, 4]
        finally:
            _drop_user(uid)

    def test_org_options_for_department_pickers(self, client, h, box):
        """组织下拉（登录即可）：单据表单选择申请/采购部门用。"""
        org = box.client.post("/api/system/org-units", headers=h,
                              json={"name": f"下拉部_{uuid.uuid4().hex[:4]}", "unit_type": "部门"}).json()
        try:
            rows = box.client.get(f"{API}/options/org", headers=h).json()
            assert any(r["id"] == org["id"] and r["name"] == org["name"] for r in rows)
            rows = box.client.get(f"{API}/options/org", headers=h,
                                  params={"keyword": org["name"]}).json()
            assert len(rows) == 1
            # 登录即可（无 master.org.view 的角色也能取到，避免开不了单）
            uid = _mk_user_with_role("buyer")
            try:
                headers = {"Authorization": f"Bearer {_token_of(client, uid)}"}
                assert box.client.get(f"{API}/options/org", headers=headers).status_code == 200
            finally:
                _drop_user(uid)
        finally:
            box.client.delete(f"/api/system/org-units/{org['id']}", headers=h)
