"""T-V2-17~23 测试：单据公共层、采购线、库存过账、盘点。

对应验收场景：
- AC-V2-13 采购申请提交与审核；AC-V2-14 驳回回草稿；AC-V2-15 创建人不可自审；AC-V2-17 作废留痕
- AC-V2-16 申请下推采购单（剩余量约束）；AC-V2-18 已入库数量回写
- AC-V2-19 入库过账；AC-V2-20 出库过账；AC-V2-21 负库存拦截；AC-V2-22 反审核红冲；
  AC-V2-23 过账幂等；AC-V2-24 有下游禁止反审核；AC-V2-26 结存与流水一致
- AC-V2-27/28/29 盘点全盘生成行项、差异调整自动生成盘盈/盘亏单

测试自建主数据、账号与单据，结束时按依赖顺序清理。
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
from app.models_doc import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseRequest,
    PurchaseRequestItem,
    StockInOrder,
    StockInOrderItem,
    StockOutOrder,
    StockOutOrderItem,
    StockTake,
    StockTakeItem,
)
from app.models_master import Customer, Product, ProductType, Supplier, Uom, Warehouse
from app.models_stock import Stock, StockLedger
from app.security import hash_password

BUYER, MANAGER, KEEPER = "buyer", "purchase_manager", "keeper"


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
    """主数据 + 账号 + 单据工厂，负责依赖顺序清理。"""

    def __init__(self, client, admin_h):
        self.client = client
        self.admin = admin_h
        self.users: list[int] = []
        self.products: list[int] = []
        self.types: list[int] = []
        self.uoms: list[int] = []
        self.warehouses: list[int] = []
        self.suppliers: list[int] = []
        self.customers: list[int] = []
        self.docs: dict[str, list[int]] = {k: [] for k in
                                           ("purchase_requests", "purchase_orders",
                                            "stock_in_orders", "stock_out_orders", "stock_takes")}
        self._token_cache: dict[str, dict] = {}

    # ---- 主数据 ----
    def uom(self, decimals: int = 2) -> dict:
        r = self.client.post("/api/master/uoms", headers=self.admin, json={
            "code": f"U{uuid.uuid4().hex[:5].upper()}", "name": f"单位{uuid.uuid4().hex[:4]}",
            "decimals": decimals})
        assert r.status_code == 200, r.text
        self.uoms.append(r.json()["id"])
        return r.json()

    def ptype(self, code: str | None = None) -> dict:
        r = self.client.post("/api/master/product-types", headers=self.admin, json={
            "name": f"类型{uuid.uuid4().hex[:5]}", "code": code or f"T{uuid.uuid4().hex[:3].upper()}"})
        assert r.status_code == 200, r.text
        self.types.append(r.json()["id"])
        return r.json()

    def product(self, *, ptype_id: int, uom_id: int, safety_stock=None) -> dict:
        payload = {"name": f"物料{uuid.uuid4().hex[:5]}", "product_type_id": ptype_id,
                   "uom_id": uom_id, "default_price": 10}
        if safety_stock is not None:
            payload["safety_stock"] = safety_stock
        r = self.client.post("/api/master/products", headers=self.admin, json=payload)
        assert r.status_code == 200, r.text
        self.products.append(r.json()["id"])
        return r.json()

    def warehouse(self) -> dict:
        r = self.client.post("/api/master/warehouses", headers=self.admin, json={
            "code": f"W{uuid.uuid4().hex[:5].upper()}", "name": f"仓库{uuid.uuid4().hex[:4]}"})
        assert r.status_code == 200, r.text
        self.warehouses.append(r.json()["id"])
        return r.json()

    def supplier(self) -> dict:
        r = self.client.post("/api/master/suppliers", headers=self.admin,
                             json={"name": f"供应商{uuid.uuid4().hex[:5]}"})
        assert r.status_code == 200, r.text
        self.suppliers.append(r.json()["id"])
        return r.json()

    def customer(self) -> dict:
        r = self.client.post("/api/master/customers", headers=self.admin,
                             json={"name": f"客户{uuid.uuid4().hex[:5]}"})
        assert r.status_code == 200, r.text
        self.customers.append(r.json()["id"])
        return r.json()

    # ---- 账号 ----
    def headers(self, role_code: str) -> dict:
        if role_code in self._token_cache:
            return self._token_cache[role_code]
        username = f"doc_{role_code[:6]}_{uuid.uuid4().hex[:6]}"
        with SessionLocal() as db:
            role = db.query(Role).filter(Role.code == role_code).one()
            user = User(username=username, real_name=f"单据-{role_code}",
                        password_hash=hash_password("init12345"), status="enabled")
            user.roles.append(role)
            db.add(user)
            db.commit()
            self.users.append(user.id)
        token = self.client.post("/api/auth/login",
                                 json={"username": username, "password": "init12345"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        self._token_cache[role_code] = headers
        return headers

    # ---- 单据 ----
    def create_doc(self, path: str, headers: dict, payload: dict) -> dict:
        r = self.client.post(path, headers=headers, json=payload)
        assert r.status_code == 200, r.text
        key = path.rstrip("/").split("/")[-1]
        table = {"requests": "purchase_requests", "orders": "purchase_orders",
                 "in-orders": "stock_in_orders", "out-orders": "stock_out_orders",
                 "takes": "stock_takes"}[key]
        self.docs[table].append(r.json()["id"])
        return r.json()

    def cleanup(self) -> None:
        from sqlalchemy import text

        with SessionLocal() as db:
            for table, ids in self.docs.items():
                for doc_id in ids:
                    db.execute(text(f"DELETE FROM {table} WHERE id = :i"), {"i": doc_id})
            product_ids = self.products or []
            for pid in product_ids:
                db.execute(text("DELETE FROM stock_ledger WHERE product_id = :i"), {"i": pid})
                db.execute(text("DELETE FROM stocks WHERE product_id = :i"), {"i": pid})
            for wid in self.warehouses:
                db.execute(text("DELETE FROM stock_ledger WHERE warehouse_id = :i"), {"i": wid})
                db.execute(text("DELETE FROM stocks WHERE warehouse_id = :i"), {"i": wid})
            for table in ("products", "uoms", "warehouses", "product_types", "suppliers", "customers"):
                ids = {"products": self.products, "uoms": self.uoms, "warehouses": self.warehouses,
                       "product_types": self.types, "suppliers": self.suppliers,
                       "customers": self.customers}[table]
                for obj_id in ids:
                    db.execute(text(f"DELETE FROM {table} WHERE id = :i"), {"i": obj_id})
            # 单据变更历史（object_type 为单据类型）
            db.query(ChangeLog).filter(ChangeLog.object_type.in_(
                ["purchase_request", "purchase_order", "stock_in", "stock_out", "stock_take"]
            )).delete(synchronize_session=False)
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


def _req_items(box: Box, product: dict, qty: float, price: float = 10) -> list[dict]:
    return [{"product_id": product["id"], "qty": qty, "unit_price": price}]


def _approve(client, path: str, doc_id: int, headers: dict, expect=200):
    return client.post(f"{path}/{doc_id}/approve", headers=headers)


# ===================== AC-V2-13/14/15/17 采购申请单 =====================

class TestPurchaseRequestFlow:
    def test_create_submit_approve(self, box):
        product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
        buyer, manager = box.headers(BUYER), box.headers(MANAGER)
        doc = box.create_doc("/api/purchase/requests", buyer, {
            "doc_date": "2026-01-05", "purpose": "测试采购",
            "items": _req_items(box, product, 100)})
        assert doc["status"] == "draft" and doc["total_amount"] == 1000.0
        assert doc["doc_no"].startswith("PR202601"), doc["doc_no"]

        sent = box.client.post(f"/api/purchase/requests/{doc['id']}/submit", headers=buyer)
        assert sent.status_code == 200 and sent.json()["status"] == "submitted"

        # AC-V2-15：审核权限与创建人分离（buyer 无审核权限 → 403；manager 可审核）
        denied = _approve(box.client, "/api/purchase/requests", doc["id"], buyer)
        assert denied.status_code == 403, "采购员无审核权限"

        ok = _approve(box.client, "/api/purchase/requests", doc["id"], manager)
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "approved"

        logs = box.client.get(f"/api/purchase/requests/{doc['id']}/changelogs",
                              headers=manager).json()
        assert any(lg["field_name"] == "status" and lg["new_value"] == "submitted" for lg in logs)
        assert any(lg["operator_name"] for lg in logs), "变更历史应带操作人"

    def test_self_approve_rejected(self, box):
        """AC-V2-15：同一账号既是创建人又有审核权限时被拒。"""
        product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
        manager = box.headers(MANAGER)
        doc = box.create_doc("/api/purchase/requests", manager, {
            "items": _req_items(box, product, 10)})
        box.client.post(f"/api/purchase/requests/{doc['id']}/submit", headers=manager)
        resp = _approve(box.client, "/api/purchase/requests", doc["id"], manager)
        assert resp.status_code == 422
        assert "自己创建" in resp.json()["detail"]

    def test_reject_returns_to_draft(self, box):
        product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
        buyer, manager = box.headers(BUYER), box.headers(MANAGER)
        doc = box.create_doc("/api/purchase/requests", buyer, {"items": _req_items(box, product, 5)})
        box.client.post(f"/api/purchase/requests/{doc['id']}/submit", headers=buyer)
        resp = box.client.post(f"/api/purchase/requests/{doc['id']}/reject", headers=manager,
                               json={"reason": "数量需要调整"})
        assert resp.status_code == 200 and resp.json()["status"] == "draft"
        logs = box.client.get(f"/api/purchase/requests/{doc['id']}/changelogs", headers=manager).json()
        assert any("数量需要调整" in (lg["note"] or "") for lg in logs)

    def test_void_hidden_from_default_list(self, box):
        product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
        buyer, manager = box.headers(BUYER), box.headers(MANAGER)
        doc = box.create_doc("/api/purchase/requests", buyer, {"items": _req_items(box, product, 3)})
        # 采购员无作废权限（purchase.request.void）→ 403；主管可作废
        assert box.client.post(f"/api/purchase/requests/{doc['id']}/void", headers=buyer,
                               json={"reason": "x"}).status_code == 403
        resp = box.client.post(f"/api/purchase/requests/{doc['id']}/void", headers=manager,
                               json={"reason": "重复录入"})
        assert resp.status_code == 200 and resp.json()["status"] == "voided"

        listed = box.client.get("/api/purchase/requests", headers=box.admin,
                                params={"keyword": doc["doc_no"]}).json()
        assert listed["total"] == 0, "作废单据默认不进列表（AC-V2-17）"
        listed = box.client.get("/api/purchase/requests", headers=box.admin,
                                params={"keyword": doc["doc_no"], "include_voided": True}).json()
        assert listed["total"] == 1

    def test_submitted_doc_not_editable(self, box):
        product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
        buyer = box.headers(BUYER)
        doc = box.create_doc("/api/purchase/requests", buyer, {"items": _req_items(box, product, 3)})
        box.client.post(f"/api/purchase/requests/{doc['id']}/submit", headers=buyer)
        resp = box.client.put(f"/api/purchase/requests/{doc['id']}", headers=buyer,
                              json={"purpose": "改一下"})
        assert resp.status_code == 422

    def test_qty_decimals_checked_against_uom(self, box):
        """AC-V2-11：单位为"个"（小数位 0）时不允许 1.5。"""
        ptype = box.ptype()
        uom_int = box.uom(decimals=0)
        product = box.product(ptype_id=ptype["id"], uom_id=uom_int["id"])
        buyer = box.headers(BUYER)
        resp = box.client.post("/api/purchase/requests", headers=buyer, json={
            "items": [{"product_id": product["id"], "qty": 1.5, "unit_price": 1}]})
        assert resp.status_code == 422
        assert "不支持小数" in resp.json()["detail"]


# ===================== AC-V2-16/18 下推 =====================

class TestPush:
    def _approved_request(self, box, qty=100):
        product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
        buyer, manager = box.headers(BUYER), box.headers(MANAGER)
        doc = box.create_doc("/api/purchase/requests", buyer, {"items": _req_items(box, product, qty)})
        box.client.post(f"/api/purchase/requests/{doc['id']}/submit", headers=buyer)
        _approve(box.client, "/api/purchase/requests", doc["id"], manager)
        return doc, product, buyer, manager

    def test_partial_push_and_remaining_guard(self, box):
        doc, product, buyer, manager = self._approved_request(box, 100)
        supplier = box.supplier()
        item_id = doc["items"][0]["id"]

        pushed = box.client.post(f"/api/purchase/requests/{doc['id']}/push", headers=buyer, json={
            "supplier_id": supplier["id"],
            "items": [{"src_item_id": item_id, "qty": 60}]})
        assert pushed.status_code == 200, pushed.text
        po = pushed.json()
        box.docs["purchase_orders"].append(po["id"])
        assert po["status"] == "draft" and po["source_doc_no"] == doc["doc_no"]
        assert po["items"][0]["qty"] == 60

        detail = box.client.get(f"/api/purchase/requests/{doc['id']}", headers=buyer).json()
        assert detail["items"][0]["ordered_qty"] == 60, "申请单应记录已下单 60"

        over = box.client.post(f"/api/purchase/requests/{doc['id']}/push", headers=buyer, json={
            "supplier_id": supplier["id"], "items": [{"src_item_id": item_id, "qty": 50}]})
        assert over.status_code == 422
        assert "可下推数量不足" in over.json()["detail"]

        rest = box.client.post(f"/api/purchase/requests/{doc['id']}/push", headers=buyer,
                               json={"supplier_id": supplier["id"]})
        assert rest.status_code == 200, rest.text
        box.docs["purchase_orders"].append(rest.json()["id"])
        assert rest.json()["items"][0]["qty"] == 40, "默认下推剩余 40"

    def test_stock_in_backfills_received_qty(self, box):
        doc, product, buyer, manager = self._approved_request(box, 100)
        supplier, warehouse = box.supplier(), box.warehouse()
        pushed = box.client.post(f"/api/purchase/requests/{doc['id']}/push", headers=buyer,
                                 json={"supplier_id": supplier["id"]}).json()
        box.docs["purchase_orders"].append(pushed["id"])
        po_id = pushed["id"]
        box.client.post(f"/api/purchase/orders/{po_id}/submit", headers=manager)
        _approve(box.client, "/api/purchase/orders", po_id, manager)

        stock_in = box.client.post(f"/api/purchase/orders/{po_id}/push", headers=manager, json={
            "warehouse_id": warehouse["id"], "items": [{"qty": 40}]})
        assert stock_in.status_code == 200, stock_in.text
        si = stock_in.json()
        box.docs["stock_in_orders"].append(si["id"])
        assert si["items"][0]["qty"] == 40 and si["source_doc_no"] == pushed["doc_no"]

        keeper = box.headers(KEEPER)
        submitted = box.client.post(f"/api/stock/in-orders/{si['id']}/submit", headers=keeper)
        assert submitted.status_code == 200, submitted.text
        ok = _approve(box.client, "/api/stock/in-orders", si["id"], box.admin)
        assert ok.status_code == 200, ok.text

        po_detail = box.client.get(f"/api/purchase/orders/{po_id}", headers=buyer).json()
        assert po_detail["items"][0]["received_qty"] == 40, "AC-V2-18：入库后回写已入库数量"


# ===================== AC-V2-19~26 库存过账 =====================

class TestStockPosting:
    def _setup(self, box):
        product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
        warehouse = box.warehouse()
        keeper = box.headers(KEEPER)
        return product, warehouse, keeper

    def _stock_in(self, box, keeper, product, warehouse, qty):
        doc = box.create_doc("/api/stock/in-orders", keeper, {
            "warehouse_id": warehouse["id"], "in_type": "其他入库",
            "items": _req_items(box, product, qty)})
        box.client.post(f"/api/stock/in-orders/{doc['id']}/submit", headers=keeper)
        resp = _approve(box.client, "/api/stock/in-orders", doc["id"], box.admin)
        assert resp.status_code == 200, resp.text
        return doc

    def _stock_out(self, box, keeper, product, warehouse, qty, approve=True):
        doc = box.create_doc("/api/stock/out-orders", keeper, {
            "warehouse_id": warehouse["id"], "out_type": "其他出库",
            "items": _req_items(box, product, qty)})
        box.client.post(f"/api/stock/out-orders/{doc['id']}/submit", headers=keeper)
        if approve:
            return doc, _approve(box.client, "/api/stock/out-orders", doc["id"], box.admin)
        return doc, None

    def _balance(self, box, product_id, warehouse_id, headers) -> float:
        data = box.client.get("/api/stock/ledger", headers=headers,
                              params={"product_id": product_id, "warehouse_id": warehouse_id}).json()
        return data["balance"]

    def test_in_then_out_updates_balance_and_ledger(self, box):
        product, warehouse, keeper = self._setup(box)
        self._stock_in(box, keeper, product, warehouse, 10)
        assert self._balance(box, product["id"], warehouse["id"], keeper) == 10.0

        ledger = box.client.get("/api/stock/ledger", headers=keeper, params={
            "product_id": product["id"], "warehouse_id": warehouse["id"]}).json()
        assert ledger["total"] == 1 and ledger["items"][0]["qty_change"] == 10.0
        assert ledger["items"][0]["qty_after"] == 10.0

        self._stock_out(box, keeper, product, warehouse, 4)
        assert self._balance(box, product["id"], warehouse["id"], keeper) == 6.0

        balances = box.client.get("/api/stock/balances", headers=keeper).json()
        row = next(b for b in balances["items"] if b["product_id"] == product["id"])
        assert row["qty"] == 6.0

    def test_negative_stock_blocked(self, box):
        """AC-V2-21：库存不足时审核被拦截，库存与单据状态都不变。"""
        product, warehouse, keeper = self._setup(box)
        self._stock_in(box, keeper, product, warehouse, 4)
        doc, resp = self._stock_out(box, keeper, product, warehouse, 5)
        assert resp.status_code == 422
        assert "库存不足" in resp.json()["detail"]
        assert self._balance(box, product["id"], warehouse["id"], keeper) == 4.0
        detail = box.client.get(f"/api/stock/out-orders/{doc['id']}", headers=keeper).json()
        assert detail["status"] == "submitted" and detail["posted"] is False

    def test_idempotent_approve(self, box):
        """AC-V2-23：重复审核不产生第二条流水。"""
        product, warehouse, keeper = self._setup(box)
        doc = self._stock_in(box, keeper, product, warehouse, 10)
        again = _approve(box.client, "/api/stock/in-orders", doc["id"], box.admin)
        assert again.status_code == 200
        ledger = box.client.get("/api/stock/ledger", headers=keeper, params={
            "product_id": product["id"], "warehouse_id": warehouse["id"]}).json()
        assert ledger["total"] == 1, "重复审核不得重复过账"
        assert self._balance(box, product["id"], warehouse["id"], keeper) == 10.0

    def test_unapprove_reverses_stock(self, box):
        """AC-V2-22：反审核红冲，结存回退且保留原流水。"""
        product, warehouse, keeper = self._setup(box)
        doc = self._stock_in(box, keeper, product, warehouse, 10)
        resp = box.client.post(f"/api/stock/in-orders/{doc['id']}/unapprove", headers=box.admin,
                               json={"reason": "供应商取消发货"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "submitted" and resp.json()["posted"] is False
        assert self._balance(box, product["id"], warehouse["id"], keeper) == 0.0

        ledger = box.client.get("/api/stock/ledger", headers=keeper, params={
            "product_id": product["id"], "warehouse_id": warehouse["id"]}).json()
        assert ledger["total"] == 2
        assert ledger["items"][0]["qty_change"] == -10.0
        assert ledger["items"][0]["biz_type"].startswith("红冲-")

    def test_downstream_blocks_unapprove(self, box):
        """AC-V2-24：存在下游入库单时禁止反审核采购单。"""
        product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
        warehouse, supplier = box.warehouse(), box.supplier()
        buyer, manager = box.headers(BUYER), box.headers(MANAGER)
        doc = box.create_doc("/api/purchase/requests", buyer, {"items": _req_items(box, product, 20)})
        box.client.post(f"/api/purchase/requests/{doc['id']}/submit", headers=buyer)
        _approve(box.client, "/api/purchase/requests", doc["id"], manager)
        po = box.client.post(f"/api/purchase/requests/{doc['id']}/push", headers=buyer,
                             json={"supplier_id": supplier["id"]}).json()
        box.docs["purchase_orders"].append(po["id"])
        box.client.post(f"/api/purchase/orders/{po['id']}/submit", headers=manager)
        _approve(box.client, "/api/purchase/orders", po["id"], manager)
        si = box.client.post(f"/api/purchase/orders/{po['id']}/push", headers=manager,
                             json={"warehouse_id": warehouse["id"]}).json()
        box.docs["stock_in_orders"].append(si["id"])

        resp = box.client.post(f"/api/purchase/orders/{po['id']}/unapprove", headers=manager,
                               json={"reason": "想改价格"})
        assert resp.status_code == 422
        assert "下游" in resp.json()["detail"]

    def test_recalc_consistent(self, box):
        """AC-V2-26：结存 == 流水累计。"""
        product, warehouse, keeper = self._setup(box)
        self._stock_in(box, keeper, product, warehouse, 7)
        self._stock_out(box, keeper, product, warehouse, 2)
        result = box.client.post("/api/stock/recalc", headers=keeper).json()
        assert result["consistent"] is True and result["mismatch_count"] == 0


# ===================== AC-V2-27~29 盘点 =====================

class TestStockTake:
    def _prepare(self, box, qty=10):
        product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
        warehouse, keeper = box.warehouse(), box.headers(KEEPER)
        doc = box.create_doc("/api/stock/in-orders", keeper, {
            "warehouse_id": warehouse["id"], "in_type": "其他入库",
            "items": _req_items(box, product, qty)})
        box.client.post(f"/api/stock/in-orders/{doc['id']}/submit", headers=keeper)
        _approve(box.client, "/api/stock/in-orders", doc["id"], box.admin)
        return product, warehouse, keeper

    def _new_take(self, box, keeper, warehouse, take_type="full"):
        take = box.create_doc("/api/stock/takes", keeper, {
            "warehouse_id": warehouse["id"], "take_type": take_type})
        resp = box.client.post(f"/api/stock/takes/{take['id']}/generate", headers=keeper, json={})
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_generate_items_from_balance(self, box):
        """AC-V2-27：全盘按当前结存生成行项，账面数量只读。"""
        product, warehouse, keeper = self._prepare(box, 10)
        take = self._new_take(box, keeper, warehouse)
        assert len(take["items"]) >= 1
        row = next(i for i in take["items"] if i["product_id"] == product["id"])
        assert row["book_qty"] == 10.0 and row["actual_qty"] == 10.0 and row["diff_qty"] == 0.0

    def test_shortage_generates_out_doc(self, box):
        """AC-V2-28：盘亏自动生成盘亏出库单并过账，结存变为实盘数。"""
        product, warehouse, keeper = self._prepare(box, 10)
        take = self._new_take(box, keeper, warehouse)
        row = next(i for i in take["items"] if i["product_id"] == product["id"])
        counted = box.client.put(f"/api/stock/takes/{take['id']}/count", headers=keeper, json={
            "counts": [{"id": row["id"], "actual_qty": 8, "diff_reason": "破损 2 件"}]})
        assert counted.status_code == 200, counted.text
        row = next(i for i in counted.json()["items"] if i["id"] == row["id"])
        assert row["diff_qty"] == -2.0

        box.client.post(f"/api/stock/takes/{take['id']}/submit", headers=keeper)
        ok = _approve(box.client, "/api/stock/takes", take["id"], box.admin)
        assert ok.status_code == 200, ok.text
        data = ok.json()
        assert data["generated_out_no"], "应生成盘亏出库单"
        assert data["generated_out_id"]
        box.docs["stock_out_orders"].append(data["generated_out_id"])

        ledger = box.client.get("/api/stock/ledger", headers=keeper, params={
            "product_id": product["id"], "warehouse_id": warehouse["id"]}).json()
        assert ledger["balance"] == 8.0
        assert any(r["biz_type"] == "盘亏出库" for r in ledger["items"])

    def test_surplus_generates_in_doc(self, box):
        """AC-V2-29：盘盈自动生成盘盈入库单并过账。"""
        product, warehouse, keeper = self._prepare(box, 10)
        take = self._new_take(box, keeper, warehouse)
        row = next(i for i in take["items"] if i["product_id"] == product["id"])
        box.client.put(f"/api/stock/takes/{take['id']}/count", headers=keeper, json={
            "counts": [{"id": row["id"], "actual_qty": 12}]})
        box.client.post(f"/api/stock/takes/{take['id']}/submit", headers=keeper)
        ok = _approve(box.client, "/api/stock/takes", take["id"], box.admin)
        assert ok.status_code == 200, ok.text
        assert ok.json()["generated_in_no"], "应生成盘盈入库单"
        box.docs["stock_in_orders"].append(ok.json()["generated_in_id"])
        ledger = box.client.get("/api/stock/ledger", headers=keeper, params={
            "product_id": product["id"], "warehouse_id": warehouse["id"]}).json()
        assert ledger["balance"] == 12.0
        assert any(r["biz_type"] == "盘盈入库" for r in ledger["items"])

    def test_partial_take_by_product(self, box):
        """AC-V2-30（抽盘）：按指定物料生成行项，仅该物料进入盘点行。"""
        product, warehouse, keeper = self._prepare(box, 5)
        other = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
        other_in = box.create_doc("/api/stock/in-orders", keeper, {
            "warehouse_id": warehouse["id"], "in_type": "其他入库",
            "items": _req_items(box, other, 3)})
        box.client.post(f"/api/stock/in-orders/{other_in['id']}/submit", headers=keeper)
        _approve(box.client, "/api/stock/in-orders", other_in["id"], box.admin)

        take = box.create_doc("/api/stock/takes", keeper, {
            "warehouse_id": warehouse["id"], "take_type": "partial"})
        resp = box.client.post(f"/api/stock/takes/{take['id']}/generate", headers=keeper,
                               json={"product_ids": [other["id"]]})
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        assert items and all(i["product_id"] == other["id"] for i in items)
        assert items[0]["book_qty"] == 3.0


# ===================== 权限与数据范围 =====================

class TestDocPermissions:
    def test_buyer_cannot_approve_or_touch_stock(self, box):
        buyer = box.headers(BUYER)
        assert box.client.get("/api/stock/in-orders", headers=buyer).status_code == 403
        assert box.client.post("/api/stock/balances", headers=buyer).status_code in (403, 405)
        resp = box.client.get("/api/stock/balances", headers=buyer)
        assert resp.status_code == 200, "采购员有库存查看权限"

    def test_unauthenticated_denied(self, client):
        assert client.get("/api/purchase/requests").status_code == 401
        assert client.get("/api/stock/balances").status_code == 401
        assert client.post("/api/stock/recalc").status_code == 401

    def test_self_scope_isolation(self, box):
        """数据范围 SELF：采购员只看到自己创建的单据。"""
        product = box.product(ptype_id=box.ptype()["id"], uom_id=box.uom()["id"])
        buyer, manager = box.headers(BUYER), box.headers(MANAGER)
        mine = box.create_doc("/api/purchase/requests", buyer, {"items": _req_items(box, product, 1)})
        theirs = box.create_doc("/api/purchase/requests", manager, {"items": _req_items(box, product, 1)})

        listed = box.client.get("/api/purchase/requests", headers=buyer,
                                params={"keyword": mine["doc_no"]}).json()
        assert listed["total"] == 1
        blocked = box.client.get(f"/api/purchase/requests/{theirs['id']}", headers=buyer)
        assert blocked.status_code == 403, "越范围详情应被拒绝"
