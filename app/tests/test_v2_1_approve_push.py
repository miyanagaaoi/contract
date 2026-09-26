"""V2.1 / T-V2.1-06 · 07 · 09 测试。

覆盖：
- **自审例外**（修订 AC-V2-15，BR-V2.1-05）：初始管理员可自审并留痕；非管理员仍被拒；
  系统参数 `allow_self_approve` 开启时按 V2.0 原语义放行；
- **下推归零**（BR-V2.1-06，AC-V2.1-07/08）：全部行项下推完毕后申请单自动"已完成"，
  列表返回 `remain_qty_sum` 供按钮显隐；部分下推不置完成；
- **采购单默认带出关联合同**（N10，AC-V2.1-10）。

说明：本文件以 **service 层白盒**为主，直接验证业务规则本身；HTTP 契约部分（列表字段、
权限）由既有 `test_v2_docs.py` 与 e2e 覆盖，避免重复样板。
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.dicts import set_sys_params
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_auth import Role, User
from app.models_doc import PurchaseRequest, PurchaseRequestItem
from app.models_master import Product, ProductType, Supplier, Uom
from app.security import hash_password
from app.services import doc_service, push_service

REQ_LIST = "/api/purchase/requests"


@pytest.fixture()
def db():
    with SessionLocal() as s:
        yield s


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


def _sfx() -> str:
    return uuid.uuid4().hex[:6]


# ---------------------------------------------------------------- 造数

def _mk_user(db, *, is_superadmin: bool = False, role_codes: tuple[str, ...] = ()) -> User:
    sfx = _sfx()
    user = User(username=f"u_{sfx}", real_name=f"用户{sfx}",
                password_hash=hash_password("pw12345678"), status="enabled",
                is_superadmin=is_superadmin, must_change_pwd=False)
    db.add(user)
    db.flush()
    if role_codes:
        user.roles = db.query(Role).filter(Role.code.in_(role_codes)).all()
    db.commit()
    return user


def _admin(db) -> User:
    """取**内置初始管理员**（`is_superadmin=True`）。

    ⚠️ 本文件**不得**新建 `is_superadmin=True` 的账号：那会破坏
    `test_v2_role_user.py::test_cannot_disable_last_superadmin` 所依赖的
    "最后一个超管"不变式（admin 不再是唯一超管 → 停用不再被拒）。
    """
    return db.query(User).filter(User.username == ADMIN_USERNAME).one()


def _mk_product(db) -> Product:
    sfx = _sfx()
    uom = Uom(code=f"U{sfx}", name=f"个{sfx}", decimals=0)
    db.add(uom)
    db.flush()
    ptype = ProductType(name=f"类型{sfx}")
    db.add(ptype)
    db.flush()
    product = Product(code=f"P{sfx}", name=f"物料{sfx}", spec="规格X",
                      product_type_id=ptype.id, uom_id=uom.id)
    db.add(product)
    db.commit()
    return product


def _mk_supplier(db) -> Supplier:
    sfx = _sfx()
    sup = Supplier(code=f"S{sfx}", name=f"供应商{sfx}")
    db.add(sup)
    db.commit()
    return sup


def _mk_request(db, creator: User, product: Product, *, qty="10", ordered="0",
                status="approved", contract_id=None) -> PurchaseRequest:
    sfx = _sfx()
    pr = PurchaseRequest(
        doc_no=f"PR{sfx}", doc_date=date.today(), status=status,
        created_by=creator.id, created_by_name=creator.real_name,
        contract_id=contract_id, contract_no=f"HT{sfx}" if contract_id else None,
    )
    db.add(pr)
    db.flush()
    pr.items.append(PurchaseRequestItem(
        seq=1, product_id=product.id, product_code=product.code, product_name=product.name,
        spec=product.spec, uom_name="个", uom_decimals=0,
        qty=Decimal(qty), ordered_qty=Decimal(ordered),
        unit_price=Decimal("5"), amount=Decimal(qty) * Decimal("5"),
    ))
    db.commit()
    return pr


def _notes(db, doc) -> str:
    return " | ".join((row.get("note") or "") for row in doc_service.list_logs(db, doc))


# ---------------------------------------------------------------- T-V2.1-06 自审例外

class TestSelfApprove:
    def test_初始管理员可自审并留痕(self, db):
        admin = _admin(db)
        pr = _mk_request(db, admin, _mk_product(db), status="submitted")

        doc_service.approve(db, pr, admin)
        db.commit()

        assert pr.status == "approved"
        assert "自审" in _notes(db, pr), "自审必须在变更历史中留痕（BR-V2.1-05）"

    def test_非管理员自审被拒(self, db):
        """修订后仍保留的原 AC-V2-15 语义：普通角色不得自审。"""
        buyer = _mk_user(db, role_codes=("buyer",))
        pr = _mk_request(db, buyer, _mk_product(db), status="submitted")

        with pytest.raises(ValueError, match="仅管理员可自审"):
            doc_service.approve(db, pr, buyer)
        assert pr.status == "submitted", "被拒后状态不得变化"

    def test_sysadmin角色可自审(self, db):
        """口径：`sysadmin`（系统管理员角色）**纳入**自审例外（业务方确认，`23` §13 第 6 项）。

        它与内置 `admin`（`is_superadmin=True`）在语义上同属"管理员"，只放开后者会造成
        "同为管理员却行为不一致"。普通业务角色（如 `buyer`）仍不得自审。
        """
        sysadmin = _mk_user(db, role_codes=("sysadmin",))
        pr = _mk_request(db, sysadmin, _mk_product(db), status="submitted")

        doc_service.approve(db, pr, sysadmin)
        db.commit()

        assert pr.status == "approved"
        assert "自审" in _notes(db, pr)

    def test_系统参数开启后非管理员可自审(self, db):
        """V2.0 既有参数语义保持有效（向后兼容，避免破坏既有行为）。"""
        buyer = _mk_user(db, role_codes=("buyer",))
        pr = _mk_request(db, buyer, _mk_product(db), status="submitted")

        set_sys_params(db, {"allow_self_approve": True})
        try:
            doc_service.approve(db, pr, buyer)
            assert pr.status == "approved"
        finally:
            set_sys_params(db, {"allow_self_approve": False})


# ---------------------------------------------------------------- T-V2.1-07 / 08 下推归零

class TestPushCompletion:
    def test_全量下推后自动置为已完成(self, db):
        admin = _admin(db)
        pr = _mk_request(db, admin, _mk_product(db), qty="10", ordered="0")
        sup = _mk_supplier(db)

        push_service.push_purchase_order(db, pr, admin, supplier_id=sup.id)
        db.commit()

        assert pr.items[0].ordered_qty == Decimal("10")
        assert pr.status == "completed", "全部行项下推完毕应自动置为已完成"
        assert "自动置为已完成" in _notes(db, pr)

    def test_部分下推不置为已完成(self, db):
        admin = _admin(db)
        pr = _mk_request(db, admin, _mk_product(db), qty="10", ordered="0")
        sup = _mk_supplier(db)

        push_service.push_purchase_order(
            db, pr, admin, supplier_id=sup.id,
            rows=[{"src_item_id": pr.items[0].id, "qty": 4}],
        )
        db.commit()

        assert pr.status == "approved", "仍有剩余可下推量，不应提前完成"
        assert push_service.remain_qty_sum(pr) == Decimal("6")

    def test_完成判定幂等(self, db):
        admin = _admin(db)
        pr = _mk_request(db, admin, _mk_product(db), qty="3", ordered="3")
        assert push_service.complete_if_fully_ordered(db, pr) is True
        assert push_service.complete_if_fully_ordered(db, pr) is False

    def test_无行项不误判完成(self, db):
        admin = _admin(db)
        sfx = _sfx()
        pr = PurchaseRequest(doc_no=f"PR{sfx}", doc_date=date.today(),
                             status="approved", created_by=admin.id)
        db.add(pr)
        db.commit()
        assert push_service.complete_if_fully_ordered(db, pr) is False
        assert pr.status == "approved"

    def test_列表返回剩余可下推量(self, client, h, db):
        """AC-V2.1-07：前端据 `remain_qty_sum` 决定是否显示「下推」。"""
        admin = _admin(db)
        pr = _mk_request(db, admin, _mk_product(db), qty="10", ordered="4")

        resp = client.get(REQ_LIST, headers=h, params={"keyword": pr.doc_no})
        assert resp.status_code == 200, resp.text
        row = next(r for r in resp.json()["items"] if r["doc_no"] == pr.doc_no)
        assert row["remain_qty_sum"] == 6.0


# ---------------------------------------------------------------- T-V2.1-09 合同带出

class TestContractCarryOver:
    def test_下推默认带出申请单的关联合同(self, client, h, db):
        # 合同必须是真实存在的档案：`change_logs.contract_id` 有外键约束
        contract = client.post("/api/contracts", headers=h, json={
            "name": f"V21合同_{_sfx()}", "type": "PUR", "subject_code": "ZC", "amount": 100,
        }).json()

        admin = _admin(db)
        pr = _mk_request(db, admin, _mk_product(db), qty="5", contract_id=contract["id"])
        sup = _mk_supplier(db)

        po = push_service.push_purchase_order(db, pr, admin, supplier_id=sup.id)
        db.commit()

        assert po.contract_id == contract["id"]
        assert po.contract_no == pr.contract_no

    def test_申请单无合同时采购单也不带(self, db):
        admin = _admin(db)
        pr = _mk_request(db, admin, _mk_product(db), qty="5")
        sup = _mk_supplier(db)

        po = push_service.push_purchase_order(db, pr, admin, supplier_id=sup.id)
        db.commit()

        assert po.contract_id is None


# ---------------------------------------------------------------- T-V2.1-01 经办人账号化

class TestHandlerAccount:
    def test_经办人下拉仅返回启用账号(self, client, h):
        resp = client.get("/api/master/options/user", headers=h)
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert rows, "下拉至少应包含内置 admin"
        assert all(r.get("id") and r.get("name") for r in rows)

    def test_新建单据默认经办人为当前账号并落姓名快照(self, client, h, db):
        product = _mk_product(db)
        resp = client.post(REQ_LIST, headers=h, json={
            "doc_date": "2026-03-01", "purpose": "T-V2.1-01",
            "items": [{"product_id": product.id, "qty": 1, "unit_price": 2}],
        })
        assert resp.status_code == 200, resp.text
        doc = resp.json()

        me = client.get("/api/auth/me", headers=h).json()["user"]
        assert doc["handler_user_id"] == me["id"], "经办人应默认当前账号（BR-V2.1-01）"
        assert doc["handler_name"] == me["real_name"], "应落姓名快照"

    def test_可改选其他账号并刷新快照(self, client, h, db):
        other = _mk_user(db, role_codes=("buyer",))
        product = _mk_product(db)
        resp = client.post(REQ_LIST, headers=h, json={
            "doc_date": "2026-03-01", "handler_user_id": other.id,
            "items": [{"product_id": product.id, "qty": 1, "unit_price": 2}],
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["handler_user_id"] == other.id
        assert resp.json()["handler_name"] == other.real_name

    def test_经办人不存在被拒(self, client, h, db):
        product = _mk_product(db)
        resp = client.post(REQ_LIST, headers=h, json={
            "doc_date": "2026-03-01", "handler_user_id": 99_999_999,
            "items": [{"product_id": product.id, "qty": 1, "unit_price": 2}],
        })
        assert resp.status_code == 422, resp.text
        assert "经办人不存在" in resp.text

    def test_停用账号从下拉中消失(self, client, h, db):
        user = _mk_user(db)
        before = client.get("/api/master/options/user", headers=h).json()
        assert any(r["id"] == user.id for r in before)

        with SessionLocal() as s:
            s.get(User, user.id).status = "disabled"
            s.commit()

        after = client.get("/api/master/options/user", headers=h).json()
        assert not any(r["id"] == user.id for r in after), "停用账号不应再出现在下拉中"
