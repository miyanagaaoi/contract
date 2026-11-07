"""询价报价（CR-044，部门内部版）：询价单 / 询价行 / 供应商报价 / 报价行。

口径（PRD CR-044 已确认）：
- **纯内部使用**：不开放外部供货商账号，由本部门人员代录各家报价；
- 不与采购申请/采购单联动（只做记录与比价）；
- 一家供应商对一张询价单只有一份报价（可改价，保留 `updated_at`）；
- 金额口径：报价行填**含税单价** + 税率（默认 13%），比价按含税单价；
- 询价行是自由文本物料（不强制关联物料主数据，便于现场询价）。
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Date, DateTime, ForeignKey, Integer, Numeric, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

RFQ_STATUS = {"draft": "草稿", "open": "询价中", "closed": "已截止"}
QUOTE_CHANNELS = ("电话", "邮件", "微信", "到店", "其他")


class Rfq(Base):
    __tablename__ = "rfqs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_no: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    project: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft", index=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    lines: Mapped[list["RfqLine"]] = relationship(
        back_populates="rfq", cascade="all, delete-orphan", order_by="RfqLine.seq",
        lazy="selectin")
    quotes: Mapped[list["RfqQuote"]] = relationship(
        back_populates="rfq", cascade="all, delete-orphan", order_by="RfqQuote.id",
        lazy="selectin")


class RfqLine(Base):
    __tablename__ = "rfq_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rfq_id: Mapped[int] = mapped_column(
        ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    material_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    spec: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    qty: Mapped[float] = mapped_column(Numeric(16, 3), nullable=False, default=0)
    need_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True)

    rfq: Mapped[Rfq] = relationship(back_populates="lines")


class RfqQuote(Base):
    __tablename__ = "rfq_quotes"
    __table_args__ = (UniqueConstraint("rfq_id", "supplier_id", name="uq_rfq_quote_supplier"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rfq_id: Mapped[int] = mapped_column(
        ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    supplier_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    quote_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    rfq: Mapped[Rfq] = relationship(back_populates="quotes")
    items: Mapped[list["RfqQuoteItem"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", order_by="RfqQuoteItem.id",
        lazy="selectin")


class RfqQuoteItem(Base):
    __tablename__ = "rfq_quote_items"
    __table_args__ = (UniqueConstraint("quote_id", "line_id", name="uq_quote_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(
        ForeignKey("rfq_quotes.id", ondelete="CASCADE"), nullable=False, index=True)
    line_id: Mapped[int] = mapped_column(
        ForeignKey("rfq_lines.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_price: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False, default=0)  # 含税单价
    tax_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=13)
    moq: Mapped[float | None] = mapped_column(Numeric(16, 3), nullable=True)
    lead_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True)

    quote: Mapped[RfqQuote] = relationship(back_populates="items")
