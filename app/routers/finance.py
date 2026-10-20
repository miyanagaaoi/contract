"""财务 API（V2.5，见 `docs/29-v2.5-finance-requirements.md` §5 与 `docs/30` §5）。

分三组：

- `/api/finance/payments`（付款单）：走通用单据工厂 `register_doc_routes`，
  状态机/详情/变更历史/打印全套复用，只在 `create_hook` / `update_hook` 里补
  "商户 + 金额 + 核销明细"，并把 `approve` / `unapprove` 换成**记账 / 红冲**处理器；
- `/api/finance/receipts`（收款单）：与付款单镜像；
- `/api/finance/invoices`（发票）：**不走工厂** —— 发票是"确认入账"式简化状态机
  （`draft → confirmed → voided`），且带认证状态，端点单独实现（仍复用编号/日志/数据范围工具）。

导出用自定义列（`_fund_export_columns` / `_invoice_export_columns`）：通用单据导出列里有
"行项数/仓库"，对财务单据没有意义；列必须与列表口径一致（AC-V2.5-16）。
"""
from __future__ import annotations

import json

from datetime import date

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models_auth import User
from ..models_doc import (
    DOC_STATUS,
    INVOICE_AUTH_STATUS,
    INVOICE_DIRECTIONS,
    INVOICE_IN,
    INVOICE_OUT,
    INVOICE_STATUS,
    Invoice,
    InvoiceSyncLog,
    PaymentOrder,
    PurchaseOrder,
    ReceiptOrder,
)
from ..services import audit_service, doc_service, finance_service, numbering_service
from ..services import tax_sync_service
from ..services.permission_service import apply_data_scope, require_perm
from .doc_routes import _guard, register_doc_routes
from .export import DOC_EXPORT_LIMIT, build_xlsx_response

router = APIRouter(prefix="/api/finance", tags=["finance"])

PAY_PREFIX = "/payments"
RECEIPT_PREFIX = "/receipts"
INVOICE_PREFIX = "/invoices"

#: 财务单据允许的结算方式（前端下拉与后端校验同一份取值）
SETTLE_TYPES = ["银行转账", "现金", "承兑汇票", "其他"]
#: 发票票种
INVOICE_TYPES = ["增值税专用发票", "增值税普通发票", "电子发票", "其他"]


# ==================== 通用小工具 ====================

def _money(value, field: str, *, allow_blank: bool = False):
    return finance_service.parse_amount(value, field, allow_blank=allow_blank)


def _text(payload: dict, key: str, limit: int) -> str | None:
    value = str(payload.get(key) or "").strip()
    return value[:limit] or None


def _fmt_dt(value) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None


def _scoped_or_403(db: Session, model, doc_id: int, user: User):
    """取单据并校验数据范围（与工厂的详情/打印同口径）。"""
    doc = _guard(db, doc_service.get_doc, db, model, doc_id)
    scoped = apply_data_scope(db.query(model).filter(model.id == doc.id), model, user, db)
    if scoped.first() is None:
        raise HTTPException(status_code=403, detail="无权查看该单据（超出数据范围）")
    return doc


# ==================== 付款单 / 收款单：特有字段与核销 ====================

def _apply_fund_fields(db: Session, doc, payload: dict) -> None:
    """付款单/收款单的 create_hook 与 update_hook（同构，靠 `doc.doc_type` 分支）。

    `doc.id is None` 表示新建：此时允许"未填总额 → 按核销明细合计兜底"，
    避免出现"核销了 3000、总额却是 0"这种看不出错的单据。
    """
    creating = doc.id is None
    is_payment = doc.doc_type == "payment"

    party_key = "supplier_id" if is_payment else "customer_id"
    if creating or party_key in payload:
        raw_id = payload.get(party_key) or getattr(doc, party_key, None)
        party = (_guard(db, doc_service.require_supplier, db, raw_id) if is_payment
                 else _guard(db, doc_service.require_customer, db, raw_id))
        if is_payment:
            doc.supplier_id, doc.supplier_name = party.id, party.name
        else:
            doc.customer_id, doc.customer_name = party.id, party.name

    if "settle_type" in payload or creating:
        settle = str(payload.get("settle_type") or "").strip()
        if settle and settle not in SETTLE_TYPES:
            raise ValueError(f"结算方式只能是：{' / '.join(SETTLE_TYPES)}")
        doc.settle_type = settle or None
    if "currency" in payload or creating:
        doc.currency = (str(payload.get("currency") or "CNY").strip() or "CNY")[:8]
    if is_payment:
        # 《付款申请单》版式字段（纸质模板对齐；收款单不需要）
        for key, limit in (("payee_bank", 128), ("payee_account", 64), ("payer_bank", 128),
                           ("category_l1", 32), ("category_l2", 64), ("belong_period", 32),
                           ("bank_purpose", 64), ("pay_reason", 255), ("plan_type", 8)):
            if key in payload:
                setattr(doc, key, _text(payload, key, limit))
    account_key = "pay_account" if is_payment else "recv_account"
    if account_key in payload:
        setattr(doc, account_key, _text(payload, account_key, 64))

    if "allocations" in payload:
        finance_service.parse_allocations(db, doc, payload.get("allocations"),
                                          kind=doc.doc_type)
    # 单行核销（M1 形态）时把"来源单据"快照写成该核销目标：用户看到的「来源单号」
    # 因此永远与「核销目标」一致，不会出现"来源写着 A、核销指向 B"的困惑。
    # 显式传了 source_doc_no（手工录入的历史单据）则尊重调用方。
    if ("allocations" in payload or creating) and not payload.get("source_doc_no"):
        rows = list(doc.allocations or [])
        if len(rows) == 1:
            doc.source_doc_type = rows[0].target_type
            doc.source_doc_id = rows[0].target_id
            doc.source_doc_no = rows[0].target_no

    if "total_amount" in payload:
        doc.total_amount = _money(payload.get("total_amount"), "金额")
    elif creating:
        total = finance_service.allocations_total(doc)
        if total <= 0:
            raise ValueError("请填写金额，或至少填写一行核销明细")
        doc.total_amount = total


def _fund_export_columns() -> list[tuple[str, int]]:
    return [("单据编号", 16), ("单据日期", 12), ("状态", 10), ("签约公司", 18),
            ("供应商/客户", 22), ("结算方式", 12), ("金额", 12), ("已核销", 12),
            ("未核销", 12), ("经办人", 12), ("关联合同", 18), ("来源单据", 18),
            ("备注", 20), ("创建时间", 20)]


def _fund_export_row(doc) -> list:
    party = getattr(doc, "supplier_name", None) or getattr(doc, "customer_name", None) or ""
    allocated = finance_service.allocations_total(doc)
    return [
        doc.doc_no,
        doc.doc_date.isoformat() if doc.doc_date else "",
        DOC_STATUS.get(doc.status, doc.status),
        getattr(doc, "subject_name", None) or getattr(doc, "subject_code", None) or "",
        party,
        doc.settle_type or "",
        float(doc.total_amount or 0),
        float(allocated),
        float((doc.total_amount or 0) - allocated),
        doc.created_by_name or "",
        doc.contract_no or "",
        doc.source_doc_no or "",
        (doc.remark or "")[:200],
        _fmt_dt(doc.created_at) or "",
    ]


def _register_fund_export(prefix: str, model, perm: str, label: str) -> None:
    """在工厂注册 `/{doc_id}` **之前**注册导出（否则 `export.xlsx` 会被当成 id 解析）。"""
    dep = require_perm(perm)

    @router.get(prefix + "/export.xlsx", summary=f"{label}导出（当前筛选）")
    def _export(keyword: str | None = Query(None), status: str | None = Query(None),
                date_from: str | None = Query(None), date_to: str | None = Query(None),
                include_voided: bool = Query(False),
                supplier_id: int | None = Query(None), customer_id: int | None = Query(None),
                contract_id: int | None = Query(None), subject_code: str | None = Query(None),
                over: bool = Query(False, description="只看超额核销"),
                user: User = Depends(dep), db: Session = Depends(get_db)):
        query = _fund_query(db, model, user, keyword=keyword, status=status,
                            date_from=date_from, date_to=date_to,
                            include_voided=include_voided, supplier_id=supplier_id,
                            customer_id=customer_id, contract_id=contract_id,
                            subject_code=subject_code, over=over)
        docs = query.order_by(model.id.desc()).limit(DOC_EXPORT_LIMIT).all()
        rows = [_fund_export_row(d) for d in docs]
        return build_xlsx_response(label, _fund_export_columns(), rows, label)


def _register_fund_list(prefix: str, model, perm: str, label: str, kind: str) -> None:
    """列表端点：在工厂的同名列表**之前**注册。

    为什么要覆盖工厂那一份：财务单据需要"只看超额核销"这一库侧筛选（AC-V2.5-06），
    以及 `over` / 已核销 / 未核销这些财务专有字段。工厂版列表只认通用筛选，
    若把超额筛选放到前端内存过滤，分页与总数就会失真。
    """
    dep = require_perm(perm)

    @router.get(prefix, summary=f"{label}列表")
    def _list(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
              keyword: str | None = Query(None, description="单号/来源单号/合同号/往来单位/备注"),
              status: str | None = Query(None, description="draft/submitted/approved/voided"),
              date_from: str | None = Query(None), date_to: str | None = Query(None),
              include_voided: bool = Query(False, description="是否包含已作废（AC-V2-17）"),
              supplier_id: int | None = Query(None), customer_id: int | None = Query(None),
              contract_id: int | None = Query(None), subject_code: str | None = Query(None),
              over: bool = Query(False, description="只看超额核销（核销合计 > 单据金额）"),
              user: User = Depends(dep), db: Session = Depends(get_db)):
        if status and status not in DOC_STATUS:
            raise HTTPException(status_code=422, detail=f"无效状态：{status}")
        query = _fund_query(db, model, user, keyword=keyword, status=status,
                            date_from=date_from, date_to=date_to,
                            include_voided=include_voided, supplier_id=supplier_id,
                            customer_id=customer_id, contract_id=contract_id,
                            subject_code=subject_code, over=over)
        total = int(query.count() or 0)
        rows = query.order_by(model.id.desc()).offset((page - 1) * page_size) \
            .limit(page_size).all()
        out = [doc_service.fmt_doc(db, row, with_items=False) for row in rows]
        _add_over_flag(rows, out)
        return {
            "items": out, "total": total, "page": page, "page_size": page_size,
            "statuses": [{"code": c, "label": t} for c, t in DOC_STATUS.items()],
        }


def _fund_query(db: Session, model, user: User, *, keyword=None, status=None,
                date_from=None, date_to=None, include_voided=False, supplier_id=None,
                customer_id=None, contract_id=None, subject_code=None, over=False):
    """付款/收款列表与导出共用的查询（单一数据源，AC-V2.5-16 与 AC-V2-40）。"""
    query = apply_data_scope(db.query(model), model, user, db)
    query = doc_service.apply_doc_filters(
        query, model, keyword=keyword, status=status, date_from=date_from,
        date_to=date_to, include_voided=include_voided or status == "voided")
    for field, value in (("supplier_id", supplier_id), ("customer_id", customer_id),
                         ("contract_id", contract_id), ("subject_code", subject_code)):
        if value is not None and hasattr(model, field):
            query = query.filter(getattr(model, field) == value)
    if over:
        query = query.filter(finance_service.over_condition(db, model, model.doc_type))
    return query


def _is_over(doc) -> bool:
    """是否超额核销（核销合计 > 单据金额；BR-V2.5-03 允许但要能被筛出来）。"""
    return finance_service.allocations_total(doc) > (doc.total_amount or 0)


def _add_over_flag(docs, out: list[dict]) -> None:
    for doc, row in zip(docs, out):
        row["over"] = _is_over(doc)


# ==================== 付款单 ====================

# 顺序要紧：列表/导出必须先于工厂注册（`export.xlsx` 与列表路径不能被 `/{doc_id}` 抢走）
_register_fund_export(PAY_PREFIX, PaymentOrder, "finance.payment.export", "付款单")
_register_fund_list(PAY_PREFIX, PaymentOrder, "finance.payment.view", "付款单", "payment")
register_doc_routes(router, prefix=PAY_PREFIX, kind="payment", model=PaymentOrder,
                    perm_prefix="finance.payment", label="付款单",
                    create_hook=_apply_fund_fields, update_hook=_apply_fund_fields,
                    approve_handler=finance_service.approve_fund_doc,
                    unapprove_handler=finance_service.unapprove_fund_doc,
                    sign_subject=True)


# ==================== 收款单 ====================

_register_fund_export(RECEIPT_PREFIX, ReceiptOrder, "finance.receipt.export", "收款单")
_register_fund_list(RECEIPT_PREFIX, ReceiptOrder, "finance.receipt.view", "收款单", "receipt")
register_doc_routes(router, prefix=RECEIPT_PREFIX, kind="receipt", model=ReceiptOrder,
                    perm_prefix="finance.receipt", label="收款单",
                    create_hook=_apply_fund_fields, update_hook=_apply_fund_fields,
                    approve_handler=finance_service.approve_fund_doc,
                    unapprove_handler=finance_service.unapprove_fund_doc,
                    sign_subject=True)


@router.get("/summary", summary="资金概览（待付/待收/待开票/待收票/待认证）")
def finance_summary(_user: User = Depends(require_perm("finance.payment.view")),
                    db: Session = Depends(get_db)):
    """口径与进度列同源（都取回写字段），避免"看板与列表对不上"。"""
    return finance_service.summary(db)


@router.get("/aging", summary="应收/应付账龄（按单据日期分档）")
def finance_aging(as_of: str | None = Query(None, description="基准日 YYYY-MM-DD，缺省今天"),
                  _user: User = Depends(require_perm("finance.payment.view")),
                  db: Session = Depends(get_db)):
    day = _guard(db, doc_service.parse_doc_date, as_of) if as_of else None
    return finance_service.aging(db, as_of=day)


@router.get("/aging.xlsx", summary="账龄导出（当前基准日）")
def finance_aging_export(as_of: str | None = Query(None),
                         _user: User = Depends(require_perm("finance.payment.view")),
                         db: Session = Depends(get_db)):
    """与页面同口径、同基准日（AC-V2.5-16 的"导出与界面一致"在资金视图上的延伸）。"""
    day = _guard(db, doc_service.parse_doc_date, as_of) if as_of else None
    data = finance_service.aging(db, as_of=day)
    columns = [("账龄区间", 14), ("采购待付金额", 16), ("采购待付单据数", 16),
               ("销售待收金额", 16), ("销售待收单据数", 16), ("合计金额", 16)]
    purchase = {b["code"]: b for b in data["purchase"]["buckets"]}
    sales = {b["code"]: b for b in data["sales"]["buckets"]}
    rows = [[b["label"], purchase[b["code"]]["amount"], purchase[b["code"]]["count"],
             sales[b["code"]]["amount"], sales[b["code"]]["count"],
             round(purchase[b["code"]]["amount"] + sales[b["code"]]["amount"], 2)]
            for b in data["buckets"]]
    rows.append(["合计", data["purchase"]["total"], data["purchase"]["count"],
                 data["sales"]["total"], data["sales"]["count"],
                 round(data["purchase"]["total"] + data["sales"]["total"], 2)])
    return build_xlsx_response(f"账龄{data['as_of']}", columns, rows, "账龄")


@router.get("/meta", summary="财务模块元数据（结算方式/票种/方向/状态）")
def finance_meta(_user: User = Depends(require_perm("finance.payment.view")),
                 _db: Session = Depends(get_db)):
    """前端下拉与筛选的取值真源（避免前后端各写一份中文枚举）。"""
    return {
        "settle_types": SETTLE_TYPES,
        "invoice_types": INVOICE_TYPES,
        "invoice_directions": [{"code": c, "label": t} for c, t in INVOICE_DIRECTIONS.items()],
        "invoice_statuses": [{"code": c, "label": t} for c, t in INVOICE_STATUS.items()],
        "invoice_auth_statuses": [{"code": c, "label": t} for c, t in INVOICE_AUTH_STATUS.items()],
        "doc_statuses": [{"code": c, "label": t} for c, t in DOC_STATUS.items()],
    }


@router.post("/recalc", summary="按核销明细重算进度回写（运维）")
def finance_recalc(request: Request,
                   user: User = Depends(require_perm("finance.payment.approve")),
                   db: Session = Depends(get_db)):
    """只重建聚合值（不改明细、不改状态），可安全重复执行；返回修正明细便于核对。"""
    result = _guard(db, finance_service.recalc_progress, db)
    audit_service.log(db, user, module="finance", action="recalc",
                      detail=f"进度重算：检查 {result['checked']} 条，修正 {result['fixed']} 条",
                      request=request)
    db.commit()
    return result


# ==================== 发票（简化状态机） ====================

def _apply_invoice_fields(db: Session, inv: Invoice, payload: dict, *, creating: bool) -> None:
    """发票票面字段与核销明细（新建与修改同构）。"""
    if creating or "invoice_direction" in payload or "direction" in payload:
        direction = str(payload.get("invoice_direction") or payload.get("direction")
                        or inv.invoice_direction or INVOICE_IN).strip()
        if direction not in INVOICE_DIRECTIONS:
            raise ValueError("发票方向只能是进项（in）或销项（out）")
        inv.invoice_direction = direction

    if creating or "invoice_no" in payload:
        invoice_no = str(payload.get("invoice_no") or "").strip()
        if not invoice_no:
            raise ValueError("发票号码必填")
        inv.invoice_no = invoice_no[:64]
    if "invoice_code" in payload:
        inv.invoice_code = _text(payload, "invoice_code", 32)
    if "invoice_type" in payload:
        inv_type = str(payload.get("invoice_type") or "").strip()
        if inv_type and inv_type not in INVOICE_TYPES:
            raise ValueError(f"票种只能是：{' / '.join(INVOICE_TYPES)}")
        inv.invoice_type = inv_type or None

    # 开票日期：`invoice_date` 为票面日期，`doc_date` 同步（列表排序/日期筛选走 doc_date）
    if creating or "invoice_date" in payload:
        if payload.get("invoice_date"):
            inv.invoice_date = _guard(db, doc_service.parse_doc_date, payload.get("invoice_date"))
            inv.doc_date = inv.invoice_date
        elif creating:
            inv.invoice_date = inv.doc_date or date.today()

    if "tax_rate" in payload:
        rate = str(payload.get("tax_rate") or "").strip()
        inv.tax_rate = _money(rate, "税率") if rate else None
    amounts_given = any(k in payload for k in ("amount", "tax_amount", "total_amount"))
    if "amount" in payload or creating:
        inv.amount = _money(payload.get("amount"), "不含税金额", allow_blank=True)
    if "tax_amount" in payload or creating:
        inv.tax_amount = _money(payload.get("tax_amount"), "税额", allow_blank=True)
    if "total_amount" in payload:
        inv.total_amount = _money(payload.get("total_amount"), "价税合计")
    elif creating or amounts_given:
        # 未填价税合计时按 不含税 + 税额 计算（两者都为 0 时由下面的核销明细兜底）
        inv.total_amount = (inv.amount or 0) + (inv.tax_amount or 0)

    # 往来单位：进项=供应商、销项=客户（快照）
    if inv.invoice_direction == INVOICE_IN:
        if creating or "party_id" in payload or "supplier_id" in payload:
            supplier = _guard(db, doc_service.require_supplier, db,
                              payload.get("party_id") or payload.get("supplier_id"))
            inv.party_id, inv.party_name = supplier.id, supplier.name
    else:
        if creating or "party_id" in payload or "customer_id" in payload:
            customer = _guard(db, doc_service.require_customer, db,
                              payload.get("party_id") or payload.get("customer_id"))
            inv.party_id, inv.party_name = customer.id, customer.name

    if "auth_status" in payload:
        status = str(payload.get("auth_status") or "").strip()
        if status and status not in INVOICE_AUTH_STATUS:
            raise ValueError("认证状态只能是待认证 / 已认证")
        inv.auth_status = status or "pending"

    # 核销方向必须与发票方向一致：进项只能核销采购单、销项只能核销销售订单
    if "allocations" in payload:
        allowed = ("purchase_order",) if inv.invoice_direction == INVOICE_IN else ("sales_order",)
        finance_service.parse_allocations(db, inv, payload.get("allocations"),
                                          kind="invoice", allowed=allowed)

    if not inv.source_doc_no:
        rows = list(inv.allocations or [])
        if len(rows) == 1:
            inv.source_doc_type = rows[0].target_type
            inv.source_doc_id = rows[0].target_id
            inv.source_doc_no = rows[0].target_no

    if creating and not inv.total_amount:
        total = finance_service.allocations_total(inv)
        if total <= 0:
            raise ValueError("请填写价税合计，或至少填写一行核销明细")
        inv.total_amount = total


def _check_invoice_unique(db: Session, inv: Invoice) -> None:
    dup = (db.query(Invoice)
           .filter(Invoice.invoice_direction == inv.invoice_direction,
                   Invoice.invoice_no == inv.invoice_no,
                   Invoice.id != (inv.id or 0))
           .first())
    if dup is not None:
        raise ValueError(f"该发票号已登记（{INVOICE_DIRECTIONS.get(dup.invoice_direction, '')} "
                         f"{dup.invoice_no}，单据 {dup.doc_no}）")


def _invoice_status_label(status: str) -> str:
    return INVOICE_STATUS.get(status, status)


def _invoice_export_columns() -> list[tuple[str, int]]:
    return [("单据编号", 16), ("方向", 10), ("发票号码", 20), ("发票代码", 16),
            ("开票日期", 12), ("状态", 10), ("认证状态", 10), ("票种", 16),
            ("往来单位", 22), ("不含税金额", 12), ("税额", 12), ("价税合计", 12),
            ("已核销", 12), ("签约公司", 18), ("经办人", 12), ("关联合同", 18),
            ("备注", 20), ("创建时间", 20)]


def _invoice_export_row(inv: Invoice) -> list:
    return [
        inv.doc_no,
        INVOICE_DIRECTIONS.get(inv.invoice_direction, inv.invoice_direction),
        inv.invoice_no,
        inv.invoice_code or "",
        inv.invoice_date.isoformat() if inv.invoice_date else "",
        _invoice_status_label(inv.status),
        INVOICE_AUTH_STATUS.get(inv.auth_status, inv.auth_status),
        inv.invoice_type or "",
        inv.party_name or "",
        float(inv.amount or 0),
        float(inv.tax_amount or 0),
        float(inv.total_amount or 0),
        float(finance_service.allocations_total(inv)),
        inv.subject_name or inv.subject_code or "",
        inv.created_by_name or "",
        inv.contract_no or "",
        (inv.remark or "")[:200],
        _fmt_dt(inv.created_at) or "",
    ]


def _invoice_query(db: Session, user: User, *, keyword=None, status=None, direction=None,
                   date_from=None, date_to=None, include_voided=False, party_id=None,
                   contract_id=None, subject_code=None, auth_status=None,
                   bind_status=None, is_red=None, has_file=None, invoice_type=None):
    from ..models import Attachment
    from sqlalchemy import exists

    query = apply_data_scope(db.query(Invoice), Invoice, user, db)
    query = doc_service.apply_doc_filters(
        query, Invoice, keyword=keyword, status=status, date_from=date_from,
        date_to=date_to, include_voided=include_voided or status == "voided")
    for field, value in (("invoice_direction", direction), ("party_id", party_id),
                         ("contract_id", contract_id),
                         ("auth_status", auth_status), ("bind_status", bind_status)):
        if value is not None and value != "":
            query = query.filter(getattr(Invoice, field) == value)
    if subject_code:
        # V2.6：筛选口径 = 收票单位（我方）。同步票落在 our_company_code、
        # 手工票落在 subject_code——两者任一命中即算匹配。
        query = query.filter((Invoice.subject_code == subject_code)
                             | (Invoice.our_company_code == subject_code))
    if is_red is not None and is_red != "":
        query = query.filter(Invoice.is_red == bool(is_red))
    if invoice_type:
        query = query.filter(Invoice.invoice_type == invoice_type)
    if has_file is not None:
        pdf_exists = exists().where(
            Attachment.object_type == "invoice", Attachment.object_id == Invoice.id,
            Attachment.deleted.is_(False), Attachment.file_name.ilike("%.pdf"))
        query = query.filter(pdf_exists if has_file else ~pdf_exists)
    return query


def _annotate_files(db: Session, items: list[dict]) -> None:
    """给发票列表行补 `has_pdf`（是否有发票包原始文件），一次查询避免 N+1。"""
    ids = [it["id"] for it in items]
    if not ids:
        return
    from ..models import Attachment

    rows = (db.query(Attachment.object_id)
            .filter(Attachment.object_type == "invoice", Attachment.object_id.in_(ids),
                    Attachment.deleted.is_(False),
                    Attachment.file_name.ilike("%.pdf"))
            .all())
    have = {r[0] for r in rows}
    for it in items:
        it["has_pdf"] = it["id"] in have


@router.get(INVOICE_PREFIX + "/export.xlsx", summary="发票导出（当前筛选）")
def invoice_export(keyword: str | None = Query(None), status: str | None = Query(None),
                   direction: str | None = Query(None, description="in=进项 / out=销项"),
                   auth_status: str | None = Query(None),
                   date_from: str | None = Query(None), date_to: str | None = Query(None),
                   include_voided: bool = Query(False), party_id: int | None = Query(None),
                   contract_id: int | None = Query(None), subject_code: str | None = Query(None),
                   user: User = Depends(require_perm("finance.invoice.export")),
                   db: Session = Depends(get_db)):
    query = _invoice_query(db, user, keyword=keyword, status=status, direction=direction,
                           date_from=date_from, date_to=date_to,
                           include_voided=include_voided, party_id=party_id,
                           contract_id=contract_id, subject_code=subject_code,
                           auth_status=auth_status)
    docs = query.order_by(Invoice.id.desc()).limit(DOC_EXPORT_LIMIT).all()
    return build_xlsx_response("发票", _invoice_export_columns(),
                               [_invoice_export_row(d) for d in docs], "发票")


@router.get(INVOICE_PREFIX, summary="发票列表")
def invoice_list(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
                 keyword: str | None = Query(None, description="单号/发票号/往来单位/备注"),
                 status: str | None = Query(None, description="draft/confirmed/voided"),
                 direction: str | None = Query(None, description="in=进项 / out=销项"),
                 auth_status: str | None = Query(None),
                 invoice_type: str | None = Query(None, description="票种筛选（V2.6）"),
                 bind_status: str | None = Query(None, description="unbound/bound（V2.6）"),
                 is_red: bool | None = Query(None, description="红字发票筛选（V2.6）"),
                 has_file: bool | None = Query(None, description="已下载原始文件筛选（V2.6）"),
                 sort: str = Query("invoice_date_desc",
                                   description="invoice_date_desc/invoice_date_asc/id_desc（V2.6 默认按开票日期倒序）"),
                 date_from: str | None = Query(None), date_to: str | None = Query(None),
                 include_voided: bool = Query(False), party_id: int | None = Query(None),
                 contract_id: int | None = Query(None), subject_code: str | None = Query(None),
                 user: User = Depends(require_perm("finance.invoice.view")),
                 db: Session = Depends(get_db)):
    if status and status not in INVOICE_STATUS:
        raise HTTPException(status_code=422, detail=f"无效状态：{status}")
    query = _invoice_query(db, user, keyword=keyword, status=status, direction=direction,
                           date_from=date_from, date_to=date_to,
                           include_voided=include_voided, party_id=party_id,
                           contract_id=contract_id, subject_code=subject_code,
                           auth_status=auth_status, bind_status=bind_status,
                           is_red=is_red, has_file=has_file, invoice_type=invoice_type)
    total = int(query.count() or 0)
    order = {"invoice_date_desc": (Invoice.invoice_date.desc(), Invoice.id.desc()),
             "invoice_date_asc": (Invoice.invoice_date.asc(), Invoice.id.asc()),
             "id_desc": (Invoice.id.desc(),)}.get(sort)
    if order is None:
        raise HTTPException(status_code=422, detail=f"无效排序：{sort}")
    for clause in order:
        query = query.order_by(clause)
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [doc_service.fmt_doc(db, row, with_items=False) for row in rows]
    _annotate_files(db, items)
    return {
        "items": items,
        "total": total, "page": page, "page_size": page_size,
        "statuses": [{"code": c, "label": t} for c, t in INVOICE_STATUS.items()],
    }


@router.post(INVOICE_PREFIX, summary="登记发票")
def invoice_create(request: Request, payload: dict = Body(...),
                   user: User = Depends(require_perm("finance.invoice.create")),
                   db: Session = Depends(get_db)):
    day = _guard(db, doc_service.parse_doc_date, payload.get("doc_date"))
    handler_user_id, handler_name = _guard(
        db, doc_service.handler_snapshot, db,
        payload.get("handler_user_id") or getattr(user, "id", None))
    inv = Invoice(
        doc_no=numbering_service.next_doc_no(db, "invoice", day),
        doc_date=day, status="draft",
        org_id=getattr(user, "org_id", None),
        created_by=getattr(user, "id", None),
        created_by_name=getattr(user, "real_name", None),
        handler_user_id=handler_user_id, handler_name=handler_name,
        source_doc_type=_text(payload, "source_doc_type", 24),
        source_doc_id=payload.get("source_doc_id") or None,
        source_doc_no=_text(payload, "source_doc_no", 32),
        remark=_text(payload, "remark", 2000),
    )
    _guard(db, _apply_invoice_fields, db, inv, payload, creating=True)
    _guard(db, doc_service.require_subject, db, payload.get("subject_code"))  # 必填校验
    _guard(db, doc_service.apply_subject, db, inv, payload)
    _guard(db, _check_invoice_unique, db, inv)
    db.add(inv)
    db.flush()
    _guard(db, doc_service.bind_contract, db, inv, payload.get("contract_id"))
    audit_service.log(db, user, module="finance", action="create",
                      object_type="invoice", object_id=inv.id, object_no=inv.doc_no,
                      detail=f"登记发票（{INVOICE_DIRECTIONS.get(inv.invoice_direction, '')} "
                             f"{inv.invoice_no}）", request=request)
    db.commit()
    return doc_service.fmt_doc(db, inv)


# ==================== V2.6：发票同步（docs/38） ====================
# ⚠️ 这些路由必须在 GET /invoices/{invoice_id} **之前**注册，避免 "sync" 被当作 int id 解析。

@router.get(INVOICE_PREFIX + "/sync-info", summary="同步状态概要（已配置公司/上次同步/会话保活）")
def invoice_sync_info(user: User = Depends(require_perm("finance.invoice.view")),
                      db: Session = Depends(get_db)):
    return tax_sync_service.last_sync_info(db)


@router.post(INVOICE_PREFIX + "/sync", summary="发起发票同步（电子发票服务平台，按主体码区分公司）")
def invoice_sync(payload: dict = Body(...), request: Request = None,
                 user: User = Depends(require_perm("finance.invoice.create")),
                 db: Session = Depends(get_db)):
    date_from = doc_service.parse_doc_date(payload.get("date_from"))
    date_to = doc_service.parse_doc_date(payload.get("date_to")) or date.today()
    subject_code = str(payload.get("subject_code") or "").strip()
    if not subject_code:
        raise HTTPException(status_code=422, detail="请选择要同步的我方公司（主体码）")
    try:
        log_id = tax_sync_service.start_sync(date_from, date_to, subject_code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    audit_service.log(db, user, module="finance", action="sync",
                      object_type="invoice_sync", object_id=log_id,
                      detail=f"发起发票同步 {date_from}~{date_to}（主体 {subject_code}）",
                      request=request)
    db.commit()
    return {"sync_id": log_id}


@router.get(INVOICE_PREFIX + "/sync/{log_id}", summary="轮询同步状态")
def invoice_sync_status(log_id: int,
                        user: User = Depends(require_perm("finance.invoice.view")),
                        db: Session = Depends(get_db)):
    log = db.get(InvoiceSyncLog, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="同步任务不存在")
    return {
        "id": log.id, "status": log.status,
        "subject_code": log.subject_code,
        "date_from": log.date_from.isoformat() if log.date_from else None,
        "date_to": log.date_to.isoformat() if log.date_to else None,
        "fetched": log.fetched, "inserted": log.inserted,
        "skipped_duplicate": log.skipped_duplicate,
        "message": log.message,
        "started_at": _fmt_dt(log.started_at), "finished_at": _fmt_dt(log.finished_at),
    }


@router.post(INVOICE_PREFIX + "/sync/{log_id}/sms", summary="提交同步登录短信验证码")
def invoice_sync_sms(log_id: int, payload: dict = Body(...),
                     user: User = Depends(require_perm("finance.invoice.create"))):
    code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=422, detail="验证码不能为空")
    if not tax_sync_service.submit_sms(log_id, code):
        raise HTTPException(status_code=404, detail="同步任务不存在或已结束")
    return {"ok": True}


@router.post(INVOICE_PREFIX + "/import-rows",
             summary="桥接同步：导入浏览器解析的发票行（开发环境通道）")
def invoice_import_rows(payload: dict = Body(...), request: Request = None,
                        user: User = Depends(require_perm("finance.invoice.create")),
                        db: Session = Depends(get_db)):
    """开发环境同步通道：DSH 浏览器桥从用户已登录的「全量发票查询」页读出行数据
    （normalize_row 口径的字典），本端点负责幂等入库。行格式：
    `{invoice_no, invoice_type, invoice_date, amount, tax_amount, total_amount,
      seller_name?, seller_tax_no?, buyer_name?, buyer_tax_no?}`。"""
    subject_code = str(payload.get("subject_code") or "").strip()
    rows = payload.get("rows") or []
    if not subject_code:
        raise HTTPException(status_code=422, detail="请选择要同步的我方公司（主体码）")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=422, detail="rows 不能为空")
    try:
        result = tax_sync_service.import_platform_rows(db, rows, subject_code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    audit_service.log(db, user, module="finance", action="import",
                      object_type="invoice_sync",
                      detail=f"桥接导入发票 {result['inserted']} 张（主体 {subject_code}，"
                             f"重复 {result['skipped_duplicate']}，红字 {result['skipped_red']}）",
                      request=request)
    db.commit()
    return result


@router.post(INVOICE_PREFIX + "/import-package",
             summary="导入「下载发票包」：解压并按数电票号挂附件")
async def invoice_import_package(request: Request, file: UploadFile = File(...),
                                 subject_code: str = Form(...),
                                 user: User = Depends(require_perm("finance.invoice.create")),
                                 db: Session = Depends(get_db)):
    data = await file.read()
    try:
        result = tax_sync_service.import_package(db, data, subject_code)
    except Exception as exc:  # noqa: BLE001 - 非压缩包等
        raise HTTPException(status_code=422, detail=f"发票包解析失败：{exc}")
    audit_service.log(db, user, module="finance", action="import_package",
                      object_type="invoice",
                      detail=f"发票包 {file.filename}：匹配 {len(result['attached'])} 张，"
                             f"未匹配 {len(result['unmatched'])} 个文件", request=request)
    db.commit()
    return result


@router.get(INVOICE_PREFIX + "/print-package", summary="批量打印发票原始文件（合并 PDF）")
def invoice_print_package(ids: str = Query(..., description="逗号分隔发票 id"),
                          user: User = Depends(require_perm("finance.invoice.view")),
                          db: Session = Depends(get_db)):
    """把所选发票的**原始 PDF**（发票包下载挂载的附件）按顺序合并成一个 PDF。

    打印的就是税务平台下发的原始版式文件——合规且与纸质票完全一致。
    """
    import io

    from fastapi.responses import Response
    from pypdf import PdfWriter

    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=422, detail="ids 格式错误")
    if not id_list:
        raise HTTPException(status_code=422, detail="请选择要打印的发票")
    from ..config import UPLOAD_DIR
    from ..models import Attachment

    writer = PdfWriter()
    merged, skipped = 0, []
    for inv_id in id_list:
        inv = db.get(Invoice, inv_id)
        if inv is None:
            skipped.append(f"#{inv_id} 不存在")
            continue
        att = (db.query(Attachment)
               .filter(Attachment.object_type == "invoice", Attachment.object_id == inv_id,
                       Attachment.deleted.is_(False), Attachment.file_name.ilike("%.pdf"))
               .order_by(Attachment.id.desc())
               .first())
        if att is None:
            skipped.append(f"{inv.invoice_no} 未上传原始文件")
            continue
        path = UPLOAD_DIR / att.stored_path
        if not path.is_file():
            skipped.append(f"{inv.invoice_no} 文件丢失")
            continue
        try:
            writer.append(str(path))
            merged += 1
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"{inv.invoice_no} 读取失败: {exc}")
    if merged == 0:
        raise HTTPException(status_code=422,
                            detail="没有可打印的原始文件：" + "；".join(skipped[:5]))
    buf = io.BytesIO()
    writer.write(buf)
    audit_service.log(db, user, module="finance", action="print",
                      object_type="invoice", detail=f"批量打印 {merged} 张发票原始文件",
                      request=None)
    db.commit()
    return Response(
        content=buf.getvalue(), media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="invoice-print.pdf"',
                 "X-Skipped": "; ".join(skipped)[:400]})


@router.get(INVOICE_PREFIX + "/{invoice_id}/files", summary="发票原始文件列表（打印发票用）")
def invoice_files(invoice_id: int,
                  user: User = Depends(require_perm("finance.invoice.view")),
                  db: Session = Depends(get_db)):
    from ..models import Attachment

    atts = (db.query(Attachment)
            .filter(Attachment.object_type == "invoice", Attachment.object_id == invoice_id,
                    Attachment.deleted.is_(False))
            .order_by(Attachment.id.desc())
            .all())
    return {"files": [
        {"id": a.id, "file_name": a.file_name, "size_bytes": a.size_bytes,
         "is_pdf": a.file_name.lower().endswith(".pdf"),
         "preview_url": f"/attachments/{a.id}/download"}
        for a in atts
    ]}


@router.post(INVOICE_PREFIX + "/bind", summary="采购单绑定进项发票（多选，V2.6 弹窗）")
def invoice_bind(payload: dict = Body(...), request: Request = None,
                 user: User = Depends(require_perm("finance.invoice.create")),
                 db: Session = Depends(get_db)):

    po_id = payload.get("purchase_order_id")
    invoice_ids = payload.get("invoice_ids") or []
    if not po_id or not isinstance(invoice_ids, list) or not invoice_ids:
        raise HTTPException(status_code=422, detail="purchase_order_id 与 invoice_ids 必填")
    po = db.get(PurchaseOrder, int(po_id))
    if po is None or po.deleted:
        raise HTTPException(status_code=404, detail="采购单不存在")
    result = finance_service.bind_invoices(db, po, [int(i) for i in invoice_ids], user)
    audit_service.log(db, user, module="finance", action="bind",
                      object_type="purchase_order", object_id=po.id, object_no=po.doc_no,
                      detail=f"绑定进项发票 {len(result['bound'])} 张"
                             + (f"，失败 {len(result['errors'])} 张" if result["errors"] else ""),
                      request=request)
    db.commit()
    return result


@router.post(INVOICE_PREFIX + "/{invoice_id}/unbind", summary="解绑发票（回到未确认，V2.6）")
def invoice_unbind(invoice_id: int, request: Request,
                   user: User = Depends(require_perm("finance.invoice.create")),
                   db: Session = Depends(get_db)):
    inv = _scoped_or_403(db, Invoice, invoice_id, user)
    try:
        reverted = finance_service.unbind_invoice(db, inv, user)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    audit_service.log(db, user, module="finance", action="unbind",
                      object_type="invoice", object_id=inv.id, object_no=inv.invoice_no,
                      detail=f"解绑红冲 {reverted}", request=request)
    db.commit()
    return {"ok": True, "reverted": float(reverted)}


@router.get(INVOICE_PREFIX + "/{invoice_id}", summary="发票详情")
def invoice_get(invoice_id: int,
                user: User = Depends(require_perm("finance.invoice.view")),
                db: Session = Depends(get_db)):
    inv = _scoped_or_403(db, Invoice, invoice_id, user)
    return doc_service.fmt_doc(db, inv)


@router.put(INVOICE_PREFIX + "/{invoice_id}", summary="修改发票")
def invoice_update(invoice_id: int, request: Request, payload: dict = Body(...),
                   user: User = Depends(require_perm("finance.invoice.edit")),
                   db: Session = Depends(get_db)):
    inv = _guard(db, doc_service.get_doc, db, Invoice, invoice_id)
    _guard(db, doc_service.assert_editable, inv)
    if "doc_date" in payload:
        inv.doc_date = _guard(db, doc_service.parse_doc_date, payload.get("doc_date"))
    if "remark" in payload:
        inv.remark = _text(payload, "remark", 2000)
    if "handler_user_id" in payload:
        inv.handler_user_id, inv.handler_name = _guard(
            db, doc_service.handler_snapshot, db, payload.get("handler_user_id"))
    if "contract_id" in payload:
        _guard(db, doc_service.bind_contract, db, inv, payload.get("contract_id"))
    if "subject_code" in payload:
        _guard(db, doc_service.apply_subject, db, inv, payload)
    if "source_doc_no" in payload or "source_doc_id" in payload:
        inv.source_doc_type = _text(payload, "source_doc_type", 24) or inv.source_doc_type
        inv.source_doc_id = payload.get("source_doc_id") or inv.source_doc_id
        inv.source_doc_no = _text(payload, "source_doc_no", 32) or inv.source_doc_no
    _guard(db, _apply_invoice_fields, db, inv, payload, creating=False)
    _guard(db, _check_invoice_unique, db, inv)
    audit_service.log(db, user, module="finance", action="edit",
                      object_type="invoice", object_id=inv.id, object_no=inv.doc_no,
                      detail="修改发票", request=request)
    db.commit()
    return doc_service.fmt_doc(db, inv)


@router.post(INVOICE_PREFIX + "/{invoice_id}/confirm", summary="确认发票入账（记账）")
def invoice_confirm(invoice_id: int, request: Request,
                    user: User = Depends(require_perm("finance.invoice.confirm")),
                    db: Session = Depends(get_db)):
    inv = _guard(db, doc_service.get_doc, db, Invoice, invoice_id)
    reverted = _guard(db, finance_service.confirm_invoice, db, inv, user)
    audit_service.log(db, user, module="finance", action="approve",
                      object_type="invoice", object_id=inv.id, object_no=inv.doc_no,
                      detail=f"确认入账（回写 {reverted} 个目标单据）", request=request)
    db.commit()
    return doc_service.fmt_doc(db, inv)


@router.post(INVOICE_PREFIX + "/{invoice_id}/verify", summary="发票认证状态流转")
def invoice_verify(invoice_id: int, request: Request, payload: dict = Body(default={}),
                   user: User = Depends(require_perm("finance.invoice.confirm")),
                   db: Session = Depends(get_db)):
    inv = _guard(db, doc_service.get_doc, db, Invoice, invoice_id)
    status = _guard(db, finance_service.verify_invoice, db, inv,
                    (payload or {}).get("auth_status"), user)
    audit_service.log(db, user, module="finance", action="edit", object_type="invoice",
                      object_id=inv.id, object_no=inv.doc_no,
                      detail=f"认证状态：{INVOICE_AUTH_STATUS.get(status, status)}",
                      request=request)
    db.commit()
    return doc_service.fmt_doc(db, inv)


@router.post(INVOICE_PREFIX + "/{invoice_id}/void", summary="作废发票（已确认的先红冲）")
def invoice_void(invoice_id: int, request: Request, payload: dict = Body(default={}),
                 user: User = Depends(require_perm("finance.invoice.void")),
                 db: Session = Depends(get_db)):
    inv = _guard(db, doc_service.get_doc, db, Invoice, invoice_id)
    reverted = _guard(db, finance_service.void_invoice, db, inv,
                      (payload or {}).get("reason"), user)
    audit_service.log(db, user, module="finance", action="void", object_type="invoice",
                      object_id=inv.id, object_no=inv.doc_no,
                      detail=f"作废发票（红冲 {reverted} 个目标单据）", request=request)
    db.commit()
    return doc_service.fmt_doc(db, inv)


@router.get(INVOICE_PREFIX + "/{invoice_id}/changelogs", summary="发票变更历史")
def invoice_logs(invoice_id: int,
                 _user: User = Depends(require_perm("finance.invoice.view")),
                 db: Session = Depends(get_db)):
    inv = _guard(db, doc_service.get_doc, db, Invoice, invoice_id)
    return doc_service.list_logs(db, inv)


@router.get(INVOICE_PREFIX + "/{invoice_id}/print", summary="发票打印（A4）",
            response_class=HTMLResponse)
def invoice_print(invoice_id: int,
                  signers: str | None = Query(
                      None, description='签字位预填姓名（JSON，如 {"制单":"张三"}）'),
                  user: User = Depends(require_perm("finance.invoice.view")),
                  db: Session = Depends(get_db)):
    from ..services.print_service import build_doc_print_html, parse_signers

    inv = _scoped_or_403(db, Invoice, invoice_id, user)
    # 与单据打印同一 `signers` 口径（账号 id 嵌签名图，姓名文本兼容；渲染层转义）
    return HTMLResponse(content=build_doc_print_html(db, inv, signers=parse_signers(signers)))
