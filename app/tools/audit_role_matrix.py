"""权限矩阵复核（T-V2-39 / AC-V2-03、41、42）。

做法：对 `app/permissions.py` 中每个**内置角色**建一个临时账号，逐一登录后：
1. 拉取 `/api/auth/me`，核对生效权限点集合与 `ROLE_PRESETS` 展开结果是否一致；
2. 探测各模块代表性接口，核对"有权限=200 / 无权限=403"，自动发现**权限点与接口不匹配**；
3. 记录左侧菜单树（按权限裁剪后的 key 列表）；
4. 输出 Markdown 矩阵，可直接作为"权限复核记录"归档（默认写入 docs/16-permission-matrix.md）。

用法（先启动后端）：
    app\\.venv\\Scripts\\python.exe app\\tools\\audit_role_matrix.py

可选环境变量：`CTMS_SMOKE_BASE`（默认 http://127.0.0.1:8010/api）、`CTMS_MATRIX_OUT`（输出路径）。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.permissions import PERMISSIONS, ROLE_PRESETS, expand_perms, menu_tree_for  # noqa: E402

BASE = os.environ.get("CTMS_SMOKE_BASE", "http://127.0.0.1:8010/api")
OUT = Path(os.environ.get("CTMS_MATRIX_OUT") or (ROOT / "docs" / "16-permission-matrix.md"))
ADMIN_USER, ADMIN_PWD = "admin", "admin12345"

# (模块, 接口, 需要的权限点, 方法)
PROBES: list[tuple[str, str, str, str]] = [
    ("首页", "/dashboard", "dashboard.view", "GET"),
    ("合同", "/contracts", "contract.view", "GET"),
    ("合同-导出", "/export/contracts.xlsx", "contract.export", "GET"),
    ("客户", "/master/customers", "master.customer.view", "GET"),
    ("供应商", "/master/suppliers", "master.supplier.view", "GET"),
    ("物料", "/master/products", "master.product.view", "GET"),
    ("商品类型", "/master/product-types", "master.ptype.view", "GET"),
    ("计量单位", "/master/uoms", "master.uom.view", "GET"),
    ("仓库", "/master/warehouses", "master.wh.view", "GET"),
    ("组织架构", "/system/org-units", "master.org.view", "GET"),
    ("角色", "/system/roles", "master.role.view", "GET"),
    ("账号", "/system/users", "master.user.view", "GET"),
    ("采购申请", "/purchase/requests", "purchase.request.view", "GET"),
    ("采购单", "/purchase/orders", "purchase.order.view", "GET"),
    ("销售申请", "/sales/requests", "sales.request.view", "GET"),
    ("销售订单", "/sales/orders", "sales.order.view", "GET"),
    ("入库单", "/stock/in-orders", "stock.in.view", "GET"),
    ("出库单", "/stock/out-orders", "stock.out.view", "GET"),
    ("盘点单", "/stock/takes", "stock.take.view", "GET"),
    ("库存明细", "/stock/balances", "stock.balance.view", "GET"),
    ("操作日志", "/system/logs", "system.log.view", "GET"),
    ("系统参数", "/system/params", "system.param.view", "GET"),
    ("变更历史", "/system/changelogs", "system.changelog.view", "GET"),
    ("关于", "/system/about", "system.about.view", "GET"),
    ("物料维护(写)", "/master/products", "master.product.edit", "POST"),
    ("单据审核(写)", "/purchase/orders/1/approve", "purchase.order.approve", "POST"),
]

# 越权写探测（应始终 403/405，绝不能 200）
ESCALATION_PROBES: list[tuple[str, str, str, str]] = [
    ("新增物料越权", "/master/products", "master.product.edit", "POST"),
    ("新增账号越权", "/system/users", "master.user.edit", "POST"),
    ("变更参数越权", "/system/params", "system.param.edit", "PUT"),
    ("审核采购申请越权", "/purchase/requests/1/approve", "purchase.request.approve", "POST"),
]


def req(method: str, path: str, body=None, token: str | None = None, raw: bool = False):
    url = BASE + path
    data = json.dumps(body, ensure_ascii=True).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request) as resp:
            payload = resp.read()
            return resp.status, (payload if raw else _maybe_json(payload))
    except urllib.error.HTTPError as exc:
        return exc.code, _maybe_json(exc.read())


def _maybe_json(payload: bytes):
    try:
        return json.loads(payload.decode("utf-8") or "null")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def login(username: str, password: str) -> str:
    code, data = req("POST", "/auth/login", {"username": username, "password": password})
    assert code == 200 and data and data.get("token"), f"登录失败 {username}: {code}"
    return data["token"]


def make_user(admin: str, role_code: str) -> tuple[str, int]:
    username = f"mx_{role_code[:8]}_{uuid.uuid4().hex[:6]}"
    _, roles = req("GET", "/system/roles", token=admin)
    role_id = next(r["id"] for r in roles["items"] if r["code"] == role_code)
    code, data = req("POST", "/system/users", {
        "username": username, "real_name": f"矩阵-{role_code}",
        "password": "init12345", "role_ids": [role_id]}, token=admin)
    assert code == 200, f"建账号失败 {role_code}: {code} {data}"
    return username, data["id"]


def drop_users(usernames: list[str]) -> None:
    from app.database import SessionLocal
    from app.models_auth import OperationLog, User

    with SessionLocal() as db:
        for username in usernames:
            row = db.query(User).filter(User.username == username).first()
            if row is not None:
                db.query(OperationLog).filter(OperationLog.user_id == row.id).delete()
                db.delete(row)
        db.commit()


def menu_keys(nodes: list[dict]) -> list[str]:
    out: list[str] = []
    for node in nodes:
        out.append(node["key"])
        out.extend(menu_keys(node.get("children") or []))
    return out


def main() -> int:
    print(f"权限矩阵复核 → {BASE}")
    admin = login(ADMIN_USER, ADMIN_PWD)
    usernames: list[str] = []
    lines: list[str] = [
        "# 16. 权限矩阵复核记录（T-V2-39）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　·　生成方式：`app/tools/audit_role_matrix.py`（自动探测）",
        "> 复核内容：内置角色的生效权限点、菜单裁剪，以及各模块接口的 200（有权）/ 403（无权）实际返回。",
        "",
        "## 1. 角色 × 权限点",
        "",
        "| 角色 | 数据范围 | 权限点数 | 与预设一致 | 菜单入口 |",
        "|---|---|---|---|---|",
    ]
    issues: list[str] = []
    probe_header = "| 角色 | " + " | ".join(name for name, _, _, _ in PROBES) + " |"
    probe_rule = "|---" * (len(PROBES) + 1) + "|"
    probe_rows: list[str] = []

    try:
        for preset in ROLE_PRESETS:
            code = preset["code"]
            username, _uid = make_user(admin, code)
            usernames.append(username)
            token = login(username, "init12345")
            _status, me = req("GET", "/auth/me", token=token)
            perms = set(me["perms"])
            expected = set(expand_perms(preset["perms"]))
            consistent = perms == expected
            keys = menu_keys(me["menus"])
            lines.append(
                f"| {preset['name']}（`{code}`） | {preset['data_scope']} | {len(perms)} | "
                f"{'✅' if consistent else '❌'} | {', '.join(keys) or '（无）'} |")
            if not consistent:
                issues.append(f"{code}：权限点与预设不一致，缺 {sorted(expected - perms)}，多 {sorted(perms - expected)}")

            # 菜单裁剪：应与本地 menu_tree_for 计算结果一致
            local_keys = menu_keys(menu_tree_for(perms, is_superadmin=False))
            if local_keys != keys:
                issues.append(f"{code}：菜单裁剪与本地定义不一致（接口 {keys} / 本地 {local_keys}）")

            cells = []
            for name, path, perm, method in PROBES:
                status, _payload = req(method, path, body={} if method in ("POST", "PUT") else None,
                                       token=token)
                allowed = perm in perms
                if allowed and status in (200, 422, 409):
                    cells.append("✔")          # 有权（422/409 表示参数问题但已通过鉴权）
                elif not allowed and status == 403:
                    cells.append("—")          # 无权且被拦截
                else:
                    cells.append(f"!{status}")  # 异常：有权被拦 / 无权被放行
                    issues.append(f"{code} · {name}：期望{'通过' if allowed else '403'}，实际 {status}")
            probe_rows.append("| " + preset['name'] + " | " + " | ".join(cells) + " |")

            # 越权写探测：必须被拦截（403），绝不允许 200
            for name, path, perm, method in ESCALATION_PROBES:
                if perm in perms:
                    continue
                status, _ = req(method, path, body={}, token=token)
                if status not in (401, 403, 405, 422):
                    issues.append(f"{code} · 越权写 {name}：期望 403，实际 {status}")

            # AC-V2-42：主数据全公司共享（有 view 权限即可读），但不给维护权限就没有写按钮
            if "master.customer.view" in perms and "master.customer.edit" not in perms:
                status, _ = req("PUT", "/master/customers/1/status", body={"enabled": True}, token=token)
                if status != 403:
                    issues.append(f"{code}：无 master.customer.edit 却可修改客户状态（实际 {status}）")
    finally:
        drop_users(usernames)

    lines += ["", "## 2. 接口探测矩阵", "",
              "> ✔=有权且通过鉴权；—=无权且被 403 拦截；!N=异常（需修复）", "",
              probe_header, probe_rule, *probe_rows, ""]

    lines += ["## 3. 结论", ""]
    if issues:
        lines.append(f"发现 **{len(issues)}** 处不一致：")
        lines += [f"- {item}" for item in issues]
    else:
        lines.append("**全部通过**：所有内置角色的权限点、菜单裁剪与接口访问控制一致，"
                     "未发现越权放行或有权被拦的情况。")
    lines += ["", "## 4. 复核要点说明", "",
              "- 权限判定只在服务端执行（`require_perm`），前端隐藏按钮仅改善体验（AC-V2-41）；",
              "- 主数据全公司共享但**写操作受独立权限点控制**（AC-V2-42）；",
              "- 数据范围（本人/本部门/本部门及下级/全部）与权限点正交，本表只覆盖**权限点**维度，",
              "  数据范围的自动化验证见 `test_v2_contract_perm.py`、`test_v2_docs.py`、`smoke_m1.py`。",
              ""]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"矩阵已写入 {OUT}")
    if issues:
        print(f"发现 {len(issues)} 处不一致：")
        for item in issues:
            print(f"  - {item}")
        return 1
    print("全部通过：权限点、菜单裁剪与接口访问控制一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
