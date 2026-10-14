"""V2.6 六项改进的测试。

覆盖：
- 下推按钮行级显隐：采购单/销售订单列表返回 `remain_qty_sum`（入库/出库回写后归零）；
- 出库单 FIFO 加权单价（多批不同价、跨批、累计不足）；
- 出库单**保存阶段**的负库存前移校验（保存拦截 / 审核仍拦截 / 多行累加 / 不同仓库互不影响 / 红冲后放行）；
- 我方公司字典扩展属性（bank_name/bank_account/tax_no）的读写与**旧格式 {code,name} 兼容**；
- 打印签字栏每行 3 个、超过换行（6→2 行、9→3 行、3→1 行；付款申请单固定网格同步）；
- 付款申请单打印「付款单位名称」快照缺失时按主体码反查全称、模板外「税号」字段。
"""
from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.dicts import KEY_SUBJECTS, get_subjects, set_subjects, subject_attr_of
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models import KVSetting
from app.models_auth import User
from app.models_doc import StockInOrder, StockInOrderItem, StockOutOrder, StockOutOrderItem
from app.models_master import Product, ProductType, Uom, Warehouse
from app.services import posting_service, print_service, print_template_service


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


def _admin(db) -> User:
    return db.query(User).filter(User.username == ADMIN_USERNAME).one()


def _mk_product(db) -> Product:
    sfx = _sfx()
    uom = Uom(code=f"U{sfx}", name=f"个{sfx}", decimals=0)
    db.add(uom)
    db.flush()
    ptype = ProductType(name=f"类型{sfx}")
    db.add(ptype)
    db.flush()
    product = Product(code=f"P{sfx}", name=f"物料{sfx}",
                      product_type_id=ptype.id, uom_id=uom.id)
    db.add(product)
    db.commit()
    return product


def _mk_warehouse(db) -> Warehouse:
    sfx = _sfx()
    wh = Warehouse(code=f"W{sfx}", name=f"仓库{sfx}")
    db.add(wh)
    db.commit()
    return wh


def _restore_subjects(db, backup: str | None) -> None:
    """恢复 `subjects` KV（可能原本不存在）—— 签约公司必填依赖 ZC，必须无痕还原。"""
    row = db.get(KVSetting, KEY_SUBJECTS)
    if backup is None:
        if row is not None:
            db.delete(row)
    else:
        if row is None:
            row = KVSetting(key=KEY_SUBJECTS, value=backup)
            db.add(row)
        else:
            row.value = backup
    db.commit()


def _mk_supplier(db):
    from app.models_master import Supplier

    sfx = _sfx()
    sup = Supplier(code=f"S{sfx}", name=f"供应商{sfx}")
    db.add(sup)
    db.commit()
    return sup


def _mk_posted_stock_in(db, product: Product, warehouse: Warehouse, qty: str,
                        price: str, *, doc_date: date | None = None) -> StockInOrder:
    """造一张**已过账**入库单（结存与流水同步，保持 recalc 一致性不变式）。"""
    sfx = _sfx()
    admin = _admin(db)
    doc = StockInOrder(
        doc_no=f"IN{sfx}", doc_date=doc_date or date.today(), status="approved",
        created_by=admin.id, created_by_name=admin.real_name,
        subject_code="ZC", subject_name="智澈公司",
        warehouse_id=warehouse.id, warehouse_name=warehouse.name,
        in_type="采购入库", posted=False,
    )
    db.add(doc)
    db.flush()
    doc.items.append(StockInOrderItem(
        seq=1, product_id=product.id, product_code=product.code, product_name=product.name,
        uom_name="个", uom_decimals=0, qty=Decimal(qty), unit_price=Decimal(price),
        amount=Decimal(qty) * Decimal(price), warehouse_id=warehouse.id,
    ))
    db.commit()
    posting_service.post_stock_doc(db, doc, user=admin)
    db.commit()
    return doc


def _mk_out_doc(db, product: Product, warehouse: Warehouse, rows: list[tuple[str, str]],
                *, warehouse2: Warehouse | None = None) -> StockOutOrder:
    """造一张**草稿**出库单（不过账），`rows` 为 (qty, price)，行仓库默认同表头。"""
    sfx = _sfx()
    admin = _admin(db)
    doc = StockOutOrder(
        doc_no=f"OUT{sfx}", doc_date=date.today(), status="draft",
        created_by=admin.id, created_by_name=admin.real_name,
        subject_code="ZC", subject_name="智澈公司",
        warehouse_id=warehouse.id, warehouse_name=warehouse.name,
        out_type="销售出库", posted=False,
    )
    db.add(doc)
    db.flush()
    for idx, (qty, price) in enumerate(rows, start=1):
        wh = warehouse if warehouse2 is None or idx == 1 else warehouse2
        doc.items.append(StockOutOrderItem(
            seq=idx, product_id=product.id, product_code=product.code, product_name=product.name,
            uom_name="个", uom_decimals=0, qty=Decimal(qty), unit_price=Decimal(price),
            amount=Decimal(qty) * Decimal(price), warehouse_id=wh.id,
        ))
    db.commit()
    return doc


# ---------------------------------------------------------------- 需求1：下推按钮行级显隐

class TestRemainQtySum:
    def test_采购单剩余量按已入库回写(self, db):
        from app.services import push_service

        product, wh = _mk_product(db), _mk_warehouse(db)
        sfx = _sfx()
        admin = _admin(db)
        sup = _mk_supplier(db)
        from app.models_doc import PurchaseOrder, PurchaseOrderItem

        po = PurchaseOrder(
            doc_no=f"PO{sfx}", doc_date=date.today(), status="approved",
            created_by=admin.id, created_by_name=admin.real_name,
            subject_code="ZC", subject_name="智澈公司",
            supplier_id=sup.id, supplier_name=sup.name,
        )
        db.add(po)
        db.flush()
        po.items.append(PurchaseOrderItem(
            seq=1, product_id=product.id, product_code=product.code, product_name=product.name,
            uom_name="个", qty=Decimal("10"), unit_price=Decimal("5"), amount=Decimal("50"),
            received_qty=Decimal("4"),
        ))
        db.commit()

        # 已入库 4 / 共 10 → 仍有剩余；全部入库（回写后）→ 归零
        assert push_service.remain_qty_sum(po, "received_qty") == Decimal("6")
        po.items[0].received_qty = Decimal("10")
        assert push_service.remain_qty_sum(po, "received_qty") == Decimal("0")

    def test_采购单列表返回剩余量(self, client, h, db):
        product = _mk_product(db)
        sfx = _sfx()
        admin = _admin(db)
        sup = _mk_supplier(db)
        from app.models_doc import PurchaseOrder, PurchaseOrderItem

        po = PurchaseOrder(
            doc_no=f"PO{sfx}", doc_date=date.today(), status="approved",
            created_by=admin.id, created_by_name=admin.real_name,
            subject_code="ZC", subject_name="智澈公司",
            supplier_id=sup.id, supplier_name=sup.name,
        )
        db.add(po)
        db.flush()
        po.items.append(PurchaseOrderItem(
            seq=1, product_id=product.id, product_code=product.code, product_name=product.name,
            uom_name="个", qty=Decimal("10"), unit_price=Decimal("5"), amount=Decimal("50"),
            received_qty=Decimal("10"),
        ))
        db.commit()

        resp = client.get("/api/purchase/orders", headers=h,
                          params={"keyword": po.doc_no})
        assert resp.status_code == 200, resp.text
        row = next(r for r in resp.json()["items"] if r["id"] == po.id)
        # 全部入库 → 剩余 0 → 前端 canPush 隐藏「下推」按钮
        assert row["remain_qty_sum"] == 0.0


# ---------------------------------------------------------------- 需求3：FIFO 加权单价

class TestFifoPrice:
    def test_多批不同价加权(self, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        _mk_posted_stock_in(db, product, wh, "10", "5")
        _mk_posted_stock_in(db, product, wh, "10", "7")

        # 出 15：先吃 10×5 再吃 5×7 → (50+35)/15 = 5.67；批次足够 → short=False
        price, short = posting_service.fifo_weighted_price(db, product.id, wh.id, 15)
        assert price == Decimal("5.67")
        assert short is False

    def test_累计不足按已有部分加权(self, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        _mk_posted_stock_in(db, product, wh, "4", "10")

        price, short = posting_service.fifo_weighted_price(db, product.id, wh.id, 10)
        assert price == Decimal("10.00")   # 只有 4 个入库，按其单价
        assert short is True               # 标记"不足"，前端提示

    def test_无入库记录返回空(self, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        price, short = posting_service.fifo_weighted_price(db, product.id, wh.id, 5)
        assert price is None and short is True

    def test_跨仓库互不影响_未过账不入库不计入(self, db):
        product, wh1, wh2 = _mk_product(db), _mk_warehouse(db), _mk_warehouse(db)
        _mk_posted_stock_in(db, product, wh1, "10", "5")
        # wh2 有一张**草稿**入库单（未过账）→ 不得计入
        sfx = _sfx()
        admin = _admin(db)
        draft = StockInOrder(
            doc_no=f"IN{sfx}", doc_date=date.today(), status="draft",
            created_by=admin.id, subject_code="ZC", subject_name="智澈公司",
            warehouse_id=wh2.id, warehouse_name=wh2.name, in_type="采购入库", posted=False,
        )
        db.add(draft)
        db.flush()
        draft.items.append(StockInOrderItem(
            seq=1, product_id=product.id, product_code=product.code, product_name=product.name,
            uom_name="个", qty=Decimal("99"), unit_price=Decimal("1"), warehouse_id=wh2.id,
        ))
        db.commit()

        price, _ = posting_service.fifo_weighted_price(db, product.id, wh2.id, 1)
        assert price is None               # 草稿不算 → wh2 无可用批次

    def test_fifo接口契约(self, client, h, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        _mk_posted_stock_in(db, product, wh, "10", "5")
        resp = client.get("/api/stock/fifo-price", headers=h,
                          params={"product_id": product.id, "warehouse_id": wh.id, "qty": 10})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"unit_price": 5.0, "enough": True}


# ---------------------------------------------------------------- 需求4：保存阶段库存校验

class TestSaveTimeBalanceCheck:
    def test_保存阶段拦截_库存不足(self, client, h, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        resp = client.post("/api/stock/out-orders", headers=h, json={
            "doc_date": date.today().isoformat(), "subject_code": "ZC",
            "warehouse_id": wh.id, "out_type": "销售出库",
            "items": [{"product_id": product.id, "qty": 3, "unit_price": 1}],
        })
        assert resp.status_code == 422
        assert "库存不足" in resp.json()["detail"]

    def test_保存放行_审核仍拦截(self, client, h, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        _mk_posted_stock_in(db, product, wh, "5", "2")
        resp = client.post("/api/stock/out-orders", headers=h, json={
            "doc_date": date.today().isoformat(), "subject_code": "ZC",
            "warehouse_id": wh.id,
            "items": [{"product_id": product.id, "qty": 5, "unit_price": 2}],
        })
        assert resp.status_code == 200, resp.text
        doc_id = resp.json()["id"]
        # 提交 + 审核（过账）成功；红冲后结存归零
        client.post(f"/api/stock/out-orders/{doc_id}/submit", headers=h)
        ok = client.post(f"/api/stock/out-orders/{doc_id}/approve", headers=h)
        assert ok.status_code == 200, ok.text
        # 反审核红冲 → 结存恢复 5 → 再存一张同数量出库单应放行（红冲边界）
        back = client.post(f"/api/stock/out-orders/{doc_id}/unapprove", headers=h,
                           json={"reason": "测试红冲"})
        assert back.status_code == 200, back.text
        again = client.post("/api/stock/out-orders", headers=h, json={
            "doc_date": date.today().isoformat(), "subject_code": "ZC",
            "warehouse_id": wh.id,
            "items": [{"product_id": product.id, "qty": 5, "unit_price": 2}],
        })
        assert again.status_code == 200, again.text

    def test_多行同物料累加后拦截(self, client, h, db):
        product, wh = _mk_product(db), _mk_warehouse(db)
        _mk_posted_stock_in(db, product, wh, "10", "1")
        # 两行各 6（合计 12 > 结存 10）→ 逐行看都够、合计超量，必须拦
        resp = client.post("/api/stock/out-orders", headers=h, json={
            "doc_date": date.today().isoformat(), "subject_code": "ZC",
            "warehouse_id": wh.id,
            "items": [{"product_id": product.id, "qty": 6, "unit_price": 1},
                      {"product_id": product.id, "qty": 6, "unit_price": 1}],
        })
        assert resp.status_code == 422
        assert "本次出库 12" in resp.json()["detail"]

    def test_不同仓库互不影响(self, client, h, db):
        product, wh1, wh2 = _mk_product(db), _mk_warehouse(db), _mk_warehouse(db)
        _mk_posted_stock_in(db, product, wh1, "10", "1")
        resp = client.post("/api/stock/out-orders", headers=h, json={
            "doc_date": date.today().isoformat(), "subject_code": "ZC",
            "warehouse_id": wh1.id,
            "items": [{"product_id": product.id, "qty": 10, "unit_price": 1,
                       "warehouse_id": wh1.id},
                      {"product_id": product.id, "qty": 3, "unit_price": 1,
                       "warehouse_id": wh2.id}],
        })
        # wh2 没有 3 个结存 → 行级仓库独立校验应拦截（而不是被 wh1 的结存掩盖）
        assert resp.status_code == 422

    def test_审核过账层仍兜底(self, db):
        """直接过账：结存不足时 post_stock_doc 依旧抛 BusinessError（AC-V2-21 回归）。"""
        product, wh = _mk_product(db), _mk_warehouse(db)
        doc = _mk_out_doc(db, product, wh, [("3", "1")])
        with pytest.raises(posting_service.BusinessError):
            posting_service.post_stock_doc(db, doc, user=_admin(db))
        db.rollback()


# ---------------------------------------------------------------- 需求5：我方公司扩展属性 / 付款打印

class TestSubjectExtraAttrs:
    def test_旧格式兼容读取(self, db):
        row = db.get(KVSetting, KEY_SUBJECTS)
        backup = row.value if row else None
        try:
            if row is None:
                row = KVSetting(key=KEY_SUBJECTS, value="[]")
                db.add(row)
            row.value = '[{"code": "T1", "name": "旧格式公司"}]'   # 旧格式：无扩展属性
            db.commit()
            subs = get_subjects(db)
            hit = next(s for s in subs if s["code"] == "T1")
            assert hit["name"] == "旧格式公司"
            assert hit["bank_name"] == "" and hit["tax_no"] == ""   # 缺失回退空串，不报错
        finally:
            _restore_subjects(db, backup)

    def test_扩展属性读写往返(self, db):
        row = db.get(KVSetting, KEY_SUBJECTS)
        backup = row.value if row else None
        try:
            saved = set_subjects(db, [
                {"code": "T2", "name": "扩展公司", "bank_name": "中国银行",
                 "bank_account": "6222", "tax_no": "TAX123"},
            ])
            assert saved[0]["tax_no"] == "TAX123"
            assert subject_attr_of(db, "T2", "bank_account") == "6222"
            assert subject_attr_of(db, "T2", "tax_no") == "TAX123"
            assert subject_attr_of(db, "NOPE", "tax_no") is None
        finally:
            _restore_subjects(db, backup)

    def test_付款打印_主体码反查全称与税号(self, db):
        row = db.get(KVSetting, KEY_SUBJECTS)
        backup = row.value if row else None
        try:
            set_subjects(db, [{"code": "T3", "name": "全称测试公司", "tax_no": "TAX-999"}])
            doc = print_service.sample_doc("payment")
            doc.subject_code, doc.subject_name = "T3", None      # 快照缺失
            cfg = print_template_service.default_config("payment")
            for f in cfg["head_fields"]:
                if f["key"] == "tax_no":
                    f["enabled"] = True                          # 模板外项目：显式打开
            html = print_service.build_doc_print_html(db, doc, cfg)
            assert "全称测试公司" in html                # 反查全称，而非印主体码 T3
            assert ">T3<" not in html
            assert "TAX-999" in html                     # 税号字段（打开后）
        finally:
            _restore_subjects(db, backup)

    def test_付款打印_收款单位为全称(self, db):
        doc = print_service.sample_doc("payment")
        doc.supplier_name = "样例供货商全称有限公司"
        doc.subject_name, doc.subject_code = "智澈公司", "ZC"
        html = print_service.build_doc_print_html(db, doc, None)
        assert "样例供货商全称有限公司" in html           # supplier_name 即档案全称


# ---------------------------------------------------------------- 需求6：签字栏每行 3 个

def _sign_rows(html: str, cls: str = "sign") -> int:
    """粗取签字表里的行数（通用版式取 `<tr>`；付款固定网格取 `tr class="sign"`）。"""
    if cls == "payment":
        return len(re.findall(r'<tr class="sign"', html))
    m = re.search(r'<table class="sign">(.*?)</table>', html, re.S)
    assert m, "缺少签字表"
    return len(re.findall(r"<tr>", m.group(1)))


class TestSignRows:
    def _generic(self, labels: list[str]) -> str:
        doc = print_service.sample_doc("purchase_order")
        cfg = print_template_service.default_config("purchase_order")
        cfg["signature_labels"] = labels
        return print_service.build_doc_print_html(None, doc, cfg)

    def test_三个一行(self):
        assert _sign_rows(self._generic(["甲", "乙", "丙"])) == 1

    def test_六个两行(self):
        html = self._generic([f"签{i}" for i in range(6)])
        assert _sign_rows(html) == 2

    def test_九个三行(self):
        html = self._generic([f"签{i}" for i in range(9)])
        assert _sign_rows(html) == 3

    def test_付款单九个三行_统一逻辑(self, db):
        doc = print_service.sample_doc("payment")
        cfg = print_template_service.default_config("payment")
        cfg["signature_labels"] = [f"签{i}" for i in range(9)]
        html = print_service.build_doc_print_html(db, doc, cfg)
        assert _sign_rows(html, "payment") == 3
        # 每行 3 个签字位（下划线样式保持）
        assert html.count("_" * 14) == 9
