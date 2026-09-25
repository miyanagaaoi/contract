"""主数据 ORM 模型（V2.0，对应 `12-erp-system-design.md` §4.2）。

- Customer     客户档案（销售甲方：合同/销售订单引用）
- Supplier     供应商档案（采购乙方：合同/采购单引用）
- ProductType  商品类型树（物化路径 path，叶子才可挂物料）
- Uom          计量单位（含小数位，决定数量显示与录入精度）
- Product      物料档案（编码自动/手工、绑定类型与单位、安全库存）
- Warehouse    仓库档案（库存与出入库单的归属）
- PartyDraft   历史合同甲乙方文本的迁移草案（T-V2-14，认领后批量绑定档案）

设计约定：
- 档案只做**启停用**（`status`），不做物理删除的常规入口；
  删除接口仅在"无任何引用"时放行，否则提示改为停用（与组织架构一致）。
- 主数据**不参与数据范围隔离**（`permission_service.apply_data_scope` 不适用于本模块）。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# 档案状态（与账号/组织保持一致的取值口径）
PARTY_STATUSES = ["enabled", "disabled"]

# 客户等级（下拉可选项，非强约束）
CUSTOMER_LEVELS = ["A", "B", "C", "D"]

# 物料类型（业务口径扩展字段，非强约束）
PRODUCT_LEVELS = CUSTOMER_LEVELS


class Customer(Base):
    """客户档案（销售方向的甲方）。"""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tax_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled", index=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Supplier(Base):
    """供应商档案（采购方向的乙方）。"""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tax_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    supply_scope: Mapped[str | None] = mapped_column(String(255), nullable=True)   # 供货范围
    payment_days: Mapped[int | None] = mapped_column(Integer, nullable=True)      # 账期（天）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled", index=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProductType(Base):
    """商品类型树。`path` 形如 `/1/5/`；**只有叶子节点**可被物料引用。"""

    __tablename__ = "product_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_types.id", ondelete="SET NULL"), nullable=True, index=True
    )
    code: Mapped[str | None] = mapped_column(String(32), nullable=True)           # 物料编码前缀来源
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False, default="/", index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    children: Mapped[list[ProductType]] = relationship(
        back_populates="parent", cascade="save-update"
    )
    parent: Mapped[ProductType | None] = relationship(
        remote_side=[id], back_populates="children"
    )


class Uom(Base):
    """计量单位。`decimals` 决定该单位下数量的录入/显示小数位。"""

    __tablename__ = "uoms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    decimals: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Warehouse(Base):
    """仓库档案。"""

    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    keeper_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 仓管员账号 id
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Product(Base):
    """物料档案。编码可自动生成（类型码 + 序号）或手工指定。"""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    spec: Mapped[str | None] = mapped_column(String(128), nullable=True)          # 规格型号
    product_type_id: Mapped[int] = mapped_column(
        ForeignKey("product_types.id"), nullable=False, index=True
    )
    uom_id: Mapped[int] = mapped_column(ForeignKey("uoms.id"), nullable=False, index=True)
    brand: Mapped[str | None] = mapped_column(String(64), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_price: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=Decimal("0")
    )
    safety_stock: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)  # 安全库存
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled", index=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    product_type: Mapped[ProductType] = relationship(lazy="joined")
    uom: Mapped[Uom] = relationship(lazy="joined")


class PartyDraft(Base):
    """历史合同"甲乙方文本 → 档案"迁移草案（T-V2-14 / AC-V2-34、35）。

    扫描 `contracts.party_a` / `party_b`（尚未绑定档案的记录）按文本聚合生成；
    `status`：pending（待认领）/ claimed（已认领并绑定）/ ignored（忽略，不再提示）。
    """

    __tablename__ = "party_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    party_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)   # customer/supplier
    raw_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contract_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    matched_id: Mapped[int | None] = mapped_column(Integer, nullable=True)            # 认领后的档案 id
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
