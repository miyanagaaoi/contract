"""单据 ORM 模型（V2.0 / M2，对应 `12-erp-system-design.md` §4.4；V2.5 追加财务域）。

单据分三类共 **7 张主表**（采购申请/采购单/销售申请/销售订单/入库单/出库单/盘点单），
每张主表配一张行项表；公共字段由 `DocMixin` / `DocItemMixin` 承载，避免逐表重复定义：

- 状态机：`draft → submitted → approved`（可 `rejected` 回草稿），`completed` 为手工完成态；
  库存类单据（入库/出库/盘点）`approved` 即终态，不使用 `completed`；
- 库存过账：入库/出库单审核时过账（`posted=True`），反审核生成红冲流水（见 `posting_service`）；
- 下推：申请→采购单/销售订单（`ordered_qty`）、采购单/销售订单→出入库（`received_qty`/`shipped_qty`）。

**V2.5 财务域**（`docs/29` / `docs/30`）追加 3 张单据表与 3 张核销表：
付款单 / 收款单 / 发票（进项·销项同表）。它们**没有物料行项**，靠核销明细关联采购单/销售订单/
出入库单；审核（发票为"确认"）时把金额回写到目标单据的 `paid_amount` / `received_amount` /
`invoiced_amount`，反审核或作废时精确红冲 —— 与库存的"审核即过账 + 反审核红冲"同构，
`posted` 字段复用为"金额已记账"的幂等标记。

设计约定（`11` §14 / C-05）：库存只记数量不记成本；单级审核；单据可关联合同但不强制。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, declarative_mixin, mapped_column, relationship

from .database import Base

# 单据状态（文档与前端统一样本）
DOC_STATUS = {
    "draft": "草稿",
    "submitted": "待审核",
    "approved": "已审核",
    "completed": "已完成",
    "voided": "已作废",
}
DOC_STATUS_CODES = list(DOC_STATUS)
# 可编辑状态（仅草稿；驳回后回到草稿）
EDITABLE_STATUSES = {"draft"}

# 各单据类型的编码类别（对应 `dicts.DEFAULT_NUMBER_RULES` 的键）
DOC_KINDS = {
    "purchase_request": "采购申请单",
    "purchase_order": "采购单",
    "sales_request": "销售申请单",
    "sales_order": "销售订单",
    "stock_in": "入库单",
    "stock_out": "出库单",
    "stock_take": "盘点单",
    # ---- V2.5：财务域（见 `docs/29-v2.5-finance-requirements.md`）----
    "payment": "付款单",
    "receipt": "收款单",
    "invoice": "发票",
}

# 入库/出库类型（业务分类，用于流水 biz_type）
IN_TYPES = ["采购入库", "退货入库", "退库入库", "其他入库"]  # 退库入库：出库单退库生成（CR-022）
OUT_TYPES = ["销售出库", "领用出库", "其他出库"]
TAKE_TYPES = {"full": "全盘", "partial": "抽盘"}


@declarative_mixin
class DocMixin:
    """单据表头公共字段。"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_no: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    doc_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)          # 数据范围
    # V2.3（N2）：签约公司 —— 我方签约主体（取自系统设置「我方公司（主体码）」字典）。
    # 仅采购申请/采购单/销售申请/销售订单/入库单/出库单 6 类单据在接口层强制必填；
    # 盘点单等其余单据保留空列（DocMixin 为共享字段，避免逐表重复定义）。
    subject_code: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    subject_name: Mapped[str | None] = mapped_column(String(64), nullable=True)             # 快照
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_by_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    handler_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)            # 经办人
    handler_name: Mapped[str | None] = mapped_column(String(64), nullable=True)            # 经办人姓名快照（V2.1/N1）
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 关联合同（D3：可关联、非强制）
    contract_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    contract_no: Mapped[str | None] = mapped_column(String(64), nullable=True)             # 快照
    # 下推来源
    source_doc_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    source_doc_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_doc_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 审核痕迹
    submitted_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 库存过账标记（入库/出库单使用）
    posted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


@declarative_mixin
class DocItemMixin:
    """单据行项公共字段（物料与单位信息以**快照**保存，避免主数据改名影响历史单据）。"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    product_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    product_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    spec: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uom_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    uom_decimals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=Decimal("0"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, default=Decimal("0"))
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)               # 行级仓库（覆盖表头）
    warehouse_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    src_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)                # 下推来源行
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


# ==================== 采购申请单 ====================

class PurchaseRequest(Base, DocMixin):
    __tablename__ = "purchase_requests"

    doc_type = "purchase_request"
    direction = 0
    label = "采购申请单"

    request_dept_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 申请部门
    need_date: Mapped[date | None] = mapped_column(Date, nullable=True)           # 需求日期
    suggest_supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)              # 用途说明

    items: Mapped[list["PurchaseRequestItem"]] = relationship(
        back_populates="doc", cascade="all, delete-orphan", order_by="PurchaseRequestItem.seq",
        lazy="selectin",
    )


class PurchaseRequestItem(Base, DocItemMixin):
    __tablename__ = "purchase_request_items"

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_requests.id", ondelete="CASCADE"), index=True
    )
    ordered_qty: Mapped[Decimal] = mapped_column(                            # 已下推数量（AC-V2-16）
        Numeric(16, 3), nullable=False, default=Decimal("0")
    )

    doc: Mapped[PurchaseRequest] = relationship(back_populates="items")


# ==================== 采购单 ====================

class PurchaseOrder(Base, DocMixin):
    __tablename__ = "purchase_orders"

    doc_type = "purchase_order"
    direction = 0
    label = "采购单"

    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False, index=True)
    supplier_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")   # 快照
    purchase_dept_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_arrival_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    settle_type: Mapped[str | None] = mapped_column(String(24), nullable=True)            # 结算方式
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )
    receipt_warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)      # 默认收货仓库
    # V2.5：财务回写（审核付款单/进项发票时 +，反审核/作废红冲时 −，见 `finance_service`）
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0"), server_default="0")
    invoiced_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0"), server_default="0")

    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="doc", cascade="all, delete-orphan", order_by="PurchaseOrderItem.seq",
        lazy="selectin",
    )


class PurchaseOrderItem(Base, DocItemMixin):
    __tablename__ = "purchase_order_items"

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    received_qty: Mapped[Decimal] = mapped_column(                          # 已入库数量（AC-V2-18）
        Numeric(16, 3), nullable=False, default=Decimal("0")
    )

    doc: Mapped[PurchaseOrder] = relationship(back_populates="items")


# ==================== 销售申请单 ====================

class SalesRequest(Base, DocMixin):
    __tablename__ = "sales_requests"

    doc_type = "sales_request"
    direction = 0
    label = "销售申请单"

    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_name_text: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sales_dept_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expect_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    items: Mapped[list["SalesRequestItem"]] = relationship(
        back_populates="doc", cascade="all, delete-orphan", order_by="SalesRequestItem.seq",
        lazy="selectin",
    )


class SalesRequestItem(Base, DocItemMixin):
    __tablename__ = "sales_request_items"

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("sales_requests.id", ondelete="CASCADE"), index=True
    )
    ordered_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=Decimal("0"))

    doc: Mapped[SalesRequest] = relationship(back_populates="items")


# ==================== 销售订单 ====================

class SalesOrder(Base, DocMixin):
    __tablename__ = "sales_orders"

    doc_type = "sales_order"
    direction = 0
    label = "销售订单"

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    sales_dept_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ship_warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)         # 默认发货仓库
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )
    # V2.5：财务回写（审核收款单/销项发票时 +，红冲时 −）
    received_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0"), server_default="0")
    invoiced_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0"), server_default="0")

    items: Mapped[list["SalesOrderItem"]] = relationship(
        back_populates="doc", cascade="all, delete-orphan", order_by="SalesOrderItem.seq",
        lazy="selectin",
    )


class SalesOrderItem(Base, DocItemMixin):
    __tablename__ = "sales_order_items"

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"), index=True
    )
    shipped_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=Decimal("0"))

    doc: Mapped[SalesOrder] = relationship(back_populates="items")


# ==================== 入库单 ====================

class StockInOrder(Base, DocMixin):
    __tablename__ = "stock_in_orders"

    doc_type = "stock_in"
    direction = 1                     # 入库：+qty
    label = "入库单"

    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    warehouse_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    in_type: Mapped[str] = mapped_column(String(24), nullable=False, default="采购入库")
    supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )

    items: Mapped[list["StockInOrderItem"]] = relationship(
        back_populates="doc", cascade="all, delete-orphan", order_by="StockInOrderItem.seq",
        lazy="selectin",
    )


class StockInOrderItem(Base, DocItemMixin):
    __tablename__ = "stock_in_order_items"

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("stock_in_orders.id", ondelete="CASCADE"), index=True
    )

    doc: Mapped[StockInOrder] = relationship(back_populates="items")


# ==================== 出库单 ====================

class StockOutOrder(Base, DocMixin):
    __tablename__ = "stock_out_orders"

    doc_type = "stock_out"
    direction = -1                    # 出库：-qty
    label = "出库单"

    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    warehouse_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    out_type: Mapped[str] = mapped_column(String(24), nullable=False, default="销售出库")
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # V2.6.1：领用人（领用出库时记录；可选系统账号或客户档案）
    issue_party_type: Mapped[str | None] = mapped_column(String(16), nullable=True)   # user/customer
    issue_party_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issue_party_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )

    items: Mapped[list["StockOutOrderItem"]] = relationship(
        back_populates="doc", cascade="all, delete-orphan", order_by="StockOutOrderItem.seq",
        lazy="selectin",
    )


class StockOutOrderItem(Base, DocItemMixin):
    __tablename__ = "stock_out_order_items"

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("stock_out_orders.id", ondelete="CASCADE"), index=True
    )

    doc: Mapped[StockOutOrder] = relationship(back_populates="items")


# ==================== 盘点单 ====================

class StockTake(Base, DocMixin):
    __tablename__ = "stock_takes"

    doc_type = "stock_take"
    direction = 0
    label = "盘点单"

    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    warehouse_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    take_type: Mapped[str] = mapped_column(String(16), nullable=False, default="full")   # full/partial
    scope_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_in_id: Mapped[int | None] = mapped_column(Integer, nullable=True)          # 盘盈入库单 id
    generated_in_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    generated_out_id: Mapped[int | None] = mapped_column(Integer, nullable=True)         # 盘亏出库单 id
    generated_out_no: Mapped[str | None] = mapped_column(String(32), nullable=True)

    items: Mapped[list["StockTakeItem"]] = relationship(
        back_populates="doc", cascade="all, delete-orphan", order_by="StockTakeItem.seq",
        lazy="selectin",
    )


class StockTakeItem(Base, DocItemMixin):
    __tablename__ = "stock_take_items"

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("stock_takes.id", ondelete="CASCADE"), index=True
    )
    book_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=Decimal("0"))
    actual_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=Decimal("0"))
    diff_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=Decimal("0"))
    diff_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    doc: Mapped[StockTake] = relationship(back_populates="items")


# ==================== 调拨单（V2.1 / N13）====================

class StockTransfer(Base, DocMixin):
    """调拨单：单张单据表达"调出仓 → 调入仓"，**审核后同一事务内出+入**。

    - 仅支持**同一组织内**两仓库（Q4 冻结结论，跨组织不在本版范围）；
    - 不产生金额（行项 `unit_price` / `amount` 恒为 0），也不计入「货品总额度」
      （BR-V2.1-08 / BR-V2.1-09）；
    - `direction = 0`：**不参与** `direction` 驱动的过账逻辑，由专用 `post_transfer` 处理
      （现有一单双向无法用 `post_stock_doc` 表达，见 `23-v2.1-system-design.md` §6.1）。
    """

    __tablename__ = "stock_transfers"

    doc_type = "stock_transfer"
    direction = 0
    label = "调拨单"

    from_warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False, index=True
    )
    from_warehouse_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    to_warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False, index=True
    )
    to_warehouse_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # V2.3（N4）：调出单位 / 调入单位 —— 由两端仓库的**所属公司**自动带出的快照（只读），
    # 便于跨公司调拨时直接看出货物归属变化；仓库未设所属公司时为空。
    from_subject_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    from_subject_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_subject_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    to_subject_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    items: Mapped[list["StockTransferItem"]] = relationship(
        back_populates="doc", cascade="all, delete-orphan", order_by="StockTransferItem.seq",
        lazy="selectin",
    )


class StockTransferItem(Base, DocItemMixin):
    """调拨行项。仓库由表头两仓决定，故**不使用** `DocItemMixin.warehouse_id`。"""

    __tablename__ = "stock_transfer_items"

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("stock_transfers.id", ondelete="CASCADE"), index=True
    )

    doc: Mapped[StockTransfer] = relationship(back_populates="items")


# ==================== V2.5：财务域（付款单 / 收款单 / 发票） ====================
# 设计：`docs/30-v2.5-finance-system-design.md` §2。要点：
# - 三张单据表各自独立（不合并成 fund_orders + direction，与"一类单据一张表"一致）；
# - 核销用**多态** (target_type, target_id) 子表：付款可核销到采购单/入库单，收款到销售订单/出库单，
#   发票到采购单/销售订单 —— 单一外键表达不了，代价是库层无外键，写入只经 `finance_service`；
# - 目标单据的回写字段（`paid_amount` 等）与既有 `received_qty` 同构，列表零 join。

# 发票方向
INVOICE_IN = "in"          # 进项（供应商开给我方）
INVOICE_OUT = "out"        # 销项（我方开给客户）
INVOICE_DIRECTIONS = {INVOICE_IN: "进项发票", INVOICE_OUT: "销项发票"}

# 发票状态：**独立映射，不要并进 DOC_STATUS**
# `doc_routes` 把 DOC_STATUS 当所有工厂单据的状态下拉，加 confirmed 会让采购/销售列表
# 多出一个永远筛不到的选项；发票也不参与"提交→审核→完成"业务流（确认即记账）。
INVOICE_STATUS = {"draft": "草稿", "confirmed": "已确认", "voided": "已作废"}
INVOICE_AUTH_STATUS = {"pending": "待认证", "verified": "已认证"}

# 核销目标类型（多态）
ALLOCATION_TARGETS = {
    "purchase_order": "采购单",
    "sales_order": "销售订单",
    "stock_in": "入库单",
    "stock_out": "出库单",
}
# 各财务单据允许核销的目标类型（方向校验用）
PAY_TARGETS = ("purchase_order", "stock_in")
RECEIPT_TARGETS = ("sales_order", "stock_out")
INVOICE_TARGETS = ("purchase_order", "sales_order")


class PaymentOrder(Base, DocMixin):
    """付款单（V2.5）：我方付给**供应商**的款项，可核销到采购单/入库单。"""

    __tablename__ = "payment_orders"

    doc_type = "payment"
    direction = 0        # 不参与 `direction` 驱动的过账（同 StockTransfer 的说明）
    label = "付款单"

    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False, index=True
    )
    supplier_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    settle_type: Mapped[str | None] = mapped_column(String(24), nullable=True)     # 结算方式
    pay_account: Mapped[str | None] = mapped_column(String(64), nullable=True)     # 我方付款账户
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )

    # ---- V2.5 补充：对齐纸质《付款申请单》需要的字段（模板见 `docs/33`） ----
    payee_bank: Mapped[str | None] = mapped_column(String(128), nullable=True)      # 收款方开户银行
    payee_account: Mapped[str | None] = mapped_column(String(64), nullable=True)    # 收款方账号
    payer_bank: Mapped[str | None] = mapped_column(String(128), nullable=True)      # 我方（付款方）开户行
    category_l1: Mapped[str | None] = mapped_column(String(32), nullable=True)      # 一级分类（经营/经济/…）
    category_l2: Mapped[str | None] = mapped_column(String(64), nullable=True)      # 二级分类（具体费用）
    belong_period: Mapped[str | None] = mapped_column(String(32), nullable=True)    # 付款归属期（2026-09 / 以前年度）
    bank_purpose: Mapped[str | None] = mapped_column(String(64), nullable=True)     # 银行付款用途（预付款/代付款…）
    pay_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)      # 付款事由（与备注分开）
    plan_type: Mapped[str | None] = mapped_column(String(8), nullable=True)         # 计划内 / 计划外

    allocations: Mapped[list["PaymentAllocation"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan",
        order_by="PaymentAllocation.id", lazy="selectin",
    )


class PaymentAllocation(Base):
    """付款单的核销明细（多态目标：采购单 / 入库单）。"""

    __tablename__ = "payment_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payment_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_no: Mapped[str | None] = mapped_column(String(32), nullable=True)       # 单号快照
    amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    payment: Mapped[PaymentOrder] = relationship(back_populates="allocations")


class ReceiptOrder(Base, DocMixin):
    """收款单（V2.5）：收**客户**货款，可核销到销售订单/出库单（付款单镜像）。"""

    __tablename__ = "receipt_orders"

    doc_type = "receipt"
    direction = 0
    label = "收款单"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    settle_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    recv_account: Mapped[str | None] = mapped_column(String(64), nullable=True)    # 我方收款账户
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )

    allocations: Mapped[list["ReceiptAllocation"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan",
        order_by="ReceiptAllocation.id", lazy="selectin",
    )


class ReceiptAllocation(Base):
    """收款单的核销明细（多态目标：销售订单 / 出库单）。"""

    __tablename__ = "receipt_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("receipt_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    receipt: Mapped[ReceiptOrder] = relationship(back_populates="allocations")


class Invoice(Base, DocMixin):
    """发票（V2.5）：进项/销项同表，`invoice_direction` 区分。

    ⚠️ 列名用 `invoice_direction` 而**不是** `direction`：`direction` 在 `models_doc` 里是
    整数类属性约定（入库 +1 / 出库 −1 / 其余 0），`posting_service.post_stock_doc` 直接读它
    决定过账正负号；同名列若存 `"in"/"out"` 会让任何按约定读取的通用代码拿到错误方向。
    """

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("invoice_direction", "invoice_no", name="uq_invoices_direction_no"),
    )

    doc_type = "invoice"
    direction = 0
    label = "发票"

    invoice_direction: Mapped[str] = mapped_column(
        String(8), nullable=False, default=INVOICE_IN, index=True
    )
    invoice_code: Mapped[str | None] = mapped_column(String(32), nullable=True)    # 发票代码
    invoice_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    invoice_type: Mapped[str | None] = mapped_column(String(16), nullable=True)    # 专票/普票/电子
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)         # 开票日期
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)  # 13.00
    amount: Mapped[Decimal] = mapped_column(                 # 不含税金额
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )
    total_amount: Mapped[Decimal] = mapped_column(           # 价税合计（进度口径）
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )
    party_id: Mapped[int | None] = mapped_column(Integer, nullable=True)          # 进项=供应商 / 销项=客户
    party_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    auth_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    # ---- V2.6：发票同步（docs/38）----
    # sync_source：tax_platform = 电子发票服务平台同步；NULL = 手工录入。
    # bind_status：unbound（未确认）→ 绑定采购单后 bound（已确认）；解绑/作废回 unbound。
    sync_source: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bind_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unbound", index=True
    )
    # 同步落库的票面四要素快照（开票单位=销方 / 收票单位=购方）；手工录入为空，沿用 party_*
    seller_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    seller_tax_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    buyer_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    buyer_tax_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 签约公司（我方）快照：按 buyer_tax_no 匹配我方公司字典后落 code/name
    our_company_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    our_company_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # V2.6：红冲标记（同步时平台状态含"冲红"或价税合计为负 → is_red=True；
    # 红字票只做台账展示，不参与收票进度绑定）
    is_red: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    allocations: Mapped[list["InvoiceAllocation"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan",
        order_by="InvoiceAllocation.id", lazy="selectin",
    )


class InvoiceAllocation(Base):
    """发票的核销明细（进项→采购单 / 销项→销售订单）。`tax_amount` 仅供报表口径。"""

    __tablename__ = "invoice_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    invoice: Mapped[Invoice] = relationship(back_populates="allocations")


class InvoiceSyncLog(Base):
    """V2.6 发票同步日志（docs/38 §2.2）：一次「同步发票」操作一条记录。

    `status`：running → waiting_sms → success / failed。
    `tax_no` 是本次同步登录账号对应的纳税人识别号（同步主体快照）。
    """

    __tablename__ = "invoice_sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    subject_code: Mapped[str | None] = mapped_column(String(8), nullable=True)   # 我方主体码（V2.6 多公司）
    tax_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", index=True)
    fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


# 供通用服务/路由使用的注册表
DOC_MODELS: dict[str, type] = {
    "purchase_request": PurchaseRequest,
    "purchase_order": PurchaseOrder,
    "sales_request": SalesRequest,
    "sales_order": SalesOrder,
    "stock_in": StockInOrder,
    "stock_out": StockOutOrder,
    "stock_take": StockTake,
    "stock_transfer": StockTransfer,
    # V2.5：财务域（无物料行项，故不进 DOC_ITEM_MODELS）
    "payment": PaymentOrder,
    "receipt": ReceiptOrder,
    "invoice": Invoice,
}
DOC_ITEM_MODELS: dict[str, type] = {
    "purchase_request": PurchaseRequestItem,
    "purchase_order": PurchaseOrderItem,
    "sales_request": SalesRequestItem,
    "sales_order": SalesOrderItem,
    "stock_in": StockInOrderItem,
    "stock_out": StockOutOrderItem,
    "stock_take": StockTakeItem,
    "stock_transfer": StockTransferItem,
}


class PrintTemplate(Base):
    """单据打印模板（V2.2，BR-V2.2-02）。

    一种单据类型一条记录（`kind` 唯一）。配置以 **JSON 文本**存储：
    - 标题/副标题/页脚文字；
    - 区块顺序（标题区 / 表头信息 / 行项明细 / 签字与备注）；
    - 表头字段的显示、顺序、标签文字与是否独占整行；
    - 行项列的显示、顺序与标签文字；
    - 签字栏文字。

    之所以用 JSON 而不是逐字段建列：模板是**排版数据**、字段集合会随单据类型演进，
    加列会让迁移与模型同步成本远高于收益（见 `db_migrate.py` 的 SQLite 限制说明）。
    读取时统一与默认配置合并（`print_template_service.get_config`），
    因此新增可配置项时**老模板不会报错**。
    """

    __tablename__ = "print_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
