"""Playwright E2E 测试专用账号初始化（幂等）。

为什么单独建账号：内置演示账号（`admin` / `pm01` …）为了演示"首次登录强制改密"
而置了 `must_change_pwd=1`，且密码可能已被人工改过。E2E 需要**固定凭据、
可直接进主界面**的账号，因此单独建 `e2e_*` 一组，重复执行时重置密码与首登标记，
不新增、不删除、不修改任何既有业务账号。

用法：
    app\\.venv\\Scripts\\python.exe app\\tools\\seed_e2e_users.py

账号（密码统一 `e2e12345`）：
    e2e_admin  系统管理员（超管，全权限）
    e2e_viewer 只读/管理层（用于权限裁剪与 403 场景）
    e2e_buyer  采购员（用于采购单据录入）
    e2e_keeper 仓管员（用于库存单据录入）
    e2e_seller 销售员（用于销售单据录入）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models_auth import OrgUnit, Role, User  # noqa: E402
from app.security import hash_password  # noqa: E402

E2E_PASSWORD = "e2e12345"

# (登录名, 姓名, 角色 code, 部门名或 None)
E2E_USERS: list[tuple[str, str, str, str | None]] = [
    ("e2e_admin", "E2E管理员", "sysadmin", None),
    ("e2e_viewer", "E2E只读", "viewer", None),
    ("e2e_buyer", "E2E采购员", "buyer", "采购部"),
    # V2.1：`sysadmin` 已纳入自审例外，故验证"创建人不可自审"需要一个
    # **有审核权但非管理员**的账号（见 06-purchase.spec.ts）
    ("e2e_pm", "E2E采购主管", "purchase_manager", "采购部"),
    ("e2e_keeper", "E2E仓管员", "keeper", "仓储部"),
    ("e2e_seller", "E2E销售员", "seller", "销售部"),
]


def _find_org(db, name: str | None) -> OrgUnit | None:
    if not name:
        return None
    return db.query(OrgUnit).filter(OrgUnit.name == name).first()


def main() -> int:
    db = SessionLocal()
    created = reset = 0
    try:
        for username, real_name, role_code, org_name in E2E_USERS:
            role = db.query(Role).filter(Role.code == role_code).first()
            if role is None:
                print(f"[WARN] 角色 {role_code} 不存在，跳过账号 {username}")
                continue
            org = _find_org(db, org_name)
            if org_name and org is None:
                print(f"[WARN] 组织 {org_name} 不存在，账号 {username} 将不分配部门")

            user = db.query(User).filter(User.username == username).first()
            if user is None:
                user = User(
                    username=username,
                    real_name=real_name,
                    password_hash=hash_password(E2E_PASSWORD),
                    status="enabled",
                    is_superadmin=False,
                    must_change_pwd=False,
                    org_id=org.id if org else None,
                    remark="Playwright E2E 自动化账号（seed_e2e_users 维护）",
                )
                db.add(user)
                db.flush()
                created += 1
                action = "新建"
            else:
                user.password_hash = hash_password(E2E_PASSWORD)
                user.must_change_pwd = False
                user.status = "enabled"
                user.is_superadmin = False
                if org is not None:
                    user.org_id = org.id
                reset += 1
                action = "重置"
            user.roles = [role]
            print(f"  [{action}] {username} / {E2E_PASSWORD} · {role.name}")
        db.commit()
    finally:
        db.close()

    print(f"\n完成：新建 {created} 个，重置 {reset} 个；密码统一为 {E2E_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
