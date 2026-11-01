"""发票自动匹配核销（CR-038）。

口径（2026-11-01 评估建议）：
- 对象：**进项发票** → 采购单（`status ∈ approved/completed`）；销项发票 → 销售订单（仅给建议，
  当前系统只支持进项绑定采购单）；
- 匹配因子（打分）：供应商/客户名称一致（+40）、价税合计与「未开票金额」差额
  （精确 +50；≤1% 或 ≤1 元 +30；≤5% +10）、开票日期与单据日期接近（≤7 天 +10）；
- 唯一最高分且 ≥80 → 自动绑定（复用 `finance_service.bind_invoices`，含确认入账与进度回写）；
- 否则只返回候选清单，由人工选择（不擅自绑定）。
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models_auth import User
from ..models_doc import INVOICE_IN, INVOICE_OUT, Invoice, PurchaseOrder, SalesOrder
from . import finance_service

ZERO = Decimal("0")
TARGET_STATUSES = ("approved", "completed")


def _money(value) -> Decimal:
    return Decimal(str(value or 0))


def _gap_score(gap: Decimal, base: Decimal) -> int:
    gap = abs(gap)
    if gap <= Decimal("0.01"):
        return 50
    if gap <= max(Decimal("1"), base * Decimal("0.01")):
        return 30
    if base > ZERO and gap <= base * Decimal("0.05"):
        return 10
    return 0


def _date_score(inv: Invoice, doc) -> int:
    d1, d2 = getattr(inv, "invoice_date", None), getattr(doc, "doc_date", None)
    if not d1 or not d2:
        return 0
    return 10 if abs((d1 - d2).days) <= 7 else 0


def suggest_matches(db: Session, inv: Invoice, limit: int = 5) -> list[dict]:
    """返回该发票的候选单据（按得分降序）。"""
    total = _money(inv.total_amount)
    out: list[dict] = []
    if inv.invoice_direction == INVOICE_IN:
        rows = (db.query(PurchaseOrder)
                .filter(PurchaseOrder.status.in_(TARGET_STATUSES),
                        PurchaseOrder.deleted == False)  # noqa: E712
                .order_by(PurchaseOrder.id.desc()).limit(200).all())
        for po in rows:
            score = 0
            if inv.seller_name and po.supplier_name == inv.seller_name:
                score += 40
            remain = _money(po.total_amount) - _money(po.invoiced_amount)
            score += _gap_score(total - remain, max(remain, total))
            score += _date_score(inv, po)
            if score >= 10:
                out.append({"target_type": "purchase_order", "target_id": po.id,
                            "target_no": po.doc_no, "party": po.supplier_name,
                            "total_amount": float(_money(po.total_amount)),
                            "invoiced_amount": float(_money(po.invoiced_amount)),
                            "remain_amount": float(remain), "score": score})
    elif inv.invoice_direction == INVOICE_OUT:
        rows = (db.query(SalesOrder)
                .filter(SalesOrder.status.in_(TARGET_STATUSES),
                        SalesOrder.deleted == False)  # noqa: E712
                .order_by(SalesOrder.id.desc()).limit(200).all())
        for so in rows:
            score = 0
            if inv.buyer_name and so.customer_name == inv.buyer_name:
                score += 40
            remain = _money(so.total_amount) - _money(so.invoiced_amount)
            score += _gap_score(total - remain, max(remain, total))
            score += _date_score(inv, so)
            if score >= 10:
                out.append({"target_type": "sales_order", "target_id": so.id,
                            "target_no": so.doc_no, "party": so.customer_name,
                            "total_amount": float(_money(so.total_amount)),
                            "invoiced_amount": float(_money(so.invoiced_amount)),
                            "remain_amount": float(remain), "score": score,
                            "note": "销项发票暂只给建议，需手工在销售侧核销"})
    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:limit]


def auto_match(db: Session, inv: Invoice, user: User) -> dict:
    """自动匹配：唯一高分候选 → 绑定；否则返回候选清单。"""
    if inv.status != "draft" or inv.bind_status == "bound":
        return {"matched": False, "reason": "发票已确认/已绑定，不能自动匹配", "candidates": []}
    if inv.is_red:
        return {"matched": False, "reason": "红字发票只做台账，不参与核销", "candidates": []}
    if inv.invoice_direction != INVOICE_IN:
        return {"matched": False, "reason": "仅进项发票支持自动绑定采购单",
                "candidates": suggest_matches(db, inv)}
    candidates = suggest_matches(db, inv)
    if not candidates:
        return {"matched": False, "reason": "未找到金额/供应商匹配的采购单", "candidates": []}
    top = candidates[0]
    if top["score"] < 80 or (len(candidates) > 1 and candidates[1]["score"] == top["score"]):
        return {"matched": False, "reason": "存在多个候选或匹配度不足，请手工选择",
                "candidates": candidates}
    po = db.get(PurchaseOrder, top["target_id"])
    result = finance_service.bind_invoices(db, po, [inv.id], user)
    ok = bool(result.get("bound"))
    return {"matched": ok, "candidate": top, "candidates": candidates,
            "bound": result.get("bound", []), "errors": result.get("errors", []),
            "reason": None if ok else "绑定失败"}
