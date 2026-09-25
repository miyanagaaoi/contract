"""库存 ORM 模型（V2.0 / M2，对应 `12-erp-system-design.md` §4.3）。

- `Stock`       结存（物料 × 仓库，只记数量，不记成本 —— 口径 D4/C-05）
- `StockLedger` 流水（只增不改；红冲以负数记录追加，保留原始流水可查）

**一致性不变式（AC-V2-26）**：对任一 `(product_id, warehouse_id)`，
`stocks.qty == SUM(stock_ledger.qty_change)`；运维接口 `POST /api/stock/recalc` 校验并修复。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# 业务类型（流水展示与筛选；红冲记录以前缀"红冲-"区分）
BIZ_TYPES = [
    "采购入库", "退货入库", "盘盈入库", "其他入库",
    "销售出库", "领用出库", "盘亏出库", "其他出库",
]


class Stock(Base):
    """结存：物料 × 仓库 的唯一行。"""

    __tablename__ = "stocks"
    __table_args__ = (UniqueConstraint("product_id", "warehouse_id", name="uq_stock_prod_wh"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    product = relationship("Product", lazy="joined")
    warehouse = relationship("Warehouse", lazy="joined")


class StockLedger(Base):
    """库存流水（只增不改）。`qty_after` 为变动后结存快照，便于对账与下钻。"""

    __tablename__ = "stock_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    biz_type: Mapped[str] = mapped_column(String(24), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(24), nullable=False)
    doc_id: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_no: Mapped[str] = mapped_column(String(32), nullable=False)
    src_doc_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    qty_change: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    qty_after: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )

    product = relationship("Product", lazy="joined")
    warehouse = relationship("Warehouse", lazy="joined")
