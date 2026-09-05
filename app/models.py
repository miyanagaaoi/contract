"""ORM 数据模型（对应 02-system-design.md 第 3 节 ER，V1.0 规格）。

- Contract: 合同（含框架合同自引用 parent_id，一对多）
- Tag / contract_tag: 标签字典与多对多关联
- Attachment: 附件元数据（文件存磁盘）
- ChangeLog: 变更历史（不记录操作人，仅时间与前后值）
"""
from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# ---------- 字典常量（原型以代码常量承载；M1 起可视需要落库为字典表） ----------

# 合同类型（BR2）
CONTRACT_TYPES = ["采购", "销售", "其他"]

# 进度状态（BR4，含"已终止"）
STATUSES = ["内部审批中", "集团审批中", "已签订", "付款中", "发货", "到货", "已终止"]
DEFAULT_STATUS = "内部审批中"

# 到货状态（BR3/Q3）
ARRIVAL_STATUSES = ["未到货", "部分到货", "已到货"]
DEFAULT_ARRIVAL = "未到货"

# 币种（BR2）
CURRENCIES = ["CNY", "USD", "EUR"]
DEFAULT_CURRENCY = "CNY"

# 预置标签（BR7）
DEFAULT_TAGS = ["采购", "销售", "项目A", "项目B"]

# 行项类型（MVP2 需求①；系统级可配置，见 KVSetting['item_types']，此为默认值）
DEFAULT_ITEM_TYPES = ["采购", "销售", "服务", "其他"]

# 框架合同自动标签（MVP2 需求④）
FRAMEWORK_TAG = "框架合同"

# 删除保留天数（BR10/Q7：软删除后 30 天内可恢复）
RESTORE_DAYS = 30


def add_months(value: date, months: int) -> date:
    """日期加 N 个月（按年-月进位，日归一到当月有效范围）。"""
    total = value.year * 12 + (value.month - 1) + months
    y, m0 = divmod(total, 12)
    m = m0 + 1
    day = min(value.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def compute_warranty_end(start: date, months: int) -> date:
    """质保到期日（BR5/Q2）：生效日 + 期限月 - 1 个月，取该月最后一天。

    例：2025-06-01 起 12 个月 → 2026-05-31（如同一年期保单口径）。
    months 至少为 1。
    """
    months = max(1, months)
    target = add_months(start, months - 1)
    return date(target.year, target.month, calendar.monthrange(target.year, target.month)[1])


# ---------- 关联表：合同 <-> 标签（多对多） ----------

contract_tag = Table(
    "contract_tag",
    Base.metadata,
    Column("contract_id", ForeignKey("contracts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_no: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)  # BR1 唯一
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="采购")           # BR2
    party_a: Mapped[str] = mapped_column(String(255), nullable=False, default="")            # 甲方
    party_b: Mapped[str] = mapped_column(String(255), nullable=False, default="")            # 乙方
    sign_date: Mapped[date | None] = mapped_column(Date, nullable=True)                      # 签订日期
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)                 # 生效日期(可选)
    subject_matter: Mapped[str] = mapped_column(Text, nullable=False, default="")            # 标的物
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)       # 合同金额
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default=DEFAULT_CURRENCY)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)  # 累计已付（BR3）
    has_warranty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)       # BR5
    warranty_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)   # 质保金金额
    warranty_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)     # 质保金比例
    warranty_start: Mapped[date | None] = mapped_column(Date, nullable=True)                 # 质保生效日期
    warranty_months: Mapped[int | None] = mapped_column(Integer, nullable=True)              # 质保期限(月)
    warranty_end: Mapped[date | None] = mapped_column(Date, nullable=True)                   # 质保到期日(Q2 算法)
    warranty_released: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 是否已释放
    warranty_release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    warranty_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_framework: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)       # BR6
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True, index=True
    )                                                                                        # 所属框架合同
    arrival_status: Mapped[str] = mapped_column(String(16), nullable=False, default=DEFAULT_ARRIVAL)  # BR3/Q3
    expected_arrival_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=DEFAULT_STATUS, index=True)  # BR4
    owner_name: Mapped[str | None] = mapped_column(String(64), nullable=True)                 # 经办人(BR9)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)  # 软删除（BR10/Q7）
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    parent: Mapped[Contract | None] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[Contract]] = relationship(back_populates="parent")                  # 框架子合同
    tags: Mapped[list[Tag]] = relationship(secondary=contract_tag, back_populates="contracts")
    attachments: Mapped[list[Attachment]] = relationship(back_populates="contract")
    logs: Mapped[list[ChangeLog]] = relationship(back_populates="contract")
    items: Mapped[list[ContractItem]] = relationship(
        back_populates="contract", order_by="ContractItem.seq",
        cascade="all, delete-orphan", lazy="selectin",
    )                                                                                          # 行项明细（MVP2 需求①）

    @property
    def payment_ratio(self) -> Decimal | None:
        """付款比例 = 累计已付 / 合同金额 ×100%（BR3/Q1，除零返回 None）。"""
        if self.amount is None or self.amount == 0:
            return None
        return (self.paid_amount / self.amount) * Decimal("100")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)   # BR7 全局去重
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    contracts: Mapped[list[Contract]] = relationship(secondary=contract_tag, back_populates="tags")


class ContractItem(Base):
    """合同行项明细（MVP2 需求①）：序号|类型|名称|规格型号|数量|单价|总价|备注。"""

    __tablename__ = "contract_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False, default=DEFAULT_ITEM_TYPES[0])
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    spec: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=0)          # 数量(支持小数)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0)   # 单价
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)        # 总价=数量×单价
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    contract: Mapped[Contract] = relationship(back_populates="items")


class KVSetting(Base):
    """系统级字典/配置（MVP2：行项类型等可配置列表，无账号下的全局设置）。"""

    __tablename__ = "kv_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")   # JSON 文本


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False)                    # 磁盘相对路径
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    contract: Mapped[Contract] = relationship(back_populates="attachments")


class ChangeLog(Base):
    """变更历史：记录 时间/字段/旧值/新值/备注；无操作人（01 BR12）。"""

    __tablename__ = "change_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")        # manual/auto
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    contract: Mapped[Contract] = relationship(back_populates="logs")
