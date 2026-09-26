"""CTMS V2.0 · M2 验收冒烟（采购线与库存过账，AC-V2-13 ~ AC-V2-26 + 附件/合同互动）。

用法（先启动后端）：
    app\\.venv\\Scripts\\python.exe app\\tests\\smoke_m2.py

可选环境变量：`CTMS_SMOKE_BASE`（默认 http://127.0.0.1:8010/api）

特点：全部走真实 HTTP + 登录令牌；数据自建自清（主数据与单据走接口删除，账号走 DB 直删）。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE = os.environ.get("CTMS_SMOKE_BASE", "http://127.0.0.1:8010/api")
ADMIN_USER, ADMIN_PWD = "admin", "admin12345"

PASSED: list[str] = []
FAILED: list[str] = []
TS = int(time.time()) % 100000


def ok(name: str) -> None:
    PASSED.append(name)
    print(f"  [PASS] {name}")


def req(method: str, path: str, body=None, params=None, expect=(200,), token=None,
        raw_body: bytes | None = None, content_type: str | None = None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    if raw_body is not None:
        data = raw_body
    else:
        data = json.dumps(body, ensure_ascii=True).encode("utf-8") if body is not None else None
    headers = {"Content-Type": content_type or "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request) as resp:
            payload = resp.read()
            try:
                return resp.status, json.loads(payload.decode("utf-8") or "null")
            except (json.JSONDecodeError, UnicodeDecodeError):
                return resp.status, payload
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            detail = json.loads(payload.decode("utf-8") or "null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            detail = {"raw": payload[:200]}
        if exc.code not in expect:
            raise AssertionError(f"{method} {path} -> {exc.code} {detail}")
        return exc.code, detail


def login(username: str, password: str) -> str:
    code, data = req("POST", "/auth/login", {"username": username, "password": password})
    assert code == 200 and data.get("token"), f"登录失败：{username}"
    return data["token"]


class Cleaner:
    def __init__(self) -> None:
        self.products: list[int] = []
        self.types: list[int] = []
        self.uoms: list[int] = []
        self.warehouses: list[int] = []
        self.suppliers: list[int] = []
        self.customers: list[int] = []
        self.contracts: list[int] = []
        self.docs: dict[str, list[int]] = {k: [] for k in
                                           ("purchase_requests", "purchase_orders",
                                            "stock_in_orders", "stock_out_orders", "stock_takes")}
        self.usernames: list[str] = []

    def cleanup(self, admin: str) -> None:
        # 单据无删除接口（保留审计），测试数据用 DB 直删（含行项级联）
        for cid in self.contracts:
            try:
                req("DELETE", f"/contracts/{cid}", params={"reason": "M2 冒烟归档"}, token=admin)
            except Exception:  # noqa: BLE001
                pass
        for path, ids in (("/master/products", self.products), ("/master/uoms", self.uoms),
                          ("/master/product-types", list(reversed(self.types))),
                          ("/master/warehouses", self.warehouses),
                          ("/master/suppliers", self.suppliers), ("/master/customers", self.customers)):
            for obj_id in ids:
                try:
                    req("DELETE", f"{path}/{obj_id}", token=admin)
                except Exception:  # noqa: BLE001
                    pass
        try:
            from sqlalchemy import text

            from app import models_auth, models_doc, models_master, models_stock  # noqa: F401
            from app.database import SessionLocal
            from app.models import Attachment, ChangeLog
            from app.models_auth import OperationLog, User
            from app.models_doc import DOC_MODELS
            from app.models_stock import Stock, StockLedger

            with SessionLocal() as db:
                for table, ids in self.docs.items():
                    for doc_id in ids:
                        db.execute(text(f"DELETE FROM {table} WHERE id = :i"), {"i": doc_id})
                db.query(ChangeLog).filter(ChangeLog.object_type.in_(list(DOC_MODELS))).delete(
                    synchronize_session=False)
                for pid in self.products:
                    db.query(Attachment).filter(Attachment.object_type != "contract").delete(
                        synchronize_session=False)
                    db.query(StockLedger).filter(StockLedger.product_id == pid).delete()
                    db.query(Stock).filter(Stock.product_id == pid).delete()
                for username in self.usernames:
                    row = db.query(User).filter(User.username == username).first()
                    if row is not None:
                        db.query(OperationLog).filter(OperationLog.user_id == row.id).delete()
                        db.delete(row)
                db.commit()
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] 清理残留数据失败：{exc}")


def mk_role_user(admin: str, cleaner: Cleaner, role_code: str, real_name: str) -> str:
    username = f"m2_{role_code[:6]}_{TS}_{len(cleaner.usernames)}"
    _, roles = req("GET", "/system/roles", token=admin)
    role_id = next(r["id"] for r in roles["items"] if r["code"] == role_code)
    req("POST", "/system/users", {"username": username, "real_name": real_name,
                                  "password": "init12345", "role_ids": [role_id]}, token=admin)
    cleaner.usernames.append(username)
    return login(username, "init12345")


def main() -> int:
    print(f"M2 验收冒烟 → {BASE}")
    admin = login(ADMIN_USER, ADMIN_PWD)
    cleaner = Cleaner()
    try:
        run(admin, cleaner)
    except AssertionError as exc:
        FAILED.append(str(exc))
        print(f"  [FAIL] {exc}")
    finally:
        cleaner.cleanup(admin)
    print(f"\nM2 冒烟结果：{len(PASSED)} 项通过，{len(FAILED)} 项失败")
    for item in FAILED:
        print(f"  - {item}")
    return 1 if FAILED else 0


def run(admin: str, c: Cleaner) -> None:
    buyer = mk_role_user(admin, c, "buyer", "M2采购员")
    manager = mk_role_user(admin, c, "purchase_manager", "M2采购主管")
    keeper = mk_role_user(admin, c, "keeper", "M2仓管员")

    # ---------- 主数据准备 ----------
    _, uom = req("POST", "/master/uoms", {"code": f"U{TS % 1000:03d}", "name": f"件{TS}",
                                          "decimals": 2}, token=admin)
    c.uoms.append(uom["id"])
    _, ptype = req("POST", "/master/product-types", {"name": f"M2类型{TS}", "code": f"M{TS % 100:02d}"},
                   token=admin)
    c.types.append(ptype["id"])
    _, product = req("POST", "/master/products", {"name": f"M2物料{TS}", "product_type_id": ptype["id"],
                                                  "uom_id": uom["id"], "default_price": 10}, token=admin)
    c.products.append(product["id"])
    _, warehouse = req("POST", "/master/warehouses", {"code": f"W{TS % 1000:03d}", "name": f"M2仓库{TS}"},
                       token=admin)
    c.warehouses.append(warehouse["id"])
    _, supplier = req("POST", "/master/suppliers", {"name": f"M2供应商{TS}"}, token=admin)
    c.suppliers.append(supplier["id"])
    _, customer = req("POST", "/master/customers", {"name": f"M2客户{TS}"}, token=admin)
    c.customers.append(customer["id"])
    _, contract = req("POST", "/contracts", {"name": f"M2合同{TS}", "type": "PUR",
                                             "subject_code": "ZC", "amount": 50000}, token=admin)
    c.contracts.append(contract["id"])

    items = [{"product_id": product["id"], "qty": 100, "unit_price": 10}]

    # ---------- AC-V2-13/15：创建→提交→审核（审核人非创建人）
    # 注：V2.1 起管理员可自审（修订 AC-V2-15），故此处为 buyer 创建 + manager 审核，
    # **不构成自审场景**；自审规则本身由 app/tests/test_v2_1_approve_push.py 覆盖。
    code, doc = req("POST", "/purchase/requests", {"doc_date": "2026-03-01", "purpose": "M2 冒烟",
                                                   "contract_id": contract["id"],
                                                   "items": items}, token=buyer)
    assert code == 200, doc
    c.docs["purchase_requests"].append(doc["id"])
    assert doc["status"] == "draft" and doc["total_amount"] == 1000.0
    req("POST", f"/purchase/requests/{doc['id']}/submit", token=buyer)
    code, _ = req("POST", f"/purchase/requests/{doc['id']}/approve", expect=(403,), token=buyer)
    assert code == 403, "采购员不应有审核权限（AC-V2-03）"
    _, approved = req("POST", f"/purchase/requests/{doc['id']}/approve", token=manager)
    assert approved["status"] == "approved"
    logs = req("GET", f"/purchase/requests/{doc['id']}/changelogs", token=manager)[1]
    assert any(lg["operator_name"] for lg in logs)
    ok("AC-V2-13 采购申请 提交→审核（变更历史带操作人）")

    # ---------- AC-V2-14 驳回回草稿 ----------
    _, doc2 = req("POST", "/purchase/requests", {"items": items}, token=buyer)
    c.docs["purchase_requests"].append(doc2["id"])
    req("POST", f"/purchase/requests/{doc2['id']}/submit", token=buyer)
    _, rejected = req("POST", f"/purchase/requests/{doc2['id']}/reject", {"reason": "请补充用途"},
                      token=manager)
    assert rejected["status"] == "draft"
    ok("AC-V2-14 驳回回到草稿并记录原因")

    # ---------- AC-V2-16 下推采购单（剩余量约束） ----------
    item_id = approved["items"][0]["id"]
    _, po = req("POST", f"/purchase/requests/{doc['id']}/push",
                {"supplier_id": supplier["id"], "items": [{"src_item_id": item_id, "qty": 60}]},
                token=buyer)
    c.docs["purchase_orders"].append(po["id"])
    assert po["status"] == "draft" and po["items"][0]["qty"] == 60
    detail = req("GET", f"/purchase/requests/{doc['id']}", token=buyer)[1]
    assert detail["items"][0]["ordered_qty"] == 60
    code, body = req("POST", f"/purchase/requests/{doc['id']}/push",
                     {"supplier_id": supplier["id"], "items": [{"src_item_id": item_id, "qty": 50}]},
                     expect=(422,), token=buyer)
    assert "可下推数量不足" in body["detail"]
    _, po_rest = req("POST", f"/purchase/requests/{doc['id']}/push",
                     {"supplier_id": supplier["id"]}, token=buyer)
    c.docs["purchase_orders"].append(po_rest["id"])
    assert po_rest["items"][0]["qty"] == 40, "默认下推剩余 40"
    ok("AC-V2-16 下推采购单（60 已下单 / 剩余 40，超额被拦截）")

    # ---------- AC-V2-18：采购单审核 → 下推入库 → 回写已入库 ----------
    req("POST", f"/purchase/orders/{po['id']}/submit", token=manager)
    req("POST", f"/purchase/orders/{po['id']}/approve", token=manager)
    code, si = req("POST", f"/purchase/orders/{po['id']}/push",
                   {"warehouse_id": warehouse["id"], "items": [{"qty": 40}]}, token=manager)
    assert code == 200, si
    c.docs["stock_in_orders"].append(si["id"])
    req("POST", f"/stock/in-orders/{si['id']}/submit", token=keeper)
    _, posted = req("POST", f"/stock/in-orders/{si['id']}/approve", token=admin)
    assert posted["status"] == "approved" and posted["posted"] is True
    po_detail = req("GET", f"/purchase/orders/{po['id']}", token=buyer)[1]
    assert po_detail["items"][0]["received_qty"] == 40
    ok("AC-V2-18 入库过账并回写采购单已入库数量（40）")

    # ---------- AC-V2-19/23/26：结存、幂等、一致性 ----------
    ledger = req("GET", "/stock/ledger", params={"product_id": product["id"],
                                                 "warehouse_id": warehouse["id"]}, token=keeper)[1]
    assert ledger["balance"] == 40.0 and ledger["items"][0]["qty_change"] == 40.0
    req("POST", f"/stock/in-orders/{si['id']}/approve", token=admin)     # 重复审核
    ledger = req("GET", "/stock/ledger", params={"product_id": product["id"],
                                                 "warehouse_id": warehouse["id"]}, token=keeper)[1]
    assert ledger["total"] == 1, "重复审核不得重复过账（AC-V2-23）"
    consistent = req("POST", "/stock/recalc", token=keeper)[1]
    assert consistent["consistent"] is True, "结存与流水必须一致（AC-V2-26）"
    ok("AC-V2-19/23/26 入库过账、幂等、结存=流水")

    # ---------- AC-V2-20/21：出库与负库存拦截 ----------
    _, out_ok = req("POST", "/stock/out-orders", {
        "warehouse_id": warehouse["id"], "out_type": "其他出库", "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "qty": 4, "unit_price": 10}]}, token=keeper)
    c.docs["stock_out_orders"].append(out_ok["id"])
    req("POST", f"/stock/out-orders/{out_ok['id']}/submit", token=keeper)
    req("POST", f"/stock/out-orders/{out_ok['id']}/approve", token=admin)
    balance = req("GET", "/stock/ledger", params={"product_id": product["id"],
                                                  "warehouse_id": warehouse["id"]}, token=keeper)[1]["balance"]
    assert balance == 36.0, balance

    _, out_bad = req("POST", "/stock/out-orders", {
        "warehouse_id": warehouse["id"], "out_type": "其他出库",
        "items": [{"product_id": product["id"], "qty": 100, "unit_price": 10}]}, token=keeper)
    c.docs["stock_out_orders"].append(out_bad["id"])
    req("POST", f"/stock/out-orders/{out_bad['id']}/submit", token=keeper)
    code, body = req("POST", f"/stock/out-orders/{out_bad['id']}/approve", expect=(422,), token=admin)
    assert "库存不足" in body["detail"]
    after = req("GET", f"/stock/ledger", params={"product_id": product["id"],
                                                 "warehouse_id": warehouse["id"]}, token=keeper)[1]["balance"]
    assert after == 36.0, "拦截后库存不得变化（AC-V2-21）"
    doc_state = req("GET", f"/stock/out-orders/{out_bad['id']}", token=keeper)[1]
    assert doc_state["status"] == "submitted" and doc_state["posted"] is False
    ok("AC-V2-20/21 出库过账（36）与负库存拦截（状态与库存均不变）")

    # ---------- AC-V2-22/24：反审核红冲与下游保护 ----------
    code, body = req("POST", f"/purchase/orders/{po['id']}/unapprove", {"reason": "改价"},
                     expect=(422,), token=manager)
    assert "下游" in body["detail"], "存在下游入库单时禁止反审核（AC-V2-24）"
    _, reverted = req("POST", f"/stock/in-orders/{si['id']}/unapprove", {"reason": "供应商少发"},
                      token=admin)
    assert reverted["status"] == "submitted" and reverted["posted"] is False
    ledger = req("GET", "/stock/ledger", params={"product_id": product["id"],
                                                 "warehouse_id": warehouse["id"]}, token=keeper)[1]
    assert ledger["balance"] == -4.0 or ledger["balance"] == 36.0 - 40.0, ledger["balance"]
    assert any(r["biz_type"].startswith("红冲-") for r in ledger["items"])
    # 盘亏豁免校验：红冲后为负，补一笔入库回到正数
    _, fix_in = req("POST", "/stock/in-orders", {
        "warehouse_id": warehouse["id"], "in_type": "其他入库",
        "items": [{"product_id": product["id"], "qty": 20, "unit_price": 10}]}, token=keeper)
    c.docs["stock_in_orders"].append(fix_in["id"])
    req("POST", f"/stock/in-orders/{fix_in['id']}/submit", token=keeper)
    req("POST", f"/stock/in-orders/{fix_in['id']}/approve", token=admin)
    ok("AC-V2-22/24 反审核红冲（追加负向流水）与下游单据保护")

    # ---------- AC-V2-27/28：盘点全盘与盘亏自动生成 ----------
    _, take = req("POST", "/stock/takes", {"warehouse_id": warehouse["id"], "take_type": "full"},
                  token=keeper)
    c.docs["stock_takes"].append(take["id"])
    _, generated = req("POST", f"/stock/takes/{take['id']}/generate", {}, token=keeper)
    row = next(i for i in generated["items"] if i["product_id"] == product["id"])
    assert row["book_qty"] == 16.0, row["book_qty"]
    req("PUT", f"/stock/takes/{take['id']}/count",
        {"counts": [{"id": row["id"], "actual_qty": 15, "diff_reason": "破损 1 件"}]}, token=keeper)
    req("POST", f"/stock/takes/{take['id']}/submit", token=keeper)
    _, take_done = req("POST", f"/stock/takes/{take['id']}/approve", token=admin)
    assert take_done["generated_out_no"], take_done
    c.docs["stock_out_orders"].append(take_done["generated_out_id"])
    ledger = req("GET", "/stock/ledger", params={"product_id": product["id"],
                                                 "warehouse_id": warehouse["id"]}, token=keeper)[1]
    assert ledger["balance"] == 15.0, ledger["balance"]
    ok(f"AC-V2-27/28 盘点全盘与盘亏自动生成（{take_done['generated_out_no']}）")

    # ---------- 库存明细与预警筛选 ----------
    balances = req("GET", "/stock/balances", params={"keyword": product["code"]}, token=keeper)[1]
    assert balances["total"] >= 1 and balances["items"][0]["qty"] == 15.0
    ok("T-V2-23 库存明细（结存 + 关键词筛选）")

    # ---------- T-V2-26 合同关联单据只读汇总 ----------
    related = req("GET", f"/contracts/{contract['id']}/related-docs", token=admin)[1]
    # 本流程产生 2 张采购单（60 + 剩余 40），合计 60×10 + 40×10 = 1000
    assert related["summary"]["purchase_order_count"] == 2, related["summary"]
    assert related["summary"]["purchase_order_amount"] == 1000.0, related["summary"]
    assert related["summary"]["stock_in_count"] >= 1
    assert any(d["kind_label"] == "采购单" for d in related["docs"])
    contract_after = req("GET", f"/contracts/{contract['id']}", token=admin)[1]
    assert contract_after["amount"] == 50000.0, "合同金额不受单据影响（AC-V2-32）"
    ok("AC-V2-31/32 合同关联单据汇总（只读，不改合同金额）")

    # ---------- T-V2-27 附件挂到单据 ----------
    boundary = f"----ctms-m2-{TS}"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"M2验收.pdf\"\r\nContent-Type: application/pdf\r\n\r\n").encode() + \
           b"%PDF-1.4 m2 attachment" + f"\r\n--{boundary}--\r\n".encode()
    code, att = req("POST", f"/attachments/upload?object_type=stock_in&object_id={si['id']}",
                    raw_body=body, content_type=f"multipart/form-data; boundary={boundary}",
                    token=keeper)
    assert code == 200 and att["object_type"] == "stock_in", att
    listed = req("GET", "/attachments/list", params={"object_type": "stock_in",
                                                     "object_id": si["id"]}, token=keeper)[1]
    assert [a["id"] for a in listed] == [att["id"]]
    code, blob = req("GET", f"/attachments/{att['id']}/download", token=keeper)
    assert b"m2 attachment" in blob
    req("DELETE", f"/attachments/{att['id']}", params={"reason": "冒烟清理"}, token=keeper)
    code, _ = req("GET", "/attachments/list", params={"object_type": "stock_in",
                                                     "object_id": si["id"]}, expect=(403,), token=buyer)
    assert code == 403, "采购员无入库单查看权限（附件也应有边界）"
    ok("T-V2-27 单据附件上传/列表/下载/删除 + 权限边界")


if __name__ == "__main__":
    sys.exit(main())
