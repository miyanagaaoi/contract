"""财务服务（V2.5，见 `docs/29-v2.5-finance-requirements.md` / `docs/30-v2.5-finance-system-design.md`）。

## 这个模块存在的理由

付款单/收款单/发票的价值不在"记一笔"，而在**核销**：这笔钱、这张票对应哪张采购单/销售订单。
有了核销关系，列表才能按单据显示付款/收票进度（BR-V2.5-05），作废时才能精确红冲（BR-V2.5-02）。
因此本模块是财务域**唯一的写入口**：核销明细、回写金额、幂等标记都只在这里改，
避免"某处顺手 setattr"导致回写与明细长期不一致（配 `recalc_progress` 兜底）。

## 记账模型（与库存过账同构）

- 审核（付款/收款）与确认（发票）= **记账**：`posted=False → True`（原子条件更新），
  把核销金额回写到目标单据（`paid_amount` / `received_amount` / `invoiced_amount`）；
- 反审核（付款/收款）与作废（已确认发票）= **红冲**：`posted=True → False` 并精确回退；
- `posted` 复用 `DocMixin` 的既有字段（入库/出库用它表示"库存已过账"），
  既做幂等标记，也做"是否已记账"的查询条件（重算只统计 `posted=True` 的单据）。

> 原子更新后必须 `db.expire_all()`：`docs/27` §10.2 记录过"用 `synchronize_session=False`
> 抢占后，session 里的陈旧对象在后续 flush 把旧值写回、覆盖抢占结果"的真实缺陷。

## 回写字段的适用面

只有"有回写字段"的目标单据参与进度：采购单（`paid_amount`/`invoiced_amount`）、
销售订单（`received_amount`/`invoiced_amount`）。核销到入库单/出库单时**只登记不参与进度**
（这两类单据没有进度列）——数据不丢，口径清晰。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models_doc import (
    ALLOCATION_TARGETS,
    DOC_STATUS,
    INVOICE_AUTH_STATUS,
    INVOICE_STATUS,
    INVOICE_TARGETS,
    PAY_TARGETS,
    RECEIPT_TARGETS,
    Invoice,
    InvoiceAllocation,
    PaymentAllocation,
    PaymentOrder,
    PurchaseOrder,
    ReceiptAllocation,
    ReceiptOrder,
    SalesOrder,
    StockInOrder,
    StockOutOrder,
)
from . import doc_service

ZERO = Decimal("0")
CENT = Decimal("0.01")

# kind → (核销模型, 归属外键名, 允许的目标类型, 参与记账的**单据**状态)
_ALLOC: dict[str, tuple] = {
    "payment": (PaymentAllocation, "payment_id", PAY_TARGETS, ("approved",)),
    "receipt": (ReceiptAllocation, "receipt_id", RECEIPT_TARGETS, ("approved",)),
    "invoice": (InvoiceAllocation, "invoice_id", INVOICE_TARGETS, ("confirmed",)),
}
_KIND_MODEL: dict[str, type] = {"payment": PaymentOrder, "receipt": ReceiptOrder,
                                "invoice": Invoice}
_KIND_LABEL: dict[str, str] = {"payment": "付款单", "receipt": "收款单", "invoice": "发票"}
# 核销目标类型 → 模型
_TARGET_MODELS: dict[str, type] = {
    "purchase_order": PurchaseOrder,
    "sales_order": SalesOrder,
    "stock_in": StockInOrder,
    "stock_out": StockOutOrder,
}
# (财务单据类型, 核销目标类型) → 目标单据上的回写字段；未登记的即"只登记不参与进度"
_WRITE_FIELD: dict[tuple[str, str], str] = {
    ("payment", "purchase_order"): "paid_amount",
    ("receipt", "sales_order"): "received_amount",
    ("invoice", "purchase_order"): "invoiced_amount",
    ("invoice", "sales_order"): "invoiced_amount",
}
# 可被核销的目标单据状态（已审核/已完成；草稿不能核销，作废更不能）
_TARGET_OK_STATUSES = ("approved", "completed")


# ==================== 金额与核销明细 ====================

def parse_amount(value, field: str, *, allow_blank: bool = False) -> Decimal:
    """解析金额为 2 位小数；空值默认报错（金额类字段不允许静默变 0）。"""
    if value in (None, ""):
        if allow_blank:
            return ZERO
        raise ValueError(f"{field}必填")
    try:
        return Decimal(str(value)).quantize(CENT)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field}格式不正确")


def _require_target(db: Session, target_type: str, target_id: int):
    """校验核销目标：存在、未作废、已审核/已完成（BR-V2.5-03 的上游边界）。"""
    model = _TARGET_MODELS.get(target_type)
    if model is None:
        raise ValueError(f"不支持的核销目标类型：{target_type}")
    label = ALLOCATION_TARGETS.get(target_type, target_type)
    target = db.get(model, target_id)
    if target is None or getattr(target, "deleted", False):
        raise ValueError(f"核销的目标{label}不存在（#{target_id}）")
    if target.status == "voided":
        raise ValueError(f"目标{label} {target.doc_no} 已作废，不能核销")
    if target.status not in _TARGET_OK_STATUSES:
        raise ValueError(
            f"目标{label} {target.doc_no} 尚未审核，请先审核后再核销"
            f"（当前状态：{DOC_STATUS.get(target.status, target.status)}）")
    return target


def parse_allocations(db: Session, doc, rows, *, kind: str,
                      allowed: tuple[str, ...] | None = None) -> list:
    """**整体替换**核销明细（`rows=None` 表示不改动；`[]` 表示清空）。

    规则：

    - 目标类型必须属于该单据允许的方向（付款→采购线、收款→销售线、发票→购销两侧）；
      发票还会由调用方按"进项→采购单 / 销项→销售订单"传入 `allowed` 进一步收窄；
    - 同一目标只能有一行（防止同一张单据被重复核销而看不出来）；
    - 金额 > 0；**允许超过**目标单据金额（BR-V2.5-03：先付后补单是真实业务，超额由列表标红提示）。
    """
    if rows is None:
        return list(doc.allocations or [])
    if not isinstance(rows, list):
        raise ValueError("核销明细格式非法")

    _alloc_cls, _fk, kind_targets, _statuses = _ALLOC[kind]
    allowed = tuple(allowed or kind_targets)
    allowed_text = " / ".join(ALLOCATION_TARGETS[t] for t in allowed)
    doc.allocations.clear()
    seen: set[tuple[str, int]] = set()
    picked: list = []
    for idx, raw in enumerate(rows, start=1):
        raw = raw if isinstance(raw, dict) else {}
        target_type = str(raw.get("target_type") or "").strip()
        if target_type not in allowed:
            raise ValueError(f"第 {idx} 行：核销目标只能是{allowed_text}")
        raw_id = raw.get("target_id") or raw.get("id")
        try:
            target_id = int(raw_id)
        except (TypeError, ValueError):
            raise ValueError(f"第 {idx} 行：请选择核销的目标单据")
        if (target_type, target_id) in seen:
            raise ValueError(f"第 {idx} 行：同一目标单据只能有一行核销明细")
        seen.add((target_type, target_id))

        target = _require_target(db, target_type, target_id)
        amount = parse_amount(raw.get("amount"), f"第 {idx} 行核销金额")
        if amount <= 0:
            raise ValueError(f"第 {idx} 行：核销金额必须大于 0")
        alloc = _alloc_cls(
            target_type=target_type, target_id=target.id, target_no=target.doc_no,
            amount=amount,
            remark=(str(raw.get("remark") or "").strip() or None),
        )
        if kind == "invoice":
            # 税额只用于报表口径（不影响进度），允许留空
            alloc.tax_amount = parse_amount(raw.get("tax_amount"), f"第 {idx} 行税额",
                                            allow_blank=True)
        doc.allocations.append(alloc)
        picked.append(alloc)
    return picked


def allocations_total(doc) -> Decimal:
    """核销明细金额合计。"""
    return sum(((a.amount or ZERO) for a in (doc.allocations or [])), ZERO)


def unallocated_amount(doc) -> Decimal:
    """本单**未核销**金额 = 单据金额 − 已核销合计（可为负：多核销了）。

    注意与"目标单据还差多少"区分：后者由 `progress_of` 的 `num/den` 推出。
    """
    return (getattr(doc, "total_amount", None) or ZERO) - allocations_total(doc)


def over_condition(db: Session, model, kind: str):
    """SQL 侧"超额核销"条件（核销合计 > 单据金额），供列表/导出的 `over` 筛选复用。

    用相关子查询而不是 join + group by：列表分页的 `count()` 与 `order_by` 都不会被聚合打乱。
    """
    alloc_model, fk, _targets, _statuses = _ALLOC[kind]
    sub = (db.query(func.coalesce(func.sum(alloc_model.amount), 0))
           .filter(getattr(alloc_model, fk) == model.id)
           .scalar_subquery())
    return sub > model.total_amount


def fmt_allocations(doc) -> list[dict]:
    """核销明细的接口表示（详情与列表详情抽屉共用）。"""
    return [{
        "target_type": a.target_type,
        "target_label": ALLOCATION_TARGETS.get(a.target_type, a.target_type),
        "target_id": a.target_id,
        "target_no": a.target_no,
        "amount": float(a.amount or 0),
        "tax_amount": float(getattr(a, "tax_amount", ZERO) or 0),
        "remark": a.remark,
    } for a in (doc.allocations or [])]


# ==================== 记账 / 红冲 ====================

def _claim(db: Session, doc, *, on: bool) -> bool:
    """原子抢占/释放 `posted`（幂等 + 并发保护）。

    ⚠️ 这里有两个必须同时满足的约束（少一个都会产生难查的缺陷）：

    1. **先 `db.flush()`**：调用方此刻的 `status` 变更还是 pending 状态（`doc_service.approve`
       刚改完就进来）；若不 flush 就执行批量 `UPDATE`，紧随其后的 `expire_all()` 会把
       **尚未落库的修改丢掉** —— 实测表现为"审核后状态仍是待审核、回写金额却已加上"，
       金额与状态不一致。`docs/27` §10.2 记录过同源的"陈旧对象覆盖原子结果"缺陷，这是它的另一面。
    2. **后 `db.expire_all()`**：`synchronize_session=False` 不同步 session 内的对象，
       不 expire 就会让陈旧对象在后续 flush 时把 `posted` 写回旧值。
    """
    model = type(doc)
    db.flush()
    changed = (db.query(model)
               .filter(model.id == doc.id, model.posted == (not on))
               .update({"posted": on}, synchronize_session=False))
    db.expire_all()
    return bool(changed)


def _write_back(db: Session, doc, sign: int) -> list[dict]:
    """按核销明细回写目标单据金额（`sign=+1` 记账 / `-1` 红冲，不会出现负数）。"""
    changes: list[dict] = []
    for alloc in list(doc.allocations or []):
        field = _WRITE_FIELD.get((doc.doc_type, alloc.target_type))
        if field is None:
            continue                     # 入库单/出库单目标：只登记，不参与进度
        model = _TARGET_MODELS[alloc.target_type]
        target = db.get(model, alloc.target_id)
        if target is None:               # 目标被物理删除（正常流程不会）：跳过并由重算暴露
            continue
        old = getattr(target, field) or ZERO
        new = max(ZERO, old + sign * (alloc.amount or ZERO))
        setattr(target, field, new)
        changes.append({"doc_no": target.doc_no, "field": field,
                        "old": float(old), "new": float(new)})
    return changes


def _write_back_contract(db: Session, doc, sign: int) -> dict | None:
    """付款单审核/反审核时增量回写合同「累计已付」（BR-V2.5-12 / AC-V2.5-19）。

    口径（关键取舍）：

    - **增量加减**（`+= / -=`）而非"按单据重算"：合同上的历史付款多为人工补录，
      重算会把它们抹掉；增量法保留人工值，红冲也精确回退同一金额；
    - 金额取**付款单总额**（不是核销合计）：合同口径关心"这张合同付出去多少钱"，
      暂未对应到具体单据的预付款同样属于已付；
    - 只在付款单且**关联了合同**时生效；收款单不回写 —— 合同只有"累计已付"一个字段，
      销售侧"累计已收"本版不做（`docs/32` §4 已登记）。
    """
    if doc.doc_type != "payment" or not getattr(doc, "contract_id", None):
        return None
    from ..models import Contract

    contract = db.get(Contract, doc.contract_id)
    if contract is None:                       # 合同被物理删除（正常流程不会）
        return None
    old = contract.paid_amount or ZERO
    new = max(ZERO, old + sign * (getattr(doc, "total_amount", None) or ZERO))
    contract.paid_amount = new
    return {"contract_no": contract.contract_no, "old": float(old), "new": float(new)}


def _contract_note(contract: dict | None) -> str:
    return (f"，合同 {contract['contract_no']} 累计已付 {contract['old']:.2f}→{contract['new']:.2f}"
            if contract else "")


def approve_fund_doc(db: Session, doc, user) -> int:
    """付款单/收款单**审核 = 记账**（同事务；重复调用幂等短路）。"""
    if doc.status == "approved" and doc.posted:
        return 0
    doc_service.approve(db, doc, user)
    if not _claim(db, doc, on=True):
        return 0
    changes = _write_back(db, doc, 1)
    contract = _write_back_contract(db, doc, 1)
    doc_service.log(db, doc, "_finance", None, f"{allocations_total(doc)}",
                    note=f"审核记账：核销 {len(doc.allocations or [])} 行，"
                         f"回写 {len(changes)} 个目标单据" + _contract_note(contract))
    return len(changes)


def unapprove_fund_doc(db: Session, doc, reason: str, user) -> int:
    """付款单/收款单**反审核 = 红冲**（先校验下游与原因，再精确回退）。"""
    doc_service.unapprove(db, doc, reason, user)      # 含下游校验（push + finance）
    if not _claim(db, doc, on=False):
        return 0
    changes = _write_back(db, doc, -1)
    contract = _write_back_contract(db, doc, -1)
    doc_service.log(db, doc, "_finance", f"{allocations_total(doc)}", None,
                    note=f"反审核红冲：回退 {len(changes)} 个目标单据" + _contract_note(contract))
    return len(changes)


def confirm_invoice(db: Session, inv: Invoice, user) -> int:
    """发票**确认 = 记账**：`draft → confirmed` 并回写收票/开票金额（幂等）。"""
    if inv.status == "confirmed":
        return 0
    if inv.status != "draft":
        raise ValueError(
            f"当前状态（{INVOICE_STATUS.get(inv.status, inv.status)}）不可确认，请新建发票")
    inv.status = "confirmed"
    inv.approved_by = getattr(user, "id", None)
    inv.approved_at = datetime.now()
    doc_service.log(db, inv, "status", "draft", "confirmed", note="确认入账（计入进度）")
    if not _claim(db, inv, on=True):
        return 0
    changes = _write_back(db, inv, 1)
    doc_service.log(db, inv, "_finance", None, f"{allocations_total(inv)}",
                    note=f"确认入账：核销 {len(inv.allocations or [])} 行，"
                         f"回写 {len(changes)} 个目标单据")
    return len(changes)


def void_invoice(db: Session, inv: Invoice, reason: str, user) -> int:
    """发票作废：**已确认的先红冲再作废**（发票没有"反审核"，两个动作合一）。"""
    if not (reason or "").strip():
        raise ValueError("作废原因必填")
    if inv.status == "voided":
        raise ValueError("发票已作废")
    reverted = 0
    if inv.status == "confirmed":
        if _claim(db, inv, on=False):
            reverted = len(_write_back(db, inv, -1))
    old = inv.status
    inv.status = "voided"
    inv.voided_by = getattr(user, "id", None)
    inv.voided_at = datetime.now()
    inv.void_reason = reason.strip()
    doc_service.log(db, inv, "status", old, "voided",
                    note=f"作废：{reason.strip()}" + (f"（红冲 {reverted} 个目标单据）" if reverted else ""))
    return reverted


def verify_invoice(db: Session, inv: Invoice, auth_status: str, user) -> str:
    """认证状态流转（`pending ↔ verified`）。**不影响进度**（BR-V2.5-07）。"""
    status = str(auth_status or "").strip()
    if status not in INVOICE_AUTH_STATUS:
        raise ValueError("认证状态只能是待认证 / 已认证")
    if inv.status == "voided":
        raise ValueError("已作废的发票不能变更认证状态")
    old = inv.auth_status
    if old == status:
        return status
    inv.auth_status = status
    doc_service.log(db, inv, "auth_status", old, status,
                    note=f"认证状态：{INVOICE_AUTH_STATUS.get(old, old)} → "
                         f"{INVOICE_AUTH_STATUS.get(status, status)}")
    return status


# ==================== 下游保护 ====================

def assert_no_finance_downstream(db: Session, doc) -> None:
    """目标单据反审核/作废前：存在**已记账**的财务下游则拒绝（BR-V2.5-04）。

    只拦"已记账"（`posted=True`）的：草稿/待审核的付款单尚未影响任何金额，
    但它自己**审核时**会因"目标单据状态不合法"被 `_require_target` 挡住 —— 两道闸门合起来才完整。
    """
    for kind, (alloc_model, fk, _targets, active) in _ALLOC.items():
        doc_model = _KIND_MODEL[kind]
        row = (db.query(doc_model.doc_no)
               .join(alloc_model, getattr(alloc_model, fk) == doc_model.id)
               .filter(alloc_model.target_type == doc.doc_type,
                       alloc_model.target_id == doc.id,
                       doc_model.status.in_(active),
                       doc_model.posted == True)  # noqa: E712
               .first())
        if row is not None:
            raise ValueError(
                f"已存在已记账的{_KIND_LABEL[kind]} {row[0]}，"
                f"请先反审核该{_KIND_LABEL[kind]}后再操作")


def downstream_of(db: Session, doc) -> list[dict]:
    """目标单据关联的财务下游清单（详情展示与"能否反审核"判断用）。"""
    out: list[dict] = []
    for kind, (alloc_model, fk, _targets, active) in _ALLOC.items():
        doc_model = _KIND_MODEL[kind]
        rows = (db.query(doc_model.doc_no, doc_model.status, doc_model.doc_date,
                         doc_model.posted, alloc_model.amount)
                .join(alloc_model, getattr(alloc_model, fk) == doc_model.id)
                .filter(alloc_model.target_type == doc.doc_type,
                        alloc_model.target_id == doc.id)
                .order_by(doc_model.id.desc()).all())
        for doc_no, status, day, posted, amount in rows:
            label_map = INVOICE_STATUS if kind == "invoice" else DOC_STATUS
            out.append({
                "kind": kind, "kind_label": _KIND_LABEL[kind], "doc_no": doc_no,
                "status": status, "status_label": label_map.get(status, status),
                "doc_date": day.isoformat() if day else None,
                "amount": float(amount or 0), "posted": bool(posted),
            })
    return out


# ==================== 进度口径（唯一真源） ====================

def _pct(num: Decimal, den: Decimal) -> float | None:
    """百分比：分母为 0/None 时返回 None（前端显示 `—`，不是 0%）；保留 1 位小数。"""
    if not den or den <= 0:
        return None
    return float((num / den * 100).quantize(Decimal("0.1")))


def _item(name: str, num: Decimal, den: Decimal) -> dict:
    return {"num": float(num or 0), "den": float(den or 0), "pct": _pct(num or ZERO, den or ZERO),
            "over": bool(den and den > 0 and (num or ZERO) > den)}


def progress_of(doc) -> dict:
    """三/六条进度（分子/分母/百分比/是否超额）。

    - 收货进度（采购单）/ 发货进度（销售订单）：**数量**口径（Σ`received_qty`/Σ`qty`、
      Σ`shipped_qty`/Σ`qty`），数据由入库/出库过账回写，本函数只做汇总；
    - 付款/收票（采购单）、收款/开票（销售订单）：**含税金额**口径（BR-V2.5-05），
      分子取目标单据上的回写字段（审核时由 `_write_back` 维护）。

    键名即列语义（前端按 key 渲染，后端算 `pct`，避免前后端两套算法漂移）。
    """
    out: dict[str, dict] = {}
    if doc.doc_type not in ("purchase_order", "sales_order"):
        return out

    items = list(doc.items or [])
    if items:
        qty_den = sum((it.qty or ZERO) for it in items)
        if doc.doc_type == "purchase_order":
            qty_num = sum((it.received_qty or ZERO) for it in items)
            out["received_qty"] = _item("收货进度", qty_num, qty_den)
        else:
            qty_num = sum((it.shipped_qty or ZERO) for it in items)
            out["shipped_qty"] = _item("发货进度", qty_num, qty_den)

    den = Decimal(str(getattr(doc, "total_amount", None) or 0))
    if doc.doc_type == "purchase_order":
        out["paid_amount"] = _item("付款进度", Decimal(str(doc.paid_amount or 0)), den)
        out["invoiced_amount"] = _item("收票进度", Decimal(str(doc.invoiced_amount or 0)), den)
    else:
        out["received_amount"] = _item("收款进度", Decimal(str(doc.received_amount or 0)), den)
        out["invoiced_amount"] = _item("开票进度", Decimal(str(doc.invoiced_amount or 0)), den)
    return out


# ==================== 重算（运维兜底） ====================

def _aggregate(db: Session, kind: str) -> dict[tuple[str, int], Decimal]:
    """按核销明细聚合某类财务单据的核销金额（只算**已记账**的单据）。"""
    alloc_model, fk, _targets, active = _ALLOC[kind]
    doc_model = _KIND_MODEL[kind]
    rows = (db.query(alloc_model.target_type, alloc_model.target_id,
                     func.coalesce(func.sum(alloc_model.amount), 0))
            .join(doc_model, getattr(alloc_model, fk) == doc_model.id)
            .filter(doc_model.posted == True,  # noqa: E712
                    doc_model.status.in_(active))
            .group_by(alloc_model.target_type, alloc_model.target_id).all())
    return {(str(t), int(i)): Decimal(str(total or 0)) for t, i, total in rows}


def recalc_progress(db: Session, kinds: list[str] | None = None) -> dict:
    """按核销明细**重算**回写字段（不改明细、不改状态，可安全重复执行）。

    两个方向都校正：

    1. 明细合计 ≠ 回写值 → 以明细为准（覆盖）；
    2. 回写值非 0 但明细已无（明细被删 / 单据未记账）→ 归零。

    聚合键必须是 `(目标类型, 目标ID, 回写字段)` 三元组：销售订单上
    `received_amount`（收款单）与 `invoiced_amount`（发票）是两个独立字段，
    只按 (类型, ID) 聚合会把两类金额加在一起，写进**两个**字段 —— 那是静默的数据损坏。
    """
    picked = [k for k in _ALLOC if (kinds is None or k in kinds)]
    agg: dict[tuple[str, int, str], Decimal] = {}
    for kind in picked:
        for (target_type, target_id), total in _aggregate(db, kind).items():
            field = _WRITE_FIELD.get((kind, target_type))
            if field is None:
                continue
            key = (target_type, target_id, field)
            agg[key] = agg.get(key, ZERO) + total

    diffs: list[dict] = []
    fixed = 0
    checked = 0

    def _apply(target_type: str, target, field: str, want: Decimal) -> None:
        nonlocal fixed
        want = (want or ZERO).quantize(CENT)
        cur = (getattr(target, field) or ZERO).quantize(CENT)
        if cur == want:
            return
        diffs.append({"target_type": target_type, "doc_no": target.doc_no, "field": field,
                      "old": float(cur), "new": float(want)})
        setattr(target, field, want)
        fixed += 1

    # 方向 1：明细有值 → 覆盖回写
    for (target_type, target_id, field), want in sorted(agg.items()):
        target = db.get(_TARGET_MODELS[target_type], target_id)
        if target is None:
            continue
        checked += 1
        _apply(target_type, target, field, want)

    # 方向 2：回写非 0 但明细已无 → 归零
    for target_type in sorted({t for (_k, t) in _WRITE_FIELD}):
        model = _TARGET_MODELS[target_type]
        for field in sorted({f for (k, t), f in _WRITE_FIELD.items() if t == target_type}):
            rows = db.query(model).filter(getattr(model, field) != 0).all()
            for target in rows:
                if (target_type, target.id, field) in agg:
                    continue
                checked += 1
                _apply(target_type, target, field, ZERO)

    return {"kinds": picked, "checked": checked, "fixed": fixed, "diffs": diffs}


# ==================== 资金汇总（M3 起步） ====================

_SUMMARY_LIMIT = 8


def _open_expr(model, field: str):
    """未结金额表达式：单据含税总额 − 已回写金额（可为 0，不为负）。"""
    return (func.coalesce(model.total_amount, 0)
            - func.coalesce(getattr(model, field), 0))


def _open_block(db: Session, model, field: str, *, label_field: str) -> dict:
    """某一"未结"口径的合计 + 金额最大的若干张（列表页据此直接开工单）。"""
    expr = _open_expr(model, field)
    base = (model.status.in_(("approved", "completed")),
            model.deleted.is_(False), expr > 0)
    total = db.query(func.coalesce(func.sum(expr), 0)).filter(*base).scalar() or 0
    count = db.query(func.count(model.id)).filter(*base).scalar() or 0
    rows = (db.query(model).filter(*base).order_by(expr.desc())
            .limit(_SUMMARY_LIMIT).all())
    return {
        "amount": float(total), "count": int(count),
        "top": [{
            "id": r.id, "doc_no": r.doc_no,
            "party": getattr(r, label_field, None) or getattr(r, "party_name", None) or "",
            "doc_date": r.doc_date.isoformat() if r.doc_date else None,
            "total_amount": float(r.total_amount or 0),
            "done_amount": float(getattr(r, field) or 0),
            "open_amount": float((r.total_amount or 0) - (getattr(r, field) or 0)),
        } for r in rows],
    }


def summary(db: Session) -> dict:
    """资金概览：采购待付/待收票、销售待收/待开票、发票待认证、超额提醒。

    口径与进度列**同源**（都用回写字段），因此不会出现"看板说还欠 3 万、单据列表说未付 3 万"。
    只统计已审核/已完成且未删除的单据 —— 草稿与已作废单据不构成资金义务。
    """
    purchase_pay = _open_block(db, PurchaseOrder, "paid_amount",
                               label_field="supplier_name")
    purchase_inv = _open_block(db, PurchaseOrder, "invoiced_amount",
                               label_field="supplier_name")
    sales_recv = _open_block(db, SalesOrder, "received_amount",
                             label_field="customer_name")
    sales_inv = _open_block(db, SalesOrder, "invoiced_amount",
                            label_field="customer_name")

    pending_auth = (db.query(func.coalesce(func.sum(Invoice.total_amount), 0),
                             func.count(Invoice.id))
                    .filter(Invoice.status == "confirmed",
                            Invoice.auth_status == "pending",
                            Invoice.deleted.is_(False)).one())
    over_counts = {
        kind: int(db.query(func.count(model.id))
                  .filter(finance_over_condition(db, model, kind)).scalar() or 0)
        for kind, model in (("payment", PaymentOrder), ("receipt", ReceiptOrder),
                            ("invoice", Invoice))
    }
    return {
        "purchase": {"open_payment": purchase_pay, "open_invoice": purchase_inv},
        "sales": {"open_receipt": sales_recv, "open_invoice": sales_inv},
        "invoice": {"pending_auth_amount": float(pending_auth[0] or 0),
                    "pending_auth_count": int(pending_auth[1] or 0)},
        "over": over_counts,
    }


def finance_over_condition(db: Session, model, kind: str):
    """财务单据自身"超额核销"的库侧条件（列表筛选用）。"""
    return over_condition(db, model, kind)


# ==================== 应收/应付账龄（M3） ====================

AGING_BUCKETS: list[tuple[str, str, int, int | None]] = [
    ("b0_30", "0-30 天", 0, 30),
    ("b31_60", "31-60 天", 31, 60),
    ("b61_90", "61-90 天", 61, 90),
    ("b90_plus", "90 天以上", 91, None),
]


def aging(db: Session, *, as_of: date | None = None) -> dict:
    """应收/应付账龄（按**单据日期**分档；`as_of` 缺省今天，便于测试与月末口径）。

    口径与资金概览**同源**（已审核/已完成、未删除、含税差额 > 0），
    账龄天数 = `as_of` − `doc_date`（自然日）。

    起算日取**单据日期**而不是到期日：后者需要给采购单/销售订单加"付款/收款到期日"字段
    与录入项（口径待业务确认，见 `docs/31` M3 待办）；先按单据日期分档，零字段改动且够用。
    """
    today = as_of or date.today()
    out: dict = {"as_of": today.isoformat(), "buckets": [
        {"code": c, "label": l} for c, l, _lo, _hi in AGING_BUCKETS]}
    for key, model, field in (("purchase", PurchaseOrder, "paid_amount"),
                              ("sales", SalesOrder, "received_amount")):
        expr = _open_expr(model, field)
        rows = (db.query(model.doc_date, model.total_amount, getattr(model, field))
                .filter(model.status.in_(("approved", "completed")),
                        model.deleted.is_(False), expr > 0)
                .all())
        amounts = {c: 0.0 for c, _l, _lo, _hi in AGING_BUCKETS}
        counts = {c: 0 for c, _l, _lo, _hi in AGING_BUCKETS}
        total = 0.0
        for doc_date, total_amount, done in rows:
            open_amount = float((total_amount or 0) - (done or 0))
            days = (today - doc_date).days if doc_date else 0
            for code, _label, low, high in AGING_BUCKETS:
                if days >= low and (high is None or days <= high):
                    amounts[code] += open_amount
                    counts[code] += 1
                    break
            total += open_amount
        out[key] = {
            "total": round(total, 2),
            "count": sum(counts.values()),
            "buckets": [{"code": c, "label": l,
                         "amount": round(amounts[c], 2), "count": counts[c]}
                        for c, l, _lo, _hi in AGING_BUCKETS],
        }
    return out
