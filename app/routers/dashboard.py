"""首页看板 API（T9 / T-V2-38，对应 AC-08 与 `11-erp-requirements.md` §15 / O15）。

内容（按登录人的权限自动裁剪，权限不足的区块返回空且标注 `available: false`）：
- `todo`            按角色待办：**待我审核**（我拥有该单据审核权限且状态为待审核）、
                    **我提交的**（待审核）、**我的草稿**；
- `stock_alerts`    库存预警：低于安全库存的「物料 × 仓库」清单（需 `stock.balance.view`）；
- `expiring/expired` 质保到期提醒（窗口天数取系统参数 `warranty_window_days`）；
- `contract_overview` 合同执行概览（受数据范围限制：金额、已付、付款比例、状态分布）。

`stats` / `expiring` / `expired` 字段保持 V1.0 结构不变，避免破坏既有看板页面。
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..dicts import get_sys_params
from ..models import Contract
from ..models_auth import User
from ..models_doc import DOC_MODELS, DOC_STATUS
from ..models_master import Product
from ..models_stock import Stock
from ..services.permission_service import apply_data_scope, collect_perms, require_perm

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_WINDOW_DAYS = 30          # 默认质保提醒窗口（可由系统参数覆盖）

# 单据查看 / 审核权限点（按 kind）
_VIEW_PERM = {
    "purchase_request": "purchase.request.view",
    "purchase_order": "purchase.order.view",
    "sales_request": "sales.request.view",
    "sales_order": "sales.order.view",
    "stock_in": "stock.in.view",
    "stock_out": "stock.out.view",
    "stock_take": "stock.take.view",
    "stock_transfer": "stock.transfer.view",      # V2.1/N13
}
_APPROVE_PERM = {
    "purchase_request": "purchase.request.approve",
    "purchase_order": "purchase.order.approve",
    "sales_request": "sales.request.approve",
    "sales_order": "sales.order.approve",
    "stock_in": "stock.in.approve",
    "stock_out": "stock.out.approve",
    "stock_take": "stock.take.approve",
    "stock_transfer": "stock.transfer.approve",   # V2.1/N13
}


def _summary(c: Contract) -> dict:
    days_left = None
    if c.warranty_end:
        days_left = (c.warranty_end - date.today()).days
    return {
        "id": c.id,
        "contract_no": c.contract_no,
        "name": c.name,
        "party_a": c.party_a,
        "party_b": c.party_b,
        "owner_name": c.owner_name,
        "status": c.status,
        "warranty_end": c.warranty_end.isoformat() if c.warranty_end else None,
        "days_left": days_left,
    }


def _doc_brief(doc) -> dict:
    return {
        "id": doc.id, "doc_type": doc.doc_type, "kind_label": getattr(type(doc), "label", ""),
        "doc_no": doc.doc_no,
        "doc_date": doc.doc_date.isoformat() if doc.doc_date else None,
        "status": doc.status, "status_label": DOC_STATUS.get(doc.status, doc.status),
        "created_by_name": doc.created_by_name,
        "party": (getattr(doc, "supplier_name", None) or getattr(doc, "customer_name", None)
                  or getattr(doc, "customer_name_text", None) or ""),
        "total_amount": float(getattr(doc, "total_amount", None) or 0),
    }


def _todos(db: Session, user: User, perms: set[str]) -> dict:
    """按角色待办：待我审核 / 我提交的 / 我的草稿。"""
    to_approve: list[dict] = []
    my_submitted: list[dict] = []
    my_draft_count = 0
    per_kind: dict[str, dict] = {}

    for kind, model in DOC_MODELS.items():
        view_perm = _VIEW_PERM.get(kind)
        if view_perm is None:
            continue        # 未登记权限映射的单据类型：待办面板跳过（防新增类型 KeyError 500）
        if not user.is_superadmin and view_perm not in perms:
            continue
        can_approve = user.is_superadmin or _APPROVE_PERM.get(kind) in perms
        scoped = apply_data_scope(db.query(model), model, user, db)

        draft_count = int(scoped.filter(model.status == "draft",
                                        model.created_by == user.id).count() or 0)
        my_draft_count += draft_count
        submitted = (scoped.filter(model.status == "submitted",
                                   (model.submitted_by == user.id) | (model.created_by == user.id))
                     .order_by(model.id.desc()).limit(20).all())
        my_submitted.extend(_doc_brief(d) for d in submitted)

        approve_rows = []
        if can_approve:
            approve_rows = (scoped.filter(model.status == "submitted")
                            .order_by(model.id.desc()).limit(20).all())
            to_approve.extend(_doc_brief(d) for d in approve_rows)

        per_kind[kind] = {
            "kind_label": getattr(model, "label", kind),
            "can_approve": can_approve,
            "draft": draft_count,
            "my_submitted": len(submitted),
            "to_approve": len(approve_rows) if can_approve else 0,
        }

    def _sort(rows: list[dict]) -> list[dict]:
        return sorted(rows, key=lambda r: (r["doc_date"] or "", r["id"]), reverse=True)[:20]

    return {
        "to_approve": {"total": len(to_approve), "items": _sort(to_approve)},
        "my_submitted": {"total": len(my_submitted), "items": _sort(my_submitted)},
        "my_draft": {"total": my_draft_count},
        "by_kind": per_kind,
    }


def _stock_alerts(db: Session, user: User, perms: set[str], limit: int = 20) -> dict:
    """库存预警：低于安全库存的「物料 × 仓库」。"""
    if not user.is_superadmin and "stock.balance.view" not in perms:
        return {"available": False, "total": 0, "items": []}
    query = (db.query(Stock)
             .join(Product, Stock.product_id == Product.id)
             .filter(Product.safety_stock.isnot(None),
                     Stock.qty < Product.safety_stock,
                     Product.status == "enabled"))
    total = int(query.count() or 0)
    rows = query.order_by((Product.safety_stock - Stock.qty).desc()).limit(limit).all()
    return {
        "available": True,
        "total": total,
        "items": [{
            "product_id": s.product_id,
            "product_code": s.product.code if s.product else None,
            "product_name": s.product.name if s.product else None,
            "warehouse_id": s.warehouse_id,
            "warehouse_name": s.warehouse.name if s.warehouse else None,
            "qty": float(s.qty or 0),
            "safety_stock": float(s.product.safety_stock) if s.product and s.product.safety_stock is not None else None,
            "shortage": float((s.product.safety_stock or 0) - (s.qty or 0)) if s.product else None,
        } for s in rows],
    }


def _contract_overview(db: Session, user: User) -> dict:
    """合同执行概览（受数据范围限制）。"""
    base = apply_data_scope(
        db.query(Contract).filter(Contract.deleted == False), Contract, user, db)  # noqa: E712
    total = int(base.count() or 0)
    amount_sum = base.with_entities(func.coalesce(func.sum(Contract.amount), 0)).scalar() or 0
    paid_sum = base.with_entities(func.coalesce(func.sum(Contract.paid_amount), 0)).scalar() or 0
    amount_sum, paid_sum = Decimal(str(amount_sum)), Decimal(str(paid_sum))
    ratio = float((paid_sum / amount_sum * Decimal("100")).quantize(Decimal("0.01"))) if amount_sum else None

    by_status = (base.with_entities(Contract.status, func.count(Contract.id))
                 .group_by(Contract.status).all())
    frameworks = int(base.filter(Contract.is_framework == True).count() or 0)  # noqa: E712
    warranty_open = int(base.filter(Contract.has_warranty == True,  # noqa: E712
                                    Contract.warranty_released == False).count() or 0)  # noqa: E712
    return {
        "total": total,
        "frameworks": frameworks,
        "amount_sum": float(amount_sum),
        "paid_sum": float(paid_sum),
        "paid_ratio": ratio,
        "warranty_open": warranty_open,
        "by_status": [{"status": s, "count": n} for s, n in by_status],
    }


@router.get("")
def dashboard(user: User = Depends(require_perm("dashboard.view")),
              db: Session = Depends(get_db)):
    today = date.today()
    params = get_sys_params(db)
    window = int(params.get("warranty_window_days") or _WINDOW_DAYS)
    horizon = today + timedelta(days=window)

    base = db.query(Contract).filter(Contract.deleted == False)  # noqa: E712
    pending = base.filter(Contract.has_warranty == True,  # noqa: E712
                          Contract.warranty_released == False,  # noqa: E712
                          Contract.warranty_end.isnot(None))
    expiring = pending.filter(Contract.warranty_end >= today, Contract.warranty_end <= horizon)
    expired = pending.filter(Contract.warranty_end < today)

    stats = {
        "total": base.count(),
        "frameworks": base.filter(Contract.is_framework == True).count(),  # noqa: E712
        "with_warranty": base.filter(Contract.has_warranty == True).count(),  # noqa: E712
        "expiring_count": expiring.count(),
        "expired_count": expired.count(),
        "window_days": window,
    }
    perms = collect_perms(db, user)
    return {
        "stats": stats,
        "expiring": [_summary(c) for c in expiring.order_by(Contract.warranty_end).limit(100)],
        "expired": [_summary(c) for c in expired.order_by(Contract.warranty_end).limit(100)],
        # ---- V2.0/M4：按角色的待办与预警 ----
        "todo": _todos(db, user, perms),
        "stock_alerts": _stock_alerts(db, user, perms),
        "contract_overview": _contract_overview(db, user),
        "generated_at": f"{today.isoformat()}",
    }
