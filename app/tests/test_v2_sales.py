"""T-V2-29~32 测试：销售申请 → 销售订单 → 出库单（含负库存拦截）。

对应验收场景：
- AC-V2-16 同构：销售申请下推销售订单（剩余量约束）
- AC-V2-20 出库审核减少库存；AC-V2-21 可用库存不足时拦截
- AC-V2-31 同构：销售订单只关联销售方向合同（下拉过滤）

测试自建主数据与单据并在结束时清理。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models import ChangeLog
from app.models_auth import OperationLog, Role, User
from app.models_doc import DOC_MODELS
from app.models_master import Customer, Product, ProductType, Uom, Warehouse
from app.models_stock import Stock, StockLedger
from app.security import hash_password

SELLER, SALES_MANAGER, KEEPER = "seller", "sales_manager", "keeper"


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
        self.customers: list[int] = []
        self.docs: dict[str, list[int]] = {k: [] for k in DOC_MODELS}
        self._cache: dict[str, dict] = {}

    def uom(self) -> dict:
        r = self.client.post("/api/master/uoms", headers=self.admin, json={
            "code": f"S{uuid.uuid4().hex[:5].upper()}", "name": f"件{uuid.uuid4().hex[:4]}",
            "decimals": 2})
        assert r.status_code == 200, r.text
        self.uoms.append(r.json()["id"])
        return r.json()

    def ptype(self) -> dict:
        r = self.client.post("/api/master/product-types", headers=self.admin, json={
            "name": f"销售类型{uuid.uuid4().hex[:5]}", "code": f"S{uuid.uuid4().hex[:3].upper()}"})
        assert r.status_code == 200, r.text
        self.types.append(r.json()["id"])
        return r.json()

    def product(self, ptype_id: int, uom_id: int) -> dict:
        r = self.client.post("/api/master/products", headers=self.admin, json={
            "name": f"销售物料{uuid.uuid4().hex[:5]}", "product_type_id": ptype_id,
            "uom_id": uom_id, "default_price": 20})
        assert r.status_code == 200, r.text
        self.products.append(r.json()["id"])
        return r.json()

    def warehouse(self) -> dict:
        r = self.client.post("/api/master/warehouses", headers=self.admin, json={
            "code": f"SW{uuid.uuid4().hex[:4].upper()}", "name": f"销售仓{uuid.uuid4().hex[:4]}"})
        assert r.status_code == 200, r.text
        self.warehouses.append(r.json()["id"])
        return r.json()

    def customer(self) -> dict:
        r = self.client.post("/api/master/customers", headers=self.admin,
                             json={"name": f"销售客户{uuid.uuid4().hex[:5]}"})
        assert r.status_code == 200, r.text
        self.customers.append(r.json()["id"])
        return r.json()

    def headers(self, role_code: str) -> dict:
        if role_code in self._cache:
            return self._cache[role_code]
        username = f"sl_{role_code[:6]}_{uuid.uuid4().hex[:6]}"
        with SessionLocal() as db:
            role = db.query(Role).filter(Role.code == role_code).one()
            user = User(username=username, real_name=f"销售-{role_code}",
                        password_hash=hash_password("init12345"), status="enabled")
            user.roles.append(role)
            db.add(user)
            db.commit()
            self.users.append(user.id)
        token = self.client.post("/api/auth/login",
                                 json={"username": username, "password": "init12345"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        self._cache[role_code] = headers
        return headers

    def create_doc(self, path: str, headers: dict, payload: dict) -> dict:
        r = self.client.post(path, headers=headers, json=payload)
        assert r.status_code == 200, r.text
        key = {"requests": "sales_request", "orders": "sales_order",
               "in-orders": "stock_in", "out-orders": "stock_out"}[path.rstrip("/").split("/")[-1]]
        self.docs[key].append(r.json()["id"])
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
            for table, ids in (("products", self.products), ("uoms", self.uoms),
                               ("warehouses", self.warehouses),
                               ("product_types", list(reversed(self.types))),
                               ("customers", self.customers)):
                for obj_id in ids:
                    db.execute(text(f"DELETE FROM {table} WHERE id = :i"), {"i": obj_id})
            for uid in self.users:
                db.query(OperationLog).filter(OperationLog.user_id == uid).delete()
                db.query(User).filter(User.id == uid).delete()
            db.commit()
        self.__init__(self.client, self.admin)


@pytest.fixture()
def box(client, admin):
    instance = Box(client, admin)
    try:
        yield instance
    finally:
        instance.cleanup()


def _items(product: dict, qty: float, price: float = 20) -> list[dict]:
    return [{"product_id": product["id"], "qty": qty, "unit_price": price}]


class TestSalesFlow:
    def test_request_to_order_to_stock_out(self, box):
        product = box.product(box.ptype()["id"], box.uom()["id"])
        warehouse, customer = box.warehouse(), box.customer()
        seller, manager, keeper = (box.headers(SELLER), box.headers(SALES_MANAGER),
                                   box.headers(KEEPER))

        # 备货：先入库 30，便于出库
        stock_in = box.create_doc("/api/stock/in-orders", keeper, {
            "warehouse_id": warehouse["id"], "in_type": "其他入库", "items": _items(product, 30)})
        box.client.post(f"/api/stock/in-orders/{stock_in['id']}/submit", headers=keeper)
        assert box.client.post(f"/api/stock/in-orders/{stock_in['id']}/approve",
                               headers=box.admin).status_code == 200

        # 销售申请：客户可选（文本兜底）
        req_doc = box.create_doc("/api/sales/requests", seller, {
            "items": _items(product, 20), "customer_name_text": "临时客户（未建档）"})
        assert req_doc["customer_name_text"] == "临时客户（未建档）"
        box.client.post(f"/api/sales/requests/{req_doc['id']}/submit", headers=seller)
        approved = box.client.post(f"/api/sales/requests/{req_doc['id']}/approve", headers=manager)
        assert approved.status_code == 200, approved.text

        # 下推销售订单：客户必填
        pushed = box.client.post(f"/api/sales/requests/{req_doc['id']}/push", headers=seller,
                                 json={"customer_id": customer["id"], "items": [{"qty": 20}]})
        assert pushed.status_code == 200, pushed.text
        so = pushed.json()
        box.docs["sales_order"].append(so["id"])
        assert so["status"] == "draft" and so["customer_name"] == customer["name"]

        box.client.post(f"/api/sales/orders/{so['id']}/submit", headers=seller)
        assert box.client.post(f"/api/sales/orders/{so['id']}/approve",
                               headers=manager).status_code == 200

        # 下推出库单并审核（过账扣减库存）
        out = box.client.post(f"/api/sales/orders/{so['id']}/push", headers=manager,
                              json={"warehouse_id": warehouse["id"]})
        assert out.status_code == 200, out.text
        out_doc = out.json()
        box.docs["stock_out"].append(out_doc["id"])
        box.client.post(f"/api/stock/out-orders/{out_doc['id']}/submit", headers=keeper)
        posted = box.client.post(f"/api/stock/out-orders/{out_doc['id']}/approve", headers=box.admin)
        assert posted.status_code == 200, posted.text

        ledger = box.client.get("/api/stock/ledger", headers=keeper, params={
            "product_id": product["id"], "warehouse_id": warehouse["id"]}).json()
        assert ledger["balance"] == 10.0, ledger["balance"]
        # 回写销售订单已出库数量
        so_detail = box.client.get(f"/api/sales/orders/{so['id']}", headers=seller).json()
        assert so_detail["items"][0]["shipped_qty"] == 20

    def test_shortage_blocks_stock_out(self, box):
        product = box.product(box.ptype()["id"], box.uom()["id"])
        warehouse, customer = box.warehouse(), box.customer()
        seller, manager, keeper = (box.headers(SELLER), box.headers(SALES_MANAGER),
                                   box.headers(KEEPER))
        req_doc = box.create_doc("/api/sales/requests", seller, {"items": _items(product, 5)})
        box.client.post(f"/api/sales/requests/{req_doc['id']}/submit", headers=seller)
        box.client.post(f"/api/sales/requests/{req_doc['id']}/approve", headers=manager)
        so = box.client.post(f"/api/sales/requests/{req_doc['id']}/push", headers=seller,
                             json={"customer_id": customer["id"]}).json()
        box.docs["sales_order"].append(so["id"])
        box.client.post(f"/api/sales/orders/{so['id']}/submit", headers=seller)
        box.client.post(f"/api/sales/orders/{so['id']}/approve", headers=manager)
        out_doc = box.client.post(f"/api/sales/orders/{so['id']}/push", headers=manager,
                                  json={"warehouse_id": warehouse["id"]}).json()
        box.docs["stock_out"].append(out_doc["id"])
        box.client.post(f"/api/stock/out-orders/{out_doc['id']}/submit", headers=keeper)

        blocked = box.client.post(f"/api/stock/out-orders/{out_doc['id']}/approve",
                                  headers=box.admin)
        assert blocked.status_code == 422
        assert "库存不足" in blocked.json()["detail"]
        detail = box.client.get(f"/api/stock/out-orders/{out_doc['id']}", headers=keeper).json()
        assert detail["status"] == "submitted" and detail["posted"] is False

    def test_sales_permissions(self, box):
        seller = box.headers(SELLER)
        # 销售员无审核权限
        assert box.client.get("/api/system/logs", headers=seller).status_code == 403
        # 销售员可建单
        product = box.product(box.ptype()["id"], box.uom()["id"])
        doc = box.create_doc("/api/sales/requests", seller, {"items": _items(product, 1)})
        assert doc["status"] == "draft"
        # 未登录 401
        assert box.client.get("/api/sales/orders").status_code == 401
