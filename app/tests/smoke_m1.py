"""CTMS V2.0 · M1 验收冒烟（AC-V2-01 ~ AC-V2-12 + 系统管理/迁移）。

用法（先启动后端，建议同时托管前端静态产物以便人工目视 UI）：
    app\\.venv\\Scripts\\python.exe app\\tests\\smoke_m1.py

可选环境变量：
    CTMS_SMOKE_BASE   服务地址，默认 http://127.0.0.1:8010/api

脚本特点：
- 全部走**真实 HTTP + 登录令牌**（验证权限后端强校验，而非直接调用函数）；
- 数据范围（AC-V2-04/05/06）用合同台账验证：单据域在 M2 才落地，机制同源；
- 幂等：自建账号/角色/组织/档案/合同在结束时清理（账号走 DB 直删，其余走接口）。
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
ADMIN_USER = "admin"
ADMIN_PWD = "admin12345"
NEW_PWD = "ctms98765"

PASSED: list[str] = []
FAILED: list[str] = []
TS = int(time.time()) % 100000


def ok(name: str) -> None:
    PASSED.append(name)
    print(f"  [PASS] {name}")


def req(method: str, path: str, body=None, params=None, expect=(200,), token: str | None = None,
        binary: bool = False):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body, ensure_ascii=True).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request) as resp:
            raw = resp.read()
            if binary:
                return resp.status, raw
            return resp.status, json.loads(raw.decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        if binary:
            return exc.code, raw
        try:
            payload = json.loads(raw.decode("utf-8") or "null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {"raw": raw[:200].decode("utf-8", "replace")}
        if exc.code not in expect:
            raise AssertionError(f"{method} {path} -> {exc.code} {payload}")
        return exc.code, payload


def login(username: str, password: str, expect=(200,)) -> str | None:
    code, data = req("POST", "/auth/login", {"username": username, "password": password},
                     expect=expect)
    return data.get("token") if code == 200 else None


class Cleaner:
    """记录自建资源，结束时按依赖顺序清理。"""

    def __init__(self) -> None:
        self.contracts: list[int] = []
        self.products: list[int] = []
        self.uoms: list[int] = []
        self.types: list[int] = []
        self.customers: list[int] = []
        self.suppliers: list[int] = []
        self.orgs: list[int] = []
        self.roles: list[int] = []
        self.usernames: list[str] = []
        self.drafts: list[str] = []

    def cleanup(self, admin: str) -> None:
        for cid in self.contracts:
            try:
                req("DELETE", f"/contracts/{cid}", params={"reason": "M1 冒烟归档"}, token=admin)
            except Exception:  # noqa: BLE001
                pass
        for path, ids in (("/master/products", self.products),
                          ("/master/uoms", self.uoms),
                          ("/master/product-types", list(reversed(self.types))),
                          ("/master/customers", self.customers),
                          ("/master/suppliers", self.suppliers),
                          ("/system/org-units", list(reversed(self.orgs))),
                          ("/system/roles", self.roles)):
            for rid in ids:
                try:
                    req("DELETE", f"{path}/{rid}", token=admin)
                except Exception:  # noqa: BLE001
                    pass
        # 账号无删除接口（保留审计），测试账号走 DB 直删
        try:
            from app.database import SessionLocal
            from app.models_auth import OperationLog, User
            from app.models_master import PartyDraft

            with SessionLocal() as db:
                rows = db.query(User).filter(User.username.in_(self.usernames)).all()
                for row in rows:
                    db.query(OperationLog).filter(OperationLog.user_id == row.id).delete()
                    db.delete(row)
                if self.drafts:
                    db.query(PartyDraft).filter(PartyDraft.raw_name.in_(self.drafts)).delete(
                        synchronize_session=False)
                db.commit()
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] 测试账号/草案清理失败：{exc}")


def mk_user(admin: str, cleaner: Cleaner, *, role_ids: list[int], org_id: int | None,
            real_name: str, password: str = "init12345") -> str:
    username = f"sm{TS}{len(cleaner.usernames)}{int(time.time() * 1000) % 1000}"
    req("POST", "/system/users", {
        "username": username, "real_name": real_name, "password": password,
        "org_id": org_id, "role_ids": role_ids,
    }, token=admin)
    cleaner.usernames.append(username)
    return username


def role_id_of(admin: str, code: str) -> int:
    _, data = req("GET", "/system/roles", token=admin)
    return next(r["id"] for r in data["items"] if r["code"] == code)


# ==================== 各 AC 场景 ====================

def ac_v2_01(admin: str, cleaner: Cleaner) -> None:
    buyer_role = role_id_of(admin, "buyer")
    username = mk_user(admin, cleaner, role_ids=[buyer_role], org_id=None, real_name="登录验收员")

    # 错误密码：401 + 写操作日志
    code, _ = req("POST", "/auth/login", {"username": username, "password": "wrong-password"},
                  expect=(401,))
    assert code == 401
    _, logs = req("GET", "/system/logs", params={"module": "auth", "action": "login",
                                                 "keyword": username}, token=admin)
    assert any(row["result"] == "fail" for row in logs["items"]), "失败登录应写操作日志"

    # 正确密码：返回登录态，菜单按其权限裁剪
    token = login(username, "init12345")
    assert token
    _, me = req("GET", "/auth/me", token=token)
    assert me["user"]["username"] == username
    menu_keys = {m["key"] for m in me["menus"]}
    assert "contract" in menu_keys, "采购员应有合同菜单"
    assert "master" in menu_keys, "采购员应有资料库（只读）菜单"
    assert "system" not in {c["key"] for m in me["menus"] for c in (m.get("children") or [])} \
        or "m-system" not in {c["key"] for m in me["menus"] for c in (m.get("children") or [])}
    perm_set = set(me["perms"])
    assert "purchase.order.approve" not in perm_set, "采购员不应有审核权限"
    ok("AC-V2-01 登录与鉴权（错密码 401+日志；正确密码返回登录态与裁剪后菜单）")


def ac_v2_02(admin: str) -> None:
    for path in ("/contracts", "/master/products", "/system/logs", "/dashboard"):
        code, _ = req("GET", path, expect=(401,))
        assert code == 401, path
    ok("AC-V2-02 未登录拦截（业务与主数据接口均 401）")


def ac_v2_03(admin: str, cleaner: Cleaner) -> None:
    keeper_role = role_id_of(admin, "keeper")
    username = mk_user(admin, cleaner, role_ids=[keeper_role], org_id=None, real_name="仓管员验收")
    token = login(username, "init12345")

    _, me = req("GET", "/auth/me", token=token)
    perms = set(me["perms"])
    assert "purchase.order.view" in perms, "仓管员应有采购单查看权限"
    assert "purchase.order.approve" not in perms, "仓管员不应有采购单审核权限"
    # 菜单：仓管员无"采购申请"权限 → 采购管理下只应出现"采购单"查看入口（AC-V2-03 允许"仅有查看项"）
    purchase_menu = next((m for m in me["menus"] if m["key"] == "purchase"), None)
    if purchase_menu is not None:
        child_keys = {c["key"] for c in (purchase_menu.get("children") or [])}
        assert child_keys <= {"purchase-order"}, f"仓管员采购菜单越权：{child_keys}"
    assert "m-system" not in {c["key"] for m in me["menus"]
                              for c in ((m.get("children") or []) + [m])}, "仓管员不应看到系统管理入口"

    # 直接调用无权接口 → 403（前端隐藏不作为安全边界）
    code, body = req("PUT", "/master/customers/1/status", {"enabled": False},
                     expect=(403,), token=token)
    assert code == 403 and "master.customer.edit" in body["detail"], f"越权写未被拦截：{body}"

    code, body = req("GET", "/master/customers", expect=(403,), token=token)
    assert "master.customer.view" in body["detail"], f"越权读未被拦截：{body}"
    ok("AC-V2-03 菜单与按钮权限（菜单裁剪 + 直接调接口 403）")


def ac_v2_04_05_06(admin: str, cleaner: Cleaner) -> None:
    # 组织：采购部 > 采购一组；另建"销售部"
    _, dept = req("POST", "/system/org-units", {"name": f"验收采购部{TS}", "unit_type": "部门"},
                  token=admin)
    cleaner.orgs.append(dept["id"])
    _, group = req("POST", "/system/org-units",
                   {"name": f"验收采购一组{TS}", "unit_type": "岗位", "parent_id": dept["id"]},
                   token=admin)
    cleaner.orgs.append(group["id"])
    _, other = req("POST", "/system/org-units", {"name": f"验收销售部{TS}", "unit_type": "部门"},
                   token=admin)
    cleaner.orgs.append(other["id"])

    buyer_role = role_id_of(admin, "buyer")
    finance_role = role_id_of(admin, "finance")

    # 自定义角色：本部门及下级 + 合同查看（验证 DEPT_SUB 数据范围）
    _, role = req("POST", "/system/roles", {
        "code": f"deptsub{TS}", "name": f"验收主管{TS}", "data_scope": "DEPT_SUB",
        "perms": ["dashboard.view", "contract.view", "contract.log.view"],
    }, token=admin)
    cleaner.roles.append(role["id"])

    user_a = mk_user(admin, cleaner, role_ids=[buyer_role], org_id=group["id"], real_name="采购一组员")
    user_b = mk_user(admin, cleaner, role_ids=[buyer_role], org_id=other["id"], real_name="销售部采购员")
    user_mgr = mk_user(admin, cleaner, role_ids=[role["id"]], org_id=dept["id"], real_name="采购部主管")
    user_both = mk_user(admin, cleaner, role_ids=[buyer_role, finance_role], org_id=group["id"],
                        real_name="多角色验收员")

    token_a, token_b = login(user_a, "init12345"), login(user_b, "init12345")
    token_mgr, token_both = login(user_mgr, "init12345"), login(user_both, "init12345")

    def new_contract(token: str, name: str) -> dict:
        _, data = req("POST", "/contracts", {
            "name": name, "type": "PUR", "subject_code": "ZC", "amount": 1000}, token=token)
        cleaner.contracts.append(data["id"])
        return data

    name_a, name_b = f"M1范围{TS}甲", f"M1范围{TS}乙"
    cid_a = new_contract(token_a, name_a)["id"]
    new_contract(token_b, name_b)

    # AC-V2-04 本人范围
    _, listing = req("GET", "/contracts", params={"keyword": f"M1范围{TS}"}, token=token_a)
    ids = {row["id"] for row in listing["items"]}
    assert cid_a in ids and len(ids) == 1, f"本人范围应只看到自己的合同，实际 {ids}"
    ok("AC-V2-04 数据范围-本人（采购员只见自己创建的合同）")

    # AC-V2-05 本部门及下级
    _, listing = req("GET", "/contracts", params={"keyword": f"M1范围{TS}"}, token=token_mgr)
    ids = {row["id"] for row in listing["items"]}
    assert cid_a in ids, "主管应看到本部门及下级（采购一组）的合同"
    _, listing_b = req("GET", "/contracts", params={"keyword": name_b}, token=token_mgr)
    assert listing_b["total"] == 0, "主管不应看到其他部门的合同"
    ok("AC-V2-05 数据范围-本部门及下级（含下级部门，跨部门不可见）")

    # AC-V2-06 多角色：数据范围取最宽（全部），写权限仍受最小角色约束
    _, listing = req("GET", "/contracts", params={"keyword": f"M1范围{TS}"}, token=token_both)
    ids = {row["id"] for row in listing["items"]}
    assert cid_a in ids, "财务(ALL)角色应把数据范围放宽到全部"
    code, body = req("POST", "/master/products", {"name": "多角色越权物料"},
                     expect=(403,), token=token_both)
    assert "master.product.edit" in body["detail"], "写操作仍受角色权限限制"
    ok("AC-V2-06 多角色权限并集（范围取最宽、写权限仍受限）")


def ac_v2_07(admin: str, cleaner: Cleaner) -> None:
    _, root = req("POST", "/system/org-units", {"name": f"验收删除部{TS}", "unit_type": "部门"},
                  token=admin)
    cleaner.orgs.append(root["id"])
    _, child = req("POST", "/system/org-units",
                   {"name": f"验收子节点{TS}", "parent_id": root["id"]}, token=admin)
    cleaner.orgs.append(child["id"])

    code, body = req("DELETE", f"/system/org-units/{root['id']}", expect=(422,), token=admin)
    assert "子节点" in body["detail"]

    buyer_role = role_id_of(admin, "buyer")
    username = mk_user(admin, cleaner, role_ids=[buyer_role], org_id=child["id"],
                       real_name="组织占用账号")
    code, body = req("DELETE", f"/system/org-units/{child['id']}", expect=(422,), token=admin)
    assert "账号" in body["detail"]
    # 停用可用
    req("PUT", f"/system/org-units/{child['id']}/status", {"enabled": False}, token=admin)
    ok("AC-V2-07 组织节点删除校验（有子节点/有账号 → 拒绝，可停用）")
    del username


def ac_v2_08(admin: str, cleaner: Cleaner) -> None:
    buyer_role = role_id_of(admin, "buyer")
    username = mk_user(admin, cleaner, role_ids=[buyer_role], org_id=None,
                       real_name="首登改密验收", password="init12345")

    token = login(username, "init12345")
    _, me = req("GET", "/auth/me", token=token)
    assert me["user"]["must_change_pwd"] is True, "新账号首登应要求改密"

    req("POST", "/auth/change-password",
        {"old_password": "init12345", "new_password": NEW_PWD}, token=token)
    token = login(username, NEW_PWD)
    _, me = req("GET", "/auth/me", token=token)
    assert me["user"]["must_change_pwd"] is False, "改密后不再强制"

    # 管理员重置 → 再次强制改密
    _, listing = req("GET", "/system/users", params={"keyword": username}, token=admin)
    uid = listing["items"][0]["id"]
    req("POST", f"/system/users/{uid}/reset-password", {"new_password": "reset12345"}, token=admin)
    token = login(username, "reset12345")
    _, me = req("GET", "/auth/me", token=token)
    assert me["user"]["must_change_pwd"] is True, "管理员重置后应再次强制改密"
    ok("AC-V2-08 首登强制改密与管理员重置（must_change_pwd 生命周期）")


def ac_v2_09_10_11(admin: str, cleaner: Cleaner) -> None:
    # 类型编码用时间戳保证唯一，避免与开发库既有编码同前缀而干扰"递增"断言
    _, root = req("POST", "/master/product-types",
                  {"name": f"办公用品{TS}", "code": f"R{TS % 1000:03d}"}, token=admin)
    cleaner.types.append(root["id"])
    _, leaf = req("POST", "/master/product-types",
                  {"name": f"纸张{TS}", "parent_id": root["id"], "code": f"L{TS % 1000:03d}"},
                  token=admin)
    cleaner.types.append(leaf["id"])

    # AC-V2-09：非叶子拒绝、叶子通过
    code, body = req("POST", "/master/products",
                     {"name": "越级物料", "product_type_id": root["id"], "uom_id": 1},
                     expect=(422,), token=admin)
    assert "叶子" in body["detail"]
    ok("AC-V2-09 商品类型树与物料挂载（非叶子被拒，叶子可挂）")

    # AC-V2-11：单位小数位
    _, uom0 = req("POST", "/master/uoms", {"code": f"PCS{TS % 100}", "name": f"个{TS}",
                                           "decimals": 0}, token=admin)
    cleaner.uoms.append(uom0["id"])
    code, body = req("POST", "/master/uoms", {"code": f"BAD{TS % 100}", "name": f"非法{TS}",
                                              "decimals": 9}, expect=(422,), token=admin)
    assert "小数位" in body["detail"]
    ok("AC-V2-11 计量单位小数位校验（0~4，越界拒绝）")

    # AC-V2-10：编码自动生成（类型码+序号，递增）+ 手工重复拒绝
    _, p1 = req("POST", "/master/products", {"name": f"验收纸张A{TS}",
                                             "product_type_id": leaf["id"],
                                             "uom_id": uom0["id"]}, token=admin)
    cleaner.products.append(p1["id"])
    _, p2 = req("POST", "/master/products", {"name": f"验收纸张B{TS}",
                                             "product_type_id": leaf["id"],
                                             "uom_id": uom0["id"]}, token=admin)
    cleaner.products.append(p2["id"])
    assert p1["code"].startswith(leaf["code"]) and p2["code"].startswith(leaf["code"])
    assert int(p2["code"][len(leaf["code"]):]) == int(p1["code"][len(leaf["code"]):]) + 1, \
        f"编码应递增：{p1['code']} → {p2['code']}"
    assert p1["uom_decimals"] == 0, "物料应带出单位小数位"
    code, body = req("POST", "/master/products",
                     {"name": "重复编码物料", "product_type_id": leaf["id"],
                      "uom_id": uom0["id"], "code": p1["code"]}, expect=(422,), token=admin)
    assert "已存在" in body["detail"]
    ok(f"AC-V2-10 物料编码自动生成与唯一（{p1['code']} → {p2['code']}；重复拒绝）")


def ac_v2_12(admin: str, cleaner: Cleaner) -> None:
    _, customer = req("POST", "/master/customers", {"name": f"验收客户{TS}"}, token=admin)
    cleaner.customers.append(customer["id"])
    _, contract = req("POST", "/contracts", {
        "name": f"M1档案合同{TS}", "type": "SAL", "subject_code": "ZC",
        "amount": 2000, "customer_id": customer["id"]}, token=admin)
    cleaner.contracts.append(contract["id"])
    assert contract["party_a"] == customer["name"], "选择档案应回填名称快照"

    req("PUT", f"/master/customers/{customer['id']}/status", {"enabled": False}, token=admin)
    _, options = req("GET", "/master/options/customer", token=admin)
    assert customer["id"] not in {o["id"] for o in options}, "停用客户不应出现在下拉"

    _, detail = req("GET", f"/contracts/{contract['id']}", token=admin)
    assert detail["customer_name"] == customer["name"], "历史合同仍应显示档案名称"
    ok("AC-V2-12 客户停用（下拉隐藏；历史合同仍显示名称快照）")


def extras_migration_and_system(admin: str, cleaner: Cleaner) -> None:
    # ---- 历史档案迁移（T-V2-14 / AC-V2-35） ----
    raw = f"迁移供应商{TS}"
    _, legacy = req("POST", "/contracts", {
        "name": f"历史采购合同{TS}", "type": "PUR", "subject_code": "ZC",
        "amount": 3000, "party_b": raw}, token=admin)
    cleaner.contracts.append(legacy["id"])
    req("POST", "/contracts/migrate-parties", token=admin)
    _, drafts = req("GET", "/contracts/party-drafts", params={"status": "pending"}, token=admin)
    hit = next((d for d in drafts["items"] if d["raw_name"] == raw), None)
    assert hit is not None, "应生成待认领草案"

    _, claimed = req("POST", f"/contracts/party-drafts/{hit['id']}/claim",
                     {"action": "create"}, token=admin)
    cleaner.suppliers.append(claimed["archive"]["id"])
    assert claimed["bound"] >= 1
    _, detail = req("GET", f"/contracts/{legacy['id']}", token=admin)
    assert detail["supplier_id"] == claimed["archive"]["id"], "认领后应批量绑定"
    _, logs = req("GET", f"/contracts/{legacy['id']}/logs", token=admin)
    assert any(lg["field_name"] == "supplier_id" and lg["operator_name"] for lg in logs)
    ok("AC-V2-35 历史档案认领（扫描→认领→批量绑定并留痕）")

    # ---- 系统管理（T-V2-12 / AC-V2-38、39） ----
    _, params = req("GET", "/system/params", token=admin)
    assert "warranty_window_days" in params["params"] and params["meta"]
    _, rules = req("GET", "/system/number-rules", token=admin)
    assert rules["previews"]["customer"].startswith(rules["rules"]["customer"]["prefix"])
    _, logs = req("GET", "/system/logs", params={"action": "create", "page_size": 5}, token=admin)
    assert logs["total"] >= 1
    _, changes = req("GET", "/system/changelogs", params={"page_size": 5}, token=admin)
    assert changes["total"] >= 1
    _, about = req("GET", "/system/about", token=admin)
    assert about["counts"]["contracts"] >= 1 and about["permission_count"] > 0
    ok("AC-V2-38 系统管理整合（参数/编号/日志/变更历史/关于均可用）")

    _, backup = req("POST", "/system/backup", token=admin)
    assert backup["name"].startswith("ctms_backup_") and backup["size_bytes"] > 0
    code, blob = req("GET", f"/system/backup/{backup['name']}", token=admin, binary=True)
    assert code == 200 and len(blob) > 500 and blob[:2] == b"PK", "备份应为可下载的 zip"
    code, _ = req("GET", "/system/backup/not-a-backup.zip", expect=(422,), token=admin)
    assert code == 422
    req("DELETE", f"/system/backup/{backup['name']}", token=admin)
    ok("AC-V2-39 手动备份下载（生成 zip、下载可用、非法文件名拒绝）")


def main() -> int:
    print(f"M1 验收冒烟 → {BASE}")
    admin = login(ADMIN_USER, ADMIN_PWD)
    assert admin, "管理员登录失败：请先执行 python -m app.init_db"
    cleaner = Cleaner()
    try:
        ac_v2_01(admin, cleaner)
        ac_v2_02(admin)
        ac_v2_03(admin, cleaner)
        ac_v2_04_05_06(admin, cleaner)
        ac_v2_07(admin, cleaner)
        ac_v2_08(admin, cleaner)
        ac_v2_09_10_11(admin, cleaner)
        ac_v2_12(admin, cleaner)
        extras_migration_and_system(admin, cleaner)
    except AssertionError as exc:
        FAILED.append(str(exc))
        print(f"  [FAIL] {exc}")
    finally:
        cleaner.cleanup(admin)

    print(f"\nM1 冒烟结果：{len(PASSED)} 项通过，{len(FAILED)} 项失败")
    for item in FAILED:
        print(f"  - {item}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
