"""V2.6 发票同步与采购单绑定发票测试（docs/38 §7 验收场景）。

| 用例类 | 覆盖 |
|---|---|
| `TestNormalizeRow` | 平台行解析：字段映射、税率换算、非「正常」过滤、日期归一（AC-01 前置） |
| `TestUpsertIdempotent` | AC-03 同一发票号重复同步 → 跳过不重复入库；新增标记已认证/未确认 |
| `TestBindApi` | AC-05/06 弹窗绑定多张 → 状态已确认 + 收票进度累计；解绑 → 回未确认重算 |
| `TestInvoiceListV26` | AC-04 bind_status 筛选与 invoice_date 排序 |
| `TestSyncGuard` | AC-07 前置：未配置凭据 → 422；重复发起 → 422 |
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models_doc import Invoice, InvoiceSyncLog
from app.models_master import Supplier
from app.services import finance_service, tax_sync_service

from test_v2_5_finance import SUBJECT, Box, admin, box, client  # noqa: F401


def _synced_invoice(box: Box, *, no: str | None = None, amount="8000", tax="1040",
                    kprq: date | None = None) -> int:
    """直接 ORM 建一张「同步态」发票（未确认 / 已认证），供绑定用例使用。"""
    no = no or f"SYN{uuid.uuid4().hex[:16]}"
    kprq = kprq or date.today()
    with SessionLocal() as db:
        supplier = db.query(Supplier).first()
        inv = Invoice(
            doc_no=f"INV{uuid.uuid4().hex[:8].upper()}", doc_date=kprq, status="draft",
            invoice_direction="in", invoice_no=no, invoice_type="数电票（增值税专用发票）",
            invoice_date=kprq, tax_rate=Decimal("13.00"), amount=Decimal(amount),
            tax_amount=Decimal(tax), total_amount=Decimal(amount) + Decimal(tax),
            auth_status="authenticated", bind_status="unbound",
            sync_source="tax_platform",
            synced_at=__import__("datetime").datetime.now(),
            seller_name="测试开票单位", seller_tax_no="91140100TEST",
            buyer_tax_no="91149900MAECLDF33U", party_name="测试开票单位",
        )
        db.add(inv)
        db.commit()
        box.docs["invoices"].append(inv.id)
        return inv.id


# ===================== 行解析 =====================

class TestNormalizeRow:
    def test_json_row_full_mapping(self):
        row = tax_sync_service.normalize_row({
            "fphm": "26142000001496803711", "fplxDmc": "数电票（增值税专用发票）",
            "kprq": "2026-10-09 15:11:55", "je": "28814.16", "se": "3745.84",
            "jshj": "32560.00", "xfmc": "山西伟业房地产开发有限公司",
            "xfnsrsbh": "9114090277516473XM", "gfmc": "测试我方", "gfnsrsbh": "91149900MAECLDF33U",
            "fpztDmc": "正常",
        })
        assert row is not None
        assert row["invoice_no"] == "26142000001496803711"
        assert row["invoice_direction"] == "in"
        assert row["invoice_date"] == date(2026, 10, 9)
        assert row["amount"] == Decimal("28814.16")
        assert row["tax_amount"] == Decimal("3745.84")
        assert row["total_amount"] == Decimal("32560.00")
        assert row["seller_name"] == "山西伟业房地产开发有限公司"
        assert row["buyer_tax_no"] == "91149900MAECLDF33U"

    def test_tax_rate_derived_when_missing(self):
        row = tax_sync_service.normalize_row({
            "fphm": f"26{uuid.uuid4().hex[:18]}"[:20], "je": "100", "se": "13", "fpztDmc": "正常",
        })
        assert row is not None
        assert row["tax_rate"] == Decimal("13.00")
        # 价税合计缺省 = 金额 + 税额
        assert row["total_amount"] == Decimal("113")

    def test_abnormal_status_filtered(self):
        assert tax_sync_service.normalize_row({"fphm": "123", "fpztDmc": "作废"}) is None
        assert tax_sync_service.normalize_row({"fphm": "", "fpztDmc": "正常"}) is None


# ===================== 幂等入库（AC-03） =====================

class TestUpsertIdempotent:
    def test_duplicate_skipped_and_flags(self, box):  # noqa: F811
        no = f"SYN{uuid.uuid4().hex[:16]}"
        row = tax_sync_service.normalize_row({
            "fphm": no, "je": "100", "se": "13", "jshj": "113", "kprq": "2026-10-01",
            "xfmc": "测试开票单位", "gfnsrsbh": "91149900MAECLDF33U", "fpztDmc": "正常",
        })
        assert row is not None
        company = {"code": SUBJECT, "username": "u", "password": "p",
                   "tax_no": "91149900MAECLDF33U"}
        with SessionLocal() as db:
            first = tax_sync_service.upsert_invoices(db, [row], company)
            second = tax_sync_service.upsert_invoices(db, [row], company)
        assert first["inserted"] == 1 and first["skipped_duplicate"] == 0
        assert second["inserted"] == 0 and second["skipped_duplicate"] == 1
        with SessionLocal() as db:
            inv = (db.query(Invoice)
                   .filter(Invoice.invoice_no == no, Invoice.invoice_direction == "in")
                   .one())
            assert inv.auth_status == "authenticated"
            assert inv.bind_status == "unbound"
            assert inv.sync_source == "tax_platform"
            assert inv.synced_at is not None
            # 多公司口径：签约公司按主体码落快照（ZC = 种子里默认我方公司）
            assert inv.our_company_code == SUBJECT


# ===================== 绑定/解绑（AC-05/06） =====================

class TestBindApi:
    def test_bind_multi_then_unbind(self, client, box, admin):  # noqa: F811
        po_id = box.purchase_order(amount="20000")
        inv1 = _synced_invoice(box, amount="8000", tax="1040")     # 价税合计 9040
        inv2 = _synced_invoice(box, amount="5000", tax="650")      # 价税合计 5650
        fin_h = box.login(client, box.user("finance"))

        # 绑定两张 → 状态已确认 + 收票进度 (9040+5650)/20000 = 73.45%
        res = client.post("/api/finance/invoices/bind",
                          json={"purchase_order_id": po_id, "invoice_ids": [inv1, inv2]},
                          headers=fin_h)
        assert res.status_code == 200, res.text
        assert len(res.json()["bound"]) == 2 and not res.json()["errors"]
        detail = client.get(f"/api/purchase/orders/{po_id}", headers=admin).json()
        assert detail["invoiced_amount"] == pytest.approx(14690.0)
        assert detail["progress"]["invoiced_amount"]["pct"] == 73.4  # 73.45 → ROUND_HALF_EVEN
        for iid in (inv1, inv2):
            got = client.get(f"/api/finance/invoices/{iid}", headers=admin).json()
            assert got["bind_status"] == "bound"
            assert got["status"] == "confirmed"

        # 已绑定的再绑 → errors（AC-05 防重）
        again = client.post("/api/finance/invoices/bind",
                            json={"purchase_order_id": po_id, "invoice_ids": [inv1]},
                            headers=fin_h)
        assert again.status_code == 200
        assert not again.json()["bound"] and len(again.json()["errors"]) == 1

        # 解绑一张 → 回未确认（draft），进度重算为 5650/20000 = 28.3%
        ub = client.post(f"/api/finance/invoices/{inv1}/unbind", headers=fin_h)
        assert ub.status_code == 200, ub.text
        detail = client.get(f"/api/purchase/orders/{po_id}", headers=admin).json()
        assert detail["invoiced_amount"] == pytest.approx(5650.0)
        got = client.get(f"/api/finance/invoices/{inv1}", headers=admin).json()
        assert got["bind_status"] == "unbound" and got["status"] == "draft"

    def test_bind_requires_perm(self, client, box):  # noqa: F811
        po_id = box.purchase_order(amount="1000")
        inv = _synced_invoice(box, amount="100", tax="13")
        # V2.5 权限矩阵：采购员（buyer）可发起绑定；只读（viewer）不行
        viewer_h = box.login(client, box.user("viewer"))
        resp = client.post("/api/finance/invoices/bind",
                           json={"purchase_order_id": po_id, "invoice_ids": [inv]},
                           headers=viewer_h)
        assert resp.status_code == 403


# ===================== 列表筛选与排序（AC-04） =====================

class TestInvoiceListV26:
    def test_bind_status_filter_and_sort(self, client, box, admin):  # noqa: F811
        old = _synced_invoice(box, amount="100", tax="13", kprq=date(2026, 1, 5))
        new = _synced_invoice(box, amount="200", tax="26", kprq=date(2026, 9, 1))
        with SessionLocal() as db:
            db.query(Invoice).filter(Invoice.id == new).update(
                {"synced_at": __import__("datetime").datetime(2026, 9, 1, 10, 0)})
            db.commit()
        po_id = box.purchase_order(amount="100000")
        fin_h = box.login(client, box.user("finance"))
        assert client.post("/api/finance/invoices/bind",
                           json={"purchase_order_id": po_id, "invoice_ids": [old]},
                           headers=fin_h).status_code == 200

        # bind_status=unbound 只剩未确认
        ids_unbound = [r["id"] for r in client.get(
            "/api/finance/invoices", params={"bind_status": "unbound", "page_size": 200},
            headers=admin).json()["items"]]
        assert old not in ids_unbound and new in ids_unbound

        # 开票日期倒序：new(2026-09-01) 在 old(2026-01-05) 前
        rows = client.get("/api/finance/invoices",
                          params={"sort": "invoice_date_desc", "direction": "in",
                                  "page_size": 200},
                          headers=admin).json()["items"]
        pairs = [(r["id"], r["invoice_date"]) for r in rows if r["id"] in (old, new)]
        assert len(pairs) == 2
        assert pairs[0][0] == new
        rows_asc = client.get("/api/finance/invoices",
                              params={"sort": "invoice_date_asc", "direction": "in",
                                      "page_size": 200},
                              headers=admin).json()["items"]
        pairs_asc = [(r["id"]) for r in rows_asc if r["id"] in (old, new)]
        assert pairs_asc[0] == old

        # 非法排序 → 422
        assert client.get("/api/finance/invoices", params={"sort": "bogus"},
                          headers=admin).status_code == 422


# ===================== 桥接同步通道（开发环境） =====================

class TestImportRows:
    """POST /invoices/import-rows：浏览器桥解析行的幂等入库 + 红字过滤。"""

    def _row(self, no, amount="100", tax="13", total="113"):
        return {"invoice_no": no, "invoice_type": "数电发票（增值税专用发票）",
                "invoice_date": "2026-10-12", "amount": amount, "tax_amount": tax,
                "total_amount": total, "seller_name": "测试开票单位",
                "seller_tax_no": "91140100TEST", "buyer_tax_no": "91149900MAECLDF33U"}

    def test_import_then_duplicate_and_red(self, client, box, admin):  # noqa: F811
        no = f"BRG{uuid.uuid4().hex[:12]}"
        red_no = f"BRG{uuid.uuid4().hex[:12]}"
        rows = [self._row(no),
                self._row(red_no, amount="100", tax="13", total="-113")]
        resp = client.post("/api/finance/invoices/import-rows",
                           json={"subject_code": SUBJECT, "rows": rows}, headers=admin)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["inserted"] == 2
        assert body["skipped_red"] == 1          # 红字（负数）单独计数

        # 幂等：同一张再导 → 跳过
        again = client.post("/api/finance/invoices/import-rows",
                            json={"subject_code": SUBJECT, "rows": [self._row(no)]},
                            headers=admin)
        assert again.json()["skipped_duplicate"] == 1

        # 入库标记：已认证 / 未确认 / 同步口径一致；红字票 is_red=True
        with SessionLocal() as db:
            inv = (db.query(Invoice)
                   .filter(Invoice.invoice_no == no, Invoice.invoice_direction == "in")
                   .one())
            assert inv.auth_status == "authenticated"
            assert inv.bind_status == "unbound"
            assert inv.sync_source == "tax_platform"
            assert inv.our_company_code == SUBJECT
            assert inv.is_red is False
            red = (db.query(Invoice)
                   .filter(Invoice.invoice_no == red_no, Invoice.invoice_direction == "in")
                   .one())
            assert red.is_red is True

        # 红字票不可绑定采购单
        po_id = box.purchase_order(amount="50000")
        bind = client.post("/api/finance/invoices/bind",
                           json={"purchase_order_id": po_id, "invoice_ids": [red.id]},
                           headers=admin)
        assert bind.status_code == 200, bind.text
        errs = bind.json()["errors"]
        assert errs and "红字" in errs[0]["reason"]

        # 列表 is_red 筛选
        reds = [r["id"] for r in client.get(
            "/api/finance/invoices", params={"is_red": "true", "page_size": 200},
            headers=admin).json()["items"]]
        assert red.id in reds and inv.id not in reds

    def test_import_requires_subject(self, client, admin):  # noqa: F811
        resp = client.post("/api/finance/invoices/import-rows",
                           json={"rows": [{"invoice_no": "x"}]}, headers=admin)
        assert resp.status_code == 422


# ===================== 同步守卫（AC-07 前置） =====================

class TestSyncGuard:
    def test_sync_requires_subject_and_config(self, client, admin, monkeypatch):  # noqa: F811
        from app import config

        # 未选公司 → 422
        resp = client.post("/api/finance/invoices/sync",
                           json={"date_from": "2026-09-30", "date_to": "2026-10-16"},
                           headers=admin)
        assert resp.status_code == 422
        assert "我方公司" in resp.json()["detail"]

        # 主体码未配置凭据 → 422
        monkeypatch.setattr(config, "tax_sync_companies", lambda: {})
        resp = client.post("/api/finance/invoices/sync",
                           json={"date_from": "2026-09-30", "date_to": "2026-10-16",
                                 "subject_code": "ZC"},
                           headers=admin)
        assert resp.status_code == 422
        assert "CTMS_TAX_SYNC_ZC_USERNAME" in resp.json()["detail"]

        # 主体码不在「我方公司」字典 → 422（凭据已配好但字典没这家）
        monkeypatch.setattr(config, "tax_sync_companies", lambda: {
            "NOPE": {"code": "NOPE", "username": "u", "password": "p", "tax_no": ""}})
        resp = client.post("/api/finance/invoices/sync",
                           json={"date_from": "2026-09-30", "date_to": "2026-10-16",
                                 "subject_code": "NOPE"},
                           headers=admin)
        assert resp.status_code == 422
        assert "我方公司」字典" in resp.json()["detail"]

    def test_sync_info_lists_companies(self, client, admin, monkeypatch):  # noqa: F811
        """公司选项 = 字典全量主体码；ZC 已配凭据、YX 未配，各自标注 configured。"""
        from app import config

        monkeypatch.setattr(config, "tax_sync_companies", lambda: {
            "ZC": {"code": "ZC", "username": "u1", "password": "p1",
                   "tax_no": "91149900MAECLDF33U"}})
        resp = client.get("/api/finance/invoices/sync-info", headers=admin)
        assert resp.status_code == 200
        body = resp.json()
        codes = {c["code"]: c for c in body["companies"]}
        assert "ZC" in codes and "YX" in codes          # 选项来自系统管理字典全量
        assert codes["ZC"]["configured"] is True        # 有 .env 凭据
        assert codes["YX"]["configured"] is False       # 未配凭据（前端禁选）
        assert "session_fresh" in codes["ZC"]           # 会话状态按主体码给出

    def test_sync_log_recorded(self, box):  # noqa: F811
        with SessionLocal() as db:
            log = InvoiceSyncLog(date_from=date(2026, 9, 30), date_to=date(2026, 10, 16),
                                 subject_code=SUBJECT, tax_no="TEST",
                                 status="success", fetched=4, inserted=3,
                                 skipped_duplicate=1)
            db.add(log)
            db.commit()
            log_id = log.id
        with SessionLocal() as db:
            got = db.get(InvoiceSyncLog, log_id)
            assert got is not None and got.inserted == 3 and got.subject_code == SUBJECT


class TestHeadlessGuard:
    """CR-024：无头（容器）模式且无有效会话时，必须直接给出可执行指引，不得启动浏览器干等。"""

    def test_headless_without_session_rejects_with_guidance(self, monkeypatch):
        from app import config

        monkeypatch.setattr(config, "TAX_SYNC_ENABLED", True)
        monkeypatch.setattr(config, "TAX_SYNC_HEADLESS", True)
        monkeypatch.setattr(config, "tax_sync_company", lambda code: {
            "code": code, "username": "u", "password": "p", "tax_no": "91149900MAECLDF33U"})
        monkeypatch.setattr(tax_sync_service, "session_fresh", lambda code: False)

        with pytest.raises(ValueError) as exc:
            tax_sync_service.start_sync(date(2026, 9, 1), date(2026, 10, 1), "ZC")
        msg = str(exc.value)
        assert "无头模式" in msg and "state_" in msg and "上传发票包" in msg

    def test_display_required_when_headed_on_linux(self, monkeypatch):
        import os

        from app import config

        monkeypatch.setattr(config, "TAX_SYNC_ENABLED", True)
        monkeypatch.setattr(config, "TAX_SYNC_HEADLESS", False)
        monkeypatch.setattr(config, "tax_sync_company", lambda code: {
            "code": code, "username": "u", "password": "p", "tax_no": "91149900MAECLDF33U"})
        monkeypatch.setattr(tax_sync_service, "session_fresh", lambda code: False)
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        with pytest.raises(ValueError) as exc:
            tax_sync_service.start_sync(date(2026, 9, 1), date(2026, 10, 1), "ZC")
        assert "图形界面" in str(exc.value)
