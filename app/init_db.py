"""种子数据：字典种子 + 可选演示数据（对应 03 计划 T2）。

用法：python -m app.init_db            # 仅建表 + 字典种子
      python -m app.init_db --demo     # 追加演示合同数据（原型演示用）
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from .config import ensure_dirs
from .database import Base, SessionLocal, engine
from .models import (
    DEFAULT_TAGS,
    STATUSES,
    Contract,
    Tag,
)


def seed_dicts(db: Session) -> dict[str, int]:
    """幂等写入字典种子：预置标签。状态集以代码常量承载（见 models.STATUSES）。"""
    created = 0
    existing = {t.name for t in db.query(Tag).all()}
    for name in DEFAULT_TAGS:
        if name not in existing:
            db.add(Tag(name=name, builtin=True, color=None))
            created += 1
    db.commit()
    return {"tags_created": created, "statuses_available": len(STATUSES)}


def seed_demo(db: Session) -> dict[str, int]:
    """演示数据（框架 1 + 子合同 2 + 销售 1），用于原型演示质保/绑定/比例等场景。"""
    tags = {t.name: t for t in db.query(Tag).all()}

    def _tag(name: str) -> list[Tag]:
        t = tags.get(name)
        return [t] if t else []

    today = date.today()

    framework = Contract(
        contract_no="F-2025-001",
        name="2025 年度 X 设备采购框架合同",
        type="采购",
        party_a="XX 公司",
        party_b="YY 供应商",
        sign_date=today - timedelta(days=120),
        subject_matter="X 系列设备框架供货",
        amount=Decimal("500000.00"),
        paid_amount=Decimal("0.00"),
        is_framework=True,
        status="已签订",
        owner_name="张三",
        remark="演示：框架合同，下挂两个子合同",
    )
    framework.tags = _tag("采购") + _tag("项目A")

    sub1 = Contract(
        contract_no="CG-2025-001",
        name="CG 项目一期设备采购",
        type="采购",
        party_a="XX 公司",
        party_b="YY 供应商",
        sign_date=today - timedelta(days=90),
        subject_matter="X 设备 10 台",
        amount=Decimal("120000.00"),
        paid_amount=Decimal("60000.00"),
        has_warranty=True,
        warranty_amount=Decimal("6000.00"),
        warranty_rate=Decimal("5.0000"),
        warranty_start=date(2025, 6, 1),
        warranty_months=12,
        warranty_end=date(2026, 5, 31),  # Q2：加 12 个月取当月最后一天
        warranty_released=False,
        is_framework=False,
        parent=framework,
        arrival_status="部分到货",
        expected_arrival_date=today + timedelta(days=10),
        status="付款中",
        owner_name="张三",
    )
    sub1.tags = _tag("采购") + _tag("项目A")

    sub2 = Contract(
        contract_no="CG-2025-003",
        name="项目B 配套耗材采购",
        type="采购",
        party_a="XX 公司",
        party_b="ZZ 供应商",
        sign_date=today - timedelta(days=15),
        subject_matter="配套耗材一批",
        amount=Decimal("80000.00"),
        paid_amount=Decimal("0.00"),
        is_framework=False,
        parent=framework,
        status="内部审批中",
        owner_name="王五",
    )
    sub2.tags = _tag("采购") + _tag("项目B")

    sales = Contract(
        contract_no="XS-2025-002",
        name="XX 设备销售（客户 M）",
        type="销售",
        party_a="客户 M 公司",
        party_b="XX 公司",
        sign_date=today - timedelta(days=60),
        subject_matter="X 设备 3 台",
        amount=Decimal("30000.00"),
        paid_amount=Decimal("30000.00"),
        has_warranty=True,
        warranty_amount=Decimal("1500.00"),
        warranty_rate=Decimal("5.0000"),
        warranty_start=today - timedelta(days=40),
        warranty_months=12,
        warranty_end=today + timedelta(days=20),  # 即将到期演示
        warranty_released=False,
        is_framework=False,
        arrival_status="已到货",
        status="到货",
        owner_name="李四",
    )
    sales.tags = _tag("销售")

    db.add_all([framework, sub1, sub2, sales])
    db.commit()
    return {"contracts": 4}


ADMIN_USERNAME = "admin"
ADMIN_INIT_PASSWORD = "admin12345"   # 仅初始化用；首次登录强制改密


def seed_auth(db: Session) -> dict:
    """权限体系种子（幂等）：预置角色 + 权限点 + 初始超管 + 系统参数。

    - 角色按 `permissions.ROLE_PRESETS` 创建，**仅在新建时**写入权限点，
      避免覆盖管理员后续的角色调整；
    - 超管账号首次创建后 `must_change_pwd=True`，首登强制改密（AC-V2-08）。
    """
    from .dicts import get_sys_params
    from .models_auth import Role, RolePermission, User
    from .permissions import ROLE_PRESETS, expand_perms
    from .security import hash_password

    roles_created = 0
    perms_created = 0
    for preset in ROLE_PRESETS:
        role = db.query(Role).filter(Role.code == preset["code"]).first()
        if role is not None:
            continue
        role = Role(
            code=preset["code"], name=preset["name"], data_scope=preset["data_scope"],
            remark=preset.get("remark"), builtin=True, enabled=True,
        )
        db.add(role)
        db.flush()
        for code in expand_perms(preset["perms"]):
            db.add(RolePermission(role_id=role.id, perm_code=code))
            perms_created += 1
        roles_created += 1
    db.commit()

    admin_created = False
    if db.query(User).filter(User.username == ADMIN_USERNAME).first() is None:
        db.add(User(
            username=ADMIN_USERNAME, real_name="系统管理员",
            password_hash=hash_password(ADMIN_INIT_PASSWORD),
            status="enabled", is_superadmin=True, must_change_pwd=True,
            remark="初始化脚本创建；首次登录请立即修改密码",
        ))
        db.commit()
        admin_created = True

    get_sys_params(db)   # 首次调用落库默认系统参数
    return {
        "roles_created": roles_created,
        "perms_created": perms_created,
        "admin_created": admin_created,
        "admin_username": ADMIN_USERNAME,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="初始化数据库")
    parser.add_argument("--demo", action="store_true", help="追加演示数据")
    args = parser.parse_args()

    ensure_dirs()
    Base.metadata.create_all(bind=engine)  # T2：建表（原型阶段；正式版切 Alembic 迁移）
    import app.models_auth  # noqa: F401  V2.0：让 create_all 感知权限/组织/账号表
    from .db_migrate import ensure_schema_upgrades

    Base.metadata.create_all(bind=engine)  # V2.0 新表（幂等）
    upgrade = ensure_schema_upgrades()
    print(f"[init_db] 增量迁移完成: {upgrade}")
    with SessionLocal() as db:
        result = seed_dicts(db)
        print(f"[init_db] 字典种子完成: {result}")
        auth = seed_auth(db)
        print(f"[init_db] 权限种子完成: {auth}")
        if args.demo:
            from .models import Contract

            if db.query(Contract).count() == 0:
                demo = seed_demo(db)
                print(f"[init_db] 演示数据完成: {demo}")
            else:
                print("[init_db] 已存在合同数据，跳过演示数据（避免重复；如需重置请删除 app/data/ctms.db 后重跑）")
    print("[init_db] 完成")
    if auth["admin_created"]:
        print(f"[init_db] 初始管理员：{ADMIN_USERNAME} / {ADMIN_INIT_PASSWORD}（首次登录强制改密）")


if __name__ == "__main__":
    sys.exit(main())
