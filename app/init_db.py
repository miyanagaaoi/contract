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


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="初始化数据库")
    parser.add_argument("--demo", action="store_true", help="追加演示数据")
    args = parser.parse_args()

    ensure_dirs()
    Base.metadata.create_all(bind=engine)  # T2：建表（原型阶段；正式版切 Alembic 迁移）
    with SessionLocal() as db:
        result = seed_dicts(db)
        print(f"[init_db] 字典种子完成: {result}")
        if args.demo:
            demo = seed_demo(db)
            print(f"[init_db] 演示数据完成: {demo}")
    print("[init_db] 完成")


if __name__ == "__main__":
    sys.exit(main())
