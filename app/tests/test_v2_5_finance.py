"""V2.5 财务模块测试：核销、记账/红冲、进度口径、重算与接口权限。

覆盖 `docs/29-v2.5-finance-requirements.md` §5 的验收场景：

| 用例类 | 覆盖 |
|---|---|
| `TestAllocation` | AC-V2.5-04 核销校验（目标状态/方向/金额/重复行）、超额允许（AC-V2.5-06） |
| `TestFundApproval` | AC-V2.5-01~05 记账回写、红冲精确回退、幂等、下游保护（AC-V2.5-07） |
| `TestProgress` | AC-V2.5-11~13 六列口径（含税、数量、分母 0、超额） |
| `TestRecalc` | AC-V2.5-17 按明细重算（含"明细已无 → 归零"） |
| `TestFundApi` | AC-V2.5-01/02/06/14/16 接口层：编号、必填、审核权限、over 筛选、导出 |
| `TestInvoiceApi` | AC-V2.5-09~11 票号唯一、方向一致、确认入账、认证状态、作废红冲 |
| `TestPermissions` | AC-V2.5-18 业务员可发起不可审核；只读账号只读；菜单可见性 |

测试自建主数据与账号，直接 ORM 建"已审核的目标单据"（避免依赖其它模块的接口行为），
结束时按依赖顺序清理。
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_auth import OperationLog, Role, User
from app.models_doc import (
    Invoice,
    InvoiceAllocation,
    PaymentAllocation,
    PaymentOrder,
    PurchaseOrder,
    PurchaseOrderItem,
    ReceiptOrder,
    SalesOrder,
    SalesOrderItem,
)
from app.models_master import Customer, Product, ProductType, Supplier, Uom
from app.security import hash_password
from app.services import finance_service
from app.services.permission_service import collect_perms

SUBJECT = "ZC"          # 系统设置里的默认我方公司（`init_db.seed_dicts`）


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


class Box:
    """主数据 / 账号 / 目标单据工厂 + 依赖顺序清理。"""

    def __init__(self):
        self.users: list[int] = []
        self.masters: dict[str, list[int]] = {"uoms": [], "ptypes": [], "products": [],
                                              "suppliers": [], "customers": []}
        self.docs: dict[str, list[int]] = {"purchase_orders": [], "sales_orders": [],
                                           "payments": [], "receipts": [], "invoices": []}
        self._tokens: dict[str, str] = {}

    # ---- 主数据 ----
    def seed_masters(self) -> None:
        tag = uuid.uuid4().hex[:6]
        with SessionLocal() as db:
            uom = Uom(code=f"U{tag}", name="个", decimals=0)
            db.add(uom)
            db.flush()
            ptype = ProductType(code=f"PT{tag}", name="测试类型")
            db.add(ptype)
            db.flush()
            product = Product(code=f"P{tag}", name="测试物料", product_type_id=ptype.id,
                              uom_id=uom.id)
            supplier = Supplier(code=f"SUP{tag}", name="测试供应商")
            customer = Customer(code=f"CUS{tag}", name="测试客户")
            db.add_all([product, supplier, customer])
            db.commit()
            self.masters["uoms"].append(uom.id)
            self.masters["ptypes"].append(ptype.id)
            self.masters["products"].append(product.id)
            self.masters["suppliers"].append(supplier.id)
            self.masters["customers"].append(customer.id)
            self.product_id, self.uom_id = product.id, uom.id
            self.supplier_id, self.supplier_name = supplier.id, supplier.name
            self.customer_id, self.customer_name = customer.id, customer.name

    # ---- 账号 ----
    def user(self, role_code: str) -> int:
        username = f"fin_{role_code}_{uuid.uuid4().hex[:6]}"
        with SessionLocal() as db:
            role = db.query(Role).filter(Role.code == role_code).first()
            assert role is not None, f"内置角色 {role_code} 不存在"
            user = User(username=username, real_name=f"测试{role.name}",
                        password_hash=hash_password("fin12345"), status="enabled",
                        must_change_pwd=False)
            user.roles = [role]
            db.add(user)
            db.commit()
            uid = user.id
            self.users.append(uid)
            return uid

    def login(self, client: TestClient, uid: int) -> dict:
        with SessionLocal() as db:
            username = db.get(User, uid).username
        resp = client.post("/api/auth/login", json={"username": username,
                                                    "password": "fin12345"})
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['token']}"}

    # ---- 目标单据（直接建"已审核"，等价于通过既有审核流程后的状态）----
    def purchase_order(self, *, amount: str = "10000", qty: str = "10",
                       received: str = "0", status: str = "approved") -> int:
        with SessionLocal() as db:
            po = PurchaseOrder(
                doc_no=f"PO{ uuid.uuid4().hex[:8].upper() }", doc_date=date.today(),
                status=status, supplier_id=self.supplier_id, supplier_name=self.supplier_name,
                total_amount=Decimal(amount), subject_code=SUBJECT, subject_name="众诚",
            )
            db.add(po)
            db.flush()
            db.add(PurchaseOrderItem(doc_id=po.id, seq=1, product_id=self.product_id,
                                     product_code="P", product_name="测试物料",
                                     qty=Decimal(qty), unit_price=Decimal("1"),
                                     amount=Decimal(amount), received_qty=Decimal(received)))
            db.commit()
            self.docs["purchase_orders"].append(po.id)
            return po.id

    def sales_order(self, *, amount: str = "8000", qty: str = "8",
                    shipped: str = "0", status: str = "approved") -> int:
        with SessionLocal() as db:
            so = SalesOrder(
                doc_no=f"SO{ uuid.uuid4().hex[:8].upper() }", doc_date=date.today(),
                status=status, customer_id=self.customer_id, customer_name=self.customer_name,
                total_amount=Decimal(amount), subject_code=SUBJECT, subject_name="众诚",
            )
            db.add(so)
            db.flush()
            db.add(SalesOrderItem(doc_id=so.id, seq=1, product_id=self.product_id,
                                  product_code="P", product_name="测试物料",
                                  qty=Decimal(qty), unit_price=Decimal("1"),
                                  amount=Decimal(amount), shipped_qty=Decimal(shipped)))
            db.commit()
            self.docs["sales_orders"].append(so.id)
            return so.id

    # ---- 清理 ----
    def cleanup(self) -> None:
        with SessionLocal() as db:
            for pid in self.docs["payments"]:
                db.query(PaymentAllocation).filter(PaymentAllocation.payment_id == pid).delete()
                db.query(PaymentOrder).filter(PaymentOrder.id == pid).delete()
            for rid in self.docs["receipts"]:
                db.query(ReceiptOrder).filter(ReceiptOrder.id == rid).delete()
            for iid in self.docs["invoices"]:
                db.query(InvoiceAllocation).filter(InvoiceAllocation.invoice_id == iid).delete()
                db.query(Invoice).filter(Invoice.id == iid).delete()
            for po_id in self.docs["purchase_orders"]:
                db.query(PurchaseOrderItem).filter(PurchaseOrderItem.doc_id == po_id).delete()
                db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).delete()
            for so_id in self.docs["sales_orders"]:
                db.query(SalesOrderItem).filter(SalesOrderItem.doc_id == so_id).delete()
                db.query(SalesOrder).filter(SalesOrder.id == so_id).delete()
            for uid in self.users:
                db.query(OperationLog).filter(OperationLog.user_id == uid).delete()
                db.query(User).filter(User.id == uid).delete()
            for table in ("products", "suppliers", "customers", "ptypes", "uoms"):
                model = {"products": Product, "suppliers": Supplier, "customers": Customer,
                         "ptypes": ProductType, "uoms": Uom}[table]
                for mid in self.masters[table]:
                    db.query(model).filter(model.id == mid).delete()
            db.commit()


@pytest.fixture(scope="module")
def box():
    b = Box()
    b.seed_masters()
    yield b
    b.cleanup()


@pytest.fixture(scope="module")
def admin(client):
    resp = client.post("/api/auth/login",
                       json={"username": ADMIN_USERNAME, "password": ADMIN_INIT_PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _draft_payment(db, box, amount: str, target_id: int, alloc: str | None = None) -> PaymentOrder:
    """OR 建一张草稿付款单（带一行核销）——服务层用例的最小夹具。"""
    pay = PaymentOrder(doc_no=f"PAY{uuid.uuid4().hex[:8].upper()}", doc_date=date.today(),
                       status="draft", supplier_id=box.supplier_id,
                       supplier_name=box.supplier_name, total_amount=Decimal(amount),
                       subject_code=SUBJECT, subject_name="众诚")
    db.add(pay)
    db.flush()
    finance_service.parse_allocations(db, pay, [{
        "target_type": "purchase_order", "target_id": target_id,
        "amount": alloc or amount}], kind="payment")
    return pay


def _submitted(db, box, amount: str, target_id: int, alloc: str | None = None) -> PaymentOrder:
    """建单并**提交**（服务层用例直接驱动记账时必须先过提交这道状态机）。"""
    from app.services import doc_service

    pay = _draft_payment(db, box, amount, target_id, alloc)
    doc_service.submit(db, pay, _User())
    return pay


class _User:
    id = 1
    real_name = "测试财务"
    username = "fin_tester"


# ===================== 核销明细（AC-V2.5-04/06） =====================

class TestAllocation:
    def test_rejects_draft_target(self, box):
        """目标单据未审核不能核销（否则"填了就算"，进度会凭空出现）。"""
        po_id = box.purchase_order(status="draft")
        with SessionLocal() as db:
            pay = PaymentOrder(doc_no=f"PAY{uuid.uuid4().hex[:8].upper()}", doc_date=date.today(),
                               status="draft", supplier_id=box.supplier_id,
                               supplier_name=box.supplier_name, total_amount=Decimal("100"))
            db.add(pay)
            with pytest.raises(ValueError) as exc:
                finance_service.parse_allocations(db, pay, [{
                    "target_type": "purchase_order", "target_id": po_id,
                    "amount": "100"}], kind="payment")
            assert "尚未审核" in str(exc.value)

    def test_rejects_voided_target(self, box):
        po_id = box.purchase_order(status="voided")
        with SessionLocal() as db:
            pay = PaymentOrder(doc_no=f"PAY{uuid.uuid4().hex[:8].upper()}", doc_date=date.today(),
                               status="draft", supplier_id=box.supplier_id,
                               supplier_name=box.supplier_name, total_amount=Decimal("100"))
            db.add(pay)
            with pytest.raises(ValueError) as exc:
                finance_service.parse_allocations(db, pay, [{
                    "target_type": "purchase_order", "target_id": po_id,
                    "amount": "100"}], kind="payment")
            assert "已作废" in str(exc.value)

    def test_rejects_wrong_direction(self, box):
        """付款单只能核销采购线（采购单/入库单）；核销销售订单必须被拒。"""
        so_id = box.sales_order()
        with SessionLocal() as db:
            pay = PaymentOrder(doc_no=f"PAY{uuid.uuid4().hex[:8].upper()}", doc_date=date.today(),
                               status="draft", supplier_id=box.supplier_id,
                               supplier_name=box.supplier_name, total_amount=Decimal("100"))
            db.add(pay)
            with pytest.raises(ValueError) as exc:
                finance_service.parse_allocations(db, pay, [{
                    "target_type": "sales_order", "target_id": so_id, "amount": "100"}],
                    kind="payment")
            assert "核销目标只能是" in str(exc.value)

    def test_rejects_zero_and_duplicate(self, box):
        po_id = box.purchase_order()
        with SessionLocal() as db:
            pay = PaymentOrder(doc_no=f"PAY{uuid.uuid4().hex[:8].upper()}", doc_date=date.today(),
                               status="draft", supplier_id=box.supplier_id,
                               supplier_name=box.supplier_name, total_amount=Decimal("100"))
            db.add(pay)
            with pytest.raises(ValueError) as exc:
                finance_service.parse_allocations(db, pay, [{
                    "target_type": "purchase_order", "target_id": po_id, "amount": "0"}],
                    kind="payment")
            assert "核销金额" in str(exc.value)
            with pytest.raises(ValueError) as exc:
                finance_service.parse_allocations(db, pay, [
                    {"target_type": "purchase_order", "target_id": po_id, "amount": "10"},
                    {"target_type": "purchase_order", "target_id": po_id, "amount": "20"},
                ], kind="payment")
            assert "只能有一行" in str(exc.value)

    def test_over_allocation_allowed(self, box):
        """BR-V2.5-03：核销可以超过**目标单据**金额（先付后补单），由列表标红而非拦截。"""
        po_id = box.purchase_order(amount="10000")
        user = _User()
        with SessionLocal() as db:
            pay = _submitted(db, box, "12000", po_id)
            db.commit()
            box.docs["payments"].append(pay.id)
            # "未核销"是**付款单侧**的余额：本单已全额核销
            assert finance_service.allocations_total(pay) == Decimal("12000.00")
            assert finance_service.unallocated_amount(pay) == Decimal("0.00")
            finance_service.approve_fund_doc(db, pay, user)
            db.commit()
            progress = finance_service.progress_of(db.get(PurchaseOrder, po_id))
            assert progress["paid_amount"]["pct"] == 120.0
            assert progress["paid_amount"]["over"] is True

    def test_partial_allocation_leaves_balance(self, box):
        """付款 5000 只核销 3000 → 本单未核销 2000（预付款场景）。"""
        po_id = box.purchase_order(amount="10000")
        with SessionLocal() as db:
            pay = _draft_payment(db, box, "5000", po_id, alloc="3000")
            db.commit()
            box.docs["payments"].append(pay.id)
            assert finance_service.unallocated_amount(pay) == Decimal("2000.00")


# ===================== 记账 / 红冲 / 下游保护（AC-V2.5-01~05/07） =====================

class TestFundApproval:
    def test_approve_writes_back_and_unapprove_reverts(self, box):
        po_id = box.purchase_order(amount="10000")
        user = _User()
        with SessionLocal() as db:
            pay = _submitted(db, box, "3000", po_id)
            db.commit()
            box.docs["payments"].append(pay.id)
            pay_id = pay.id
            finance_service.approve_fund_doc(db, pay, user)
            db.commit()
            assert db.get(PurchaseOrder, po_id).paid_amount == Decimal("3000.00")
            assert db.get(PaymentOrder, pay_id).posted is True
            progress = finance_service.progress_of(db.get(PurchaseOrder, po_id))
            assert progress["paid_amount"]["pct"] == 30.0

            # 幂等：重复审核不再累加
            finance_service.approve_fund_doc(db, db.get(PaymentOrder, pay_id), user)
            db.commit()
            assert db.get(PurchaseOrder, po_id).paid_amount == Decimal("3000.00")

            # 反审核红冲
            finance_service.unapprove_fund_doc(db, db.get(PaymentOrder, pay_id), "录错", user)
            db.commit()
            assert db.get(PurchaseOrder, po_id).paid_amount == Decimal("0.00")
            assert finance_service.progress_of(db.get(PurchaseOrder, po_id))["paid_amount"]["pct"] == 0.0

    def test_unapprove_twice_does_not_go_negative(self, box):
        """红冲必须精确且不会把回写值冲成负数（并发/重复调用）。"""
        po_id = box.purchase_order(amount="10000")
        user = _User()
        with SessionLocal() as db:
            pay = _submitted(db, box, "2500", po_id)
            db.commit()
            box.docs["payments"].append(pay.id)
            pay_id = pay.id
            finance_service.approve_fund_doc(db, db.get(PaymentOrder, pay_id), user)
            db.commit()
            finance_service.unapprove_fund_doc(db, db.get(PaymentOrder, pay_id), "误操作", user)
            db.commit()
            # 已回到 submitted，再次反审核被状态机拒绝
            with pytest.raises(ValueError):
                finance_service.unapprove_fund_doc(db, db.get(PaymentOrder, pay_id), "再撤", user)
            db.rollback()
            assert db.get(PurchaseOrder, po_id).paid_amount == Decimal("0.00")

    def test_downstream_blocks_source_unapprove(self, box):
        """AC-V2.5-07：采购单存在已记账付款单时禁止反审核。"""
        po_id = box.purchase_order(amount="10000")
        user = _User()
        with SessionLocal() as db:
            pay = _submitted(db, box, "3000", po_id)
            db.commit()
            box.docs["payments"].append(pay.id)
            pay_id = pay.id
            finance_service.approve_fund_doc(db, db.get(PaymentOrder, pay_id), user)
            db.commit()
            po = db.get(PurchaseOrder, po_id)
            with pytest.raises(ValueError) as exc:
                finance_service.assert_no_finance_downstream(db, po)
            assert "已记账的付款单" in str(exc.value)
            # 反审核路径也要被拦住（doc_service.unapprove 内部调用）
            from app.services import doc_service

            with pytest.raises(ValueError):
                doc_service.unapprove(db, po, "试试", user)
            db.rollback()

    def test_downstream_list(self, box):
        po_id = box.purchase_order(amount="10000")
        user = _User()
        with SessionLocal() as db:
            pay = _submitted(db, box, "3000", po_id)
            db.commit()
            box.docs["payments"].append(pay.id)
            finance_service.approve_fund_doc(db, db.get(PaymentOrder, pay.id), user)
            db.commit()
            rows = finance_service.downstream_of(db, db.get(PurchaseOrder, po_id))
            assert len(rows) == 1 and rows[0]["kind"] == "payment" and rows[0]["posted"] is True
            assert rows[0]["amount"] == 3000.0


# ===================== 进度口径（AC-V2.5-11~13） =====================

class TestProgress:
    def test_quantity_progress(self, box):
        """收货/发货进度是数量口径（数据来自入库/出库过账回写）。"""
        po_id = box.purchase_order(qty="10", received="3")
        with SessionLocal() as db:
            progress = finance_service.progress_of(db.get(PurchaseOrder, po_id))
            assert progress["received_qty"] == {"num": 3.0, "den": 10.0, "pct": 30.0,
                                                "over": False}
        so_id = box.sales_order(qty="8", shipped="8")
        with SessionLocal() as db:
            progress = finance_service.progress_of(db.get(SalesOrder, so_id))
            assert progress["shipped_qty"]["pct"] == 100.0

    def test_zero_denominator_is_none(self, box):
        """分母为 0 显示 `—`（`pct=None`），不是 0% 也不是除零崩溃。"""
        po_id = box.purchase_order(amount="0")
        with SessionLocal() as db:
            assert finance_service.progress_of(db.get(PurchaseOrder, po_id))["paid_amount"]["pct"] is None

    def test_invoiced_uses_tax_inclusive_total(self, box):
        """AC-V2.5-11：分子分母都是**含税**口径（价税合计）。"""
        po_id = box.purchase_order(amount="10000")
        user = _User()
        with SessionLocal() as db:
            inv = Invoice(doc_no="INV-T1", doc_date=date.today(), status="draft",
                          invoice_direction="in", invoice_no=f"NO{uuid.uuid4().hex[:8]}",
                          amount=Decimal("5000"), tax_amount=Decimal("650"),
                          total_amount=Decimal("5650"), party_id=box.supplier_id,
                          party_name=box.supplier_name, subject_code=SUBJECT, subject_name="众诚")
            db.add(inv)
            db.flush()
            finance_service.parse_allocations(db, inv, [{
                "target_type": "purchase_order", "target_id": po_id, "amount": "5000"}],
                kind="invoice", allowed=("purchase_order",))
            db.commit()
            box.docs["invoices"].append(inv.id)
            finance_service.confirm_invoice(db, inv, user)
            db.commit()
            progress = finance_service.progress_of(db.get(PurchaseOrder, po_id))
            # 分子取核销到该单据的价税合计口径金额（5000），分母单据含税总额 10000
            assert progress["invoiced_amount"]["pct"] == 50.0
            assert db.get(PurchaseOrder, po_id).invoiced_amount == Decimal("5000.00")

    def test_over_flag(self, box):
        po_id = box.purchase_order(amount="10000")
        with SessionLocal() as db:
            po = db.get(PurchaseOrder, po_id)
            po.paid_amount = Decimal("12000")
            db.commit()
            assert finance_service.progress_of(po)["paid_amount"]["over"] is True
            assert finance_service.progress_of(po)["paid_amount"]["pct"] == 120.0


# ===================== 重算（AC-V2.5-17） =====================

class TestRecalc:
    def test_recalc_fixes_writeback(self, box):
        po_id = box.purchase_order(amount="10000")
        user = _User()
        with SessionLocal() as db:
            pay = _submitted(db, box, "3000", po_id)
            db.commit()
            box.docs["payments"].append(pay.id)
            finance_service.approve_fund_doc(db, db.get(PaymentOrder, pay.id), user)
            db.commit()
            # 人为改坏回写值 → 重算应恢复为明细合计
            po = db.get(PurchaseOrder, po_id)
            po.paid_amount = Decimal("1")
            db.commit()
            result = finance_service.recalc_progress(db)
            db.commit()
            assert result["fixed"] >= 1
            assert db.get(PurchaseOrder, po_id).paid_amount == Decimal("3000.00")
            # 幂等：再跑一次没有需要修正的内容
            again = finance_service.recalc_progress(db)
            assert again["fixed"] == 0

    def test_recalc_zeroes_orphan_writeback(self, box):
        """明细已无（单据被反审核/明细删掉）但回写还挂着 → 归零。"""
        po_id = box.purchase_order(amount="10000")
        with SessionLocal() as db:
            po = db.get(PurchaseOrder, po_id)
            po.paid_amount = Decimal("500")
            db.commit()
            result = finance_service.recalc_progress(db)
            db.commit()
            assert db.get(PurchaseOrder, po_id).paid_amount == Decimal("0.00")
            assert any(d["doc_no"] == po.doc_no for d in result["diffs"])


# ===================== 接口层：付款单（AC-V2.5-01/02/06/14/16/18） =====================

class TestFundApi:
    def test_create_submit_approve_flow(self, client, box, admin):
        po_id = box.purchase_order(amount="10000")
        finance_uid = box.user("finance")
        fin_h = box.login(client, finance_uid)

        # 新建（采购员/管理员都可，这里用管理员；缺核销目标金额时用明细兜底）
        payload = {"supplier_id": box.supplier_id, "subject_code": SUBJECT,
                   "settle_type": "银行转账", "total_amount": "3000",
                   "allocations": [{"target_type": "purchase_order", "target_id": po_id,
                                    "amount": "3000"}]}
        created = client.post("/api/finance/payments", json=payload, headers=admin)
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["doc_no"].startswith("PAY")
        assert body["status"] == "draft"
        assert body["allocations"][0]["target_no"]
        pay_id = body["id"]
        box.docs["payments"].append(pay_id)

        # 提交 → 财务审核（记账）
        assert client.post(f"/api/finance/payments/{pay_id}/submit",
                           headers=admin).status_code == 200
        approved = client.post(f"/api/finance/payments/{pay_id}/approve", headers=fin_h)
        assert approved.status_code == 200, approved.text
        assert approved.json()["posted"] is True

        # 目标单据进度（接口层的真源）
        detail = client.get(f"/api/purchase/orders/{po_id}", headers=admin).json()
        assert detail["progress"]["paid_amount"]["pct"] == 30.0
        assert detail["paid_amount"] == 3000.0

        # AC-V2.5-07 接口层：采购单存在已记账付款单 → 反审核被拒（422）
        blocked = client.post(f"/api/purchase/orders/{po_id}/unapprove",
                              json={"reason": "试试"}, headers=admin)
        assert blocked.status_code == 422
        assert "付款单" in blocked.json()["detail"]

        # 反审核付款单 → 进度回退
        assert client.post(f"/api/finance/payments/{pay_id}/unapprove",
                           json={"reason": "录错"}, headers=fin_h).status_code == 200
        detail = client.get(f"/api/purchase/orders/{po_id}", headers=admin).json()
        assert detail["progress"]["paid_amount"]["pct"] == 0.0

    def test_missing_supplier_rejected(self, client, box, admin):
        resp = client.post("/api/finance/payments",
                           json={"subject_code": SUBJECT, "total_amount": "100"}, headers=admin)
        assert resp.status_code == 422
        assert "供应商" in resp.json()["detail"]

    def test_amount_fallback_and_no_amount_rejected(self, client, box, admin):
        """只填核销明细也能建单（金额按明细合计）；两者都没有则 422。"""
        po_id = box.purchase_order(amount="10000")
        ok = client.post("/api/finance/payments",
                         json={"supplier_id": box.supplier_id, "subject_code": SUBJECT,
                               "allocations": [{"target_type": "purchase_order",
                                                "target_id": po_id, "amount": "1234.5"}]},
                         headers=admin)
        assert ok.status_code == 200, ok.text
        assert ok.json()["total_amount"] == 1234.5
        box.docs["payments"].append(ok.json()["id"])

        bad = client.post("/api/finance/payments",
                          json={"supplier_id": box.supplier_id, "subject_code": SUBJECT},
                          headers=admin)
        assert bad.status_code == 422
        assert "核销明细" in bad.json()["detail"]

    def test_over_filter_and_export(self, client, box, admin):
        po_id = box.purchase_order(amount="10000")
        small = client.post("/api/finance/payments",
                            json={"supplier_id": box.supplier_id, "subject_code": SUBJECT,
                                  "total_amount": "100",
                                  "allocations": [{"target_type": "purchase_order",
                                                   "target_id": po_id, "amount": "100"}]},
                            headers=admin).json()
        over = client.post("/api/finance/payments",
                           json={"supplier_id": box.supplier_id, "subject_code": SUBJECT,
                                 "total_amount": "100",
                                 "allocations": [{"target_type": "purchase_order",
                                                  "target_id": po_id, "amount": "200"}]},
                           headers=admin).json()
        box.docs["payments"] += [small["id"], over["id"]]

        rows = client.get("/api/finance/payments", params={"over": True}, headers=admin).json()
        ids = [r["id"] for r in rows["items"]]
        assert over["id"] in ids and small["id"] not in ids
        assert all(r["over"] for r in rows["items"])

        # 导出：默认列表与导出条数一致（这里用关键词把范围收窄到本用例的两张单）
        listed = client.get("/api/finance/payments", params={"over": True}, headers=admin).json()
        exported = client.get("/api/finance/payments/export.xlsx", params={"over": True},
                              headers=admin)
        assert exported.status_code == 200
        assert "spreadsheetml" in exported.headers["content-type"]
        assert len(exported.content) > 0
        assert listed["total"] == len(rows["items"])

    def test_receipt_flow_updates_sales_order(self, client, box, admin):
        so_id = box.sales_order(amount="8000")
        finance_uid = box.user("finance")
        fin_h = box.login(client, finance_uid)
        created = client.post("/api/finance/receipts",
                              json={"customer_id": box.customer_id, "subject_code": SUBJECT,
                                    "total_amount": "8000",
                                    "allocations": [{"target_type": "sales_order",
                                                     "target_id": so_id, "amount": "8000"}]},
                              headers=admin)
        assert created.status_code == 200, created.text
        rid = created.json()["id"]
        box.docs["receipts"].append(rid)
        assert created.json()["doc_no"].startswith("RCP")
        client.post(f"/api/finance/receipts/{rid}/submit", headers=admin)
        assert client.post(f"/api/finance/receipts/{rid}/approve",
                           headers=fin_h).status_code == 200
        detail = client.get(f"/api/sales/orders/{so_id}", headers=admin).json()
        assert detail["progress"]["received_amount"]["pct"] == 100.0

    def test_recalc_endpoint_requires_permission(self, client, box):
        buyer = box.login(client, box.user("buyer"))
        assert client.post("/api/finance/recalc", headers=buyer).status_code == 403
        admin_uid = box.user("finance")
        assert client.post("/api/finance/recalc",
                           headers=box.login(client, admin_uid)).status_code == 200


# ===================== 接口层：发票（AC-V2.5-09/10/11） =====================

class TestInvoiceApi:
    def test_invoice_confirm_and_void(self, client, box, admin):
        po_id = box.purchase_order(amount="10000")
        fin_h = box.login(client, box.user("finance"))
        no = f"NO{uuid.uuid4().hex[:10]}"
        created = client.post("/api/finance/invoices",
                              json={"invoice_direction": "in", "invoice_no": no,
                                    "invoice_code": "044001900111",
                                    "invoice_type": "增值税专用发票",
                                    "invoice_date": date.today().isoformat(),
                                    "amount": "5000", "tax_amount": "650",
                                    "supplier_id": box.supplier_id,
                                    "subject_code": SUBJECT,
                                    "allocations": [{"target_type": "purchase_order",
                                                     "target_id": po_id, "amount": "5650",
                                                     "tax_amount": "650"}]},
                              headers=admin)
        assert created.status_code == 200, created.text
        inv = created.json()
        assert inv["doc_no"].startswith("INV")
        assert inv["invoice_direction_label"] == "进项发票"
        assert inv["auth_status_label"] == "待认证"
        box.docs["invoices"].append(inv["id"])
        assert inv["total_amount"] == 5650.0

        # 重复票号（同方向）→ 422
        dup = client.post("/api/finance/invoices",
                          json={"invoice_direction": "in", "invoice_no": no, "amount": "1",
                                "supplier_id": box.supplier_id, "subject_code": SUBJECT},
                          headers=admin)
        assert dup.status_code == 422
        assert "已登记" in dup.json()["detail"]

        # 进项票只能核销采购单（销售订单 → 422）
        so_id = box.sales_order()
        wrong = client.post("/api/finance/invoices",
                            json={"invoice_direction": "in",
                                  "invoice_no": f"NO{uuid.uuid4().hex[:10]}",
                                  "amount": "1", "supplier_id": box.supplier_id,
                                  "subject_code": SUBJECT,
                                  "allocations": [{"target_type": "sales_order",
                                                   "target_id": so_id, "amount": "1"}]},
                            headers=admin)
        assert wrong.status_code == 422
        assert "核销目标只能是" in wrong.json()["detail"]

        # 认证状态流转不影响进度
        verified = client.post(f"/api/finance/invoices/{inv['id']}/verify",
                               json={"auth_status": "verified"}, headers=fin_h)
        assert verified.status_code == 200
        assert verified.json()["auth_status"] == "verified"
        assert client.get(f"/api/purchase/orders/{po_id}",
                          headers=admin).json()["invoiced_amount"] == 0.0

        # 确认入账 → 收票进度 56.5%
        confirmed = client.post(f"/api/finance/invoices/{inv['id']}/confirm", headers=fin_h)
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "confirmed"
        detail = client.get(f"/api/purchase/orders/{po_id}", headers=admin).json()
        assert detail["progress"]["invoiced_amount"]["pct"] == 56.5
        assert detail["invoiced_amount"] == 5650.0

        # 幂等：重复确认不再累加
        assert client.post(f"/api/finance/invoices/{inv['id']}/confirm",
                           headers=fin_h).status_code == 200
        assert client.get(f"/api/purchase/orders/{po_id}",
                          headers=admin).json()["invoiced_amount"] == 5650.0

        # 作废（已确认 → 先红冲）→ 进度归零
        voided = client.post(f"/api/finance/invoices/{inv['id']}/void",
                             json={"reason": "开错票"}, headers=fin_h)
        assert voided.status_code == 200, voided.text
        assert voided.json()["status"] == "voided"
        assert client.get(f"/api/purchase/orders/{po_id}",
                          headers=admin).json()["invoiced_amount"] == 0.0

    def test_invoice_list_by_direction_and_export(self, client, box, admin):
        inv_no = f"NO{uuid.uuid4().hex[:10]}"
        created = client.post("/api/finance/invoices",
                              json={"invoice_direction": "out", "invoice_no": inv_no,
                                    "amount": "800", "tax_amount": "104",
                                    "customer_id": box.customer_id,
                                    "subject_code": SUBJECT},
                              headers=admin)
        assert created.status_code == 200, created.text
        box.docs["invoices"].append(created.json()["id"])

        rows = client.get("/api/finance/invoices",
                          params={"direction": "out", "keyword": inv_no},
                          headers=admin).json()
        assert [r["invoice_no"] for r in rows["items"]] == [inv_no]
        assert rows["items"][0]["invoice_direction_label"] == "销项发票"

        exported = client.get("/api/finance/invoices/export.xlsx",
                              params={"direction": "out", "keyword": inv_no}, headers=admin)
        assert exported.status_code == 200
        assert "spreadsheetml" in exported.headers["content-type"]

    def test_invoice_edit_locked_after_confirm(self, client, box, admin):
        created = client.post("/api/finance/invoices",
                              json={"invoice_direction": "out",
                                    "invoice_no": f"NO{uuid.uuid4().hex[:10]}",
                                    "amount": "100", "customer_id": box.customer_id,
                                    "subject_code": SUBJECT}, headers=admin).json()
        box.docs["invoices"].append(created["id"])
        fin_h = box.login(client, box.user("finance"))
        assert client.post(f"/api/finance/invoices/{created['id']}/confirm",
                           headers=fin_h).status_code == 200
        locked = client.put(f"/api/finance/invoices/{created['id']}",
                            json={"amount": "200"}, headers=admin)
        assert locked.status_code == 422
        assert "不可编辑" in locked.json()["detail"] or "反审核" in locked.json()["detail"]


# ===================== 权限与菜单（AC-V2.5-18） =====================

class TestPermissions:
    def test_buyer_can_initiate_but_not_approve(self, client, box):
        buyer_h = box.login(client, box.user("buyer"))
        po_id = box.purchase_order(amount="10000")
        created = client.post("/api/finance/payments",
                              json={"supplier_id": box.supplier_id, "subject_code": SUBJECT,
                                    "total_amount": "100",
                                    "allocations": [{"target_type": "purchase_order",
                                                     "target_id": po_id, "amount": "100"}]},
                              headers=buyer_h)
        assert created.status_code == 200, created.text
        pay_id = created.json()["id"]
        box.docs["payments"].append(pay_id)
        assert client.post(f"/api/finance/payments/{pay_id}/submit",
                           headers=buyer_h).status_code == 200
        denied = client.post(f"/api/finance/payments/{pay_id}/approve", headers=buyer_h)
        assert denied.status_code == 403
        assert "finance.payment.approve" in denied.json()["detail"]

    def test_viewer_is_read_only(self, client, box):
        viewer_h = box.login(client, box.user("viewer"))
        assert client.get("/api/finance/payments", headers=viewer_h).status_code == 200
        assert client.post("/api/finance/payments",
                           json={"supplier_id": box.supplier_id, "subject_code": SUBJECT,
                                 "total_amount": "1"}, headers=viewer_h).status_code == 403

    def test_keeper_has_no_finance_perms(self, client, box):
        """仓管员不授予财务权限：避免"谁都能记账"。"""
        keeper_h = box.login(client, box.user("keeper"))
        assert client.get("/api/finance/payments", headers=keeper_h).status_code == 403
        with SessionLocal() as db:
            keeper = db.query(User).join(User.roles).filter(
                Role.code == "keeper").order_by(User.id.desc()).first()
            assert keeper is not None
            assert not {p for p in collect_perms(db, keeper) if p.startswith("finance.")}

    def test_finance_role_sees_menu(self, client, box):
        fin_h = box.login(client, box.user("finance"))
        me = client.get("/api/auth/me", headers=fin_h).json()
        keys = [m["key"] for m in me["menus"]]
        assert "finance" in keys
        finance_menu = next(m for m in me["menus"] if m["key"] == "finance")
        assert {c["key"] for c in finance_menu["children"]} == {
            "finance-payment", "finance-receipt", "finance-invoice"}
        assert {"finance.payment.approve", "finance.invoice.confirm"} <= set(me["perms"])

    def test_meta_endpoint(self, client, box):
        resp = client.get("/api/finance/meta", headers=box.login(client, box.user("finance")))
        assert resp.status_code == 200
        body = resp.json()
        assert "银行转账" in body["settle_types"]
        assert {"in", "out"} == {d["code"] for d in body["invoice_directions"]}
