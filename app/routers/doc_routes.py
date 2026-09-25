"""单据路由工厂（T-V2-17，对应 `12-erp-system-design.md` §6.3）。

7 类单据的 REST 端点结构完全一致（列表/新增/详情/修改/提交/审核/驳回/完成/作废/反审核/变更历史），
故用工厂统一注册，各单据路由模块只提供**差异化的钩子**（特有字段处理、审核处理器、下推端点）：

```python
register_doc_routes(router, prefix="/api/purchase/requests", kind="purchase_request",
                    model=PurchaseRequest, perm_prefix="purchase.request", label="采购申请单",
                    create_hook=..., update_hook=...)
```

约定：服务层抛 `ValueError` → 统一转 HTTP 422 且回滚事务（保证审核失败时库存与状态都不变）。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models_auth import User
from ..models_doc import DOC_STATUS
from ..services import audit_service, doc_service, numbering_service
from ..services.permission_service import apply_data_scope, require_perm


def _guard(db: Session, fn, *args, **kwargs):
    """服务层 ValueError → 422（含事务回滚）。"""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))


def register_doc_routes(router: APIRouter, *, prefix: str, kind: str, model, perm_prefix: str,
                        label: str, create_hook=None, update_hook=None,
                        approve_handler=None, unapprove_handler=None) -> None:
    view_perm = require_perm(f"{perm_prefix}.view")
    create_perm = require_perm(f"{perm_prefix}.create")
    edit_perm = require_perm(f"{perm_prefix}.edit")
    submit_perm = require_perm(f"{perm_prefix}.submit")
    approve_perm = require_perm(f"{perm_prefix}.approve")
    void_perm = require_perm(f"{perm_prefix}.void")

    def _new_doc(db: Session, payload: dict, user: User):
        day = _guard(db, doc_service.parse_doc_date, payload.get("doc_date"))
        doc = model(
            doc_no=numbering_service.next_doc_no(db, kind, day),
            doc_date=day, status="draft",
            org_id=getattr(user, "org_id", None),
            created_by=getattr(user, "id", None),
            created_by_name=getattr(user, "real_name", None),
            handler_user_id=payload.get("handler_user_id") or getattr(user, "id", None),
            remark=(str(payload.get("remark") or "").strip() or None),
        )
        # 特有字段（含必填的仓库/供应商）必须在 flush 之前落值，否则会以 NULL 触发非空约束
        if create_hook is not None:
            _guard(db, create_hook, db, doc, payload)
        db.add(doc)
        db.flush()
        _guard(db, doc_service.bind_contract, db, doc, payload.get("contract_id"))
        _guard(db, doc_service.apply_items, db, doc, payload.get("items"),
               default_warehouse_id=getattr(doc, "warehouse_id", None))
        return doc

    @router.get(prefix, summary=f"{label}列表")
    def _list(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
              keyword: str | None = Query(None, description="单号/来源单号/合同号/往来单位/仓库"),
              status: str | None = Query(None, description="draft/submitted/approved/completed/voided"),
              date_from: str | None = Query(None), date_to: str | None = Query(None),
              include_voided: bool = Query(False, description="是否包含已作废（AC-V2-17）"),
              warehouse_id: int | None = Query(None), supplier_id: int | None = Query(None),
              customer_id: int | None = Query(None), contract_id: int | None = Query(None),
              handler_user_id: int | None = Query(None), product_id: int | None = Query(None),
              user: User = Depends(view_perm), db: Session = Depends(get_db)):
        if status and status not in DOC_STATUS:
            raise HTTPException(status_code=422, detail=f"无效状态：{status}")
        query = apply_data_scope(db.query(model), model, user, db)
        query = doc_service.apply_doc_filters(
            query, model, keyword=keyword, status=status, date_from=date_from, date_to=date_to,
            include_voided=include_voided or status == "voided")
        for field, value in (("warehouse_id", warehouse_id), ("supplier_id", supplier_id),
                             ("customer_id", customer_id), ("contract_id", contract_id),
                             ("handler_user_id", handler_user_id)):
            if value is not None and hasattr(model, field):
                query = query.filter(getattr(model, field) == value)
        if product_id is not None:
            query = query.filter(model.items.any(product_id=product_id))
        total = int(query.count() or 0)
        rows = (query.order_by(model.id.desc())
                .offset((page - 1) * page_size).limit(page_size).all())
        return {
            "items": [doc_service.fmt_doc(db, row, with_items=False) for row in rows],
            "total": total, "page": page, "page_size": page_size,
            "statuses": [{"code": c, "label": t} for c, t in DOC_STATUS.items()],
        }

    @router.post(prefix, summary=f"新增{label}")
    def _create(request: Request, payload: dict = Body(...),
                user: User = Depends(create_perm), db: Session = Depends(get_db)):
        doc = _new_doc(db, payload, user)
        audit_service.log(db, user, module=perm_prefix.split(".")[0], action="create",
                          object_type=kind, object_id=doc.id, object_no=doc.doc_no,
                          detail=f"新增{label}（{len(doc.items)} 行）", request=request)
        db.commit()
        return doc_service.fmt_doc(db, doc)

    @router.get(prefix + "/{doc_id}", summary=f"{label}详情")
    def _get(doc_id: int, user: User = Depends(view_perm), db: Session = Depends(get_db)):
        doc = _guard(db, doc_service.get_doc, db, model, doc_id)
        query = apply_data_scope(db.query(model).filter(model.id == doc.id), model, user, db)
        if query.first() is None:
            raise HTTPException(status_code=403, detail="无权查看该单据（超出数据范围）")
        return doc_service.fmt_doc(db, doc)

    @router.put(prefix + "/{doc_id}", summary=f"修改{label}")
    def _update(doc_id: int, request: Request, payload: dict = Body(...),
                user: User = Depends(edit_perm), db: Session = Depends(get_db)):
        doc = _guard(db, doc_service.get_doc, db, model, doc_id)
        _guard(db, doc_service.assert_editable, doc)
        if "doc_date" in payload:
            doc.doc_date = _guard(db, doc_service.parse_doc_date, payload.get("doc_date"))
        if "remark" in payload:
            doc.remark = str(payload.get("remark") or "").strip() or None
        if "handler_user_id" in payload:
            doc.handler_user_id = payload.get("handler_user_id") or None
        if "contract_id" in payload:
            _guard(db, doc_service.bind_contract, db, doc, payload.get("contract_id"))
        if update_hook is not None:
            _guard(db, update_hook, db, doc, payload)
        _guard(db, doc_service.apply_items, db, doc, payload.get("items"),
               default_warehouse_id=getattr(doc, "warehouse_id", None))
        audit_service.log(db, user, module=perm_prefix.split(".")[0], action="edit",
                          object_type=kind, object_id=doc.id, object_no=doc.doc_no,
                          detail=f"修改{label}", request=request)
        db.commit()
        return doc_service.fmt_doc(db, doc)

    @router.post(prefix + "/{doc_id}/submit", summary=f"提交{label}")
    def _submit(doc_id: int, request: Request, user: User = Depends(submit_perm),
                db: Session = Depends(get_db)):
        doc = _guard(db, doc_service.get_doc, db, model, doc_id)
        _guard(db, doc_service.submit, db, doc, user)
        audit_service.log(db, user, module=perm_prefix.split(".")[0], action="submit",
                          object_type=kind, object_id=doc.id, object_no=doc.doc_no,
                          request=request)
        db.commit()
        return doc_service.fmt_doc(db, doc)

    @router.post(prefix + "/{doc_id}/approve", summary=f"审核{label}")
    def _approve(doc_id: int, request: Request, user: User = Depends(approve_perm),
                 db: Session = Depends(get_db)):
        doc = _guard(db, doc_service.get_doc, db, model, doc_id)
        if approve_handler is not None:
            _guard(db, approve_handler, db, doc, user)
            detail = "审核通过（含库存过账）" if getattr(doc, "posted", False) else None
        else:
            _guard(db, doc_service.approve, db, doc, user)
            detail = "审核通过"
        audit_service.log(db, user, module=perm_prefix.split(".")[0], action="approve",
                          object_type=kind, object_id=doc.id, object_no=doc.doc_no,
                          detail=detail, request=request)
        db.commit()
        return doc_service.fmt_doc(db, doc)

    @router.post(prefix + "/{doc_id}/reject", summary=f"驳回{label}")
    def _reject(doc_id: int, request: Request, payload: dict = Body(default={}),
                user: User = Depends(approve_perm), db: Session = Depends(get_db)):
        doc = _guard(db, doc_service.get_doc, db, model, doc_id)
        _guard(db, doc_service.reject, db, doc, (payload or {}).get("reason"), user)
        audit_service.log(db, user, module=perm_prefix.split(".")[0], action="reject",
                          object_type=kind, object_id=doc.id, object_no=doc.doc_no,
                          detail=(payload or {}).get("reason"), request=request)
        db.commit()
        return doc_service.fmt_doc(db, doc)

    @router.post(prefix + "/{doc_id}/complete", summary=f"{label}置为已完成")
    def _complete(doc_id: int, request: Request, user: User = Depends(approve_perm),
                  db: Session = Depends(get_db)):
        doc = _guard(db, doc_service.get_doc, db, model, doc_id)
        _guard(db, doc_service.complete, db, doc, user)
        audit_service.log(db, user, module=perm_prefix.split(".")[0], action="complete",
                          object_type=kind, object_id=doc.id, object_no=doc.doc_no,
                          request=request)
        db.commit()
        return doc_service.fmt_doc(db, doc)

    @router.post(prefix + "/{doc_id}/void", summary=f"作废{label}")
    def _void(doc_id: int, request: Request, payload: dict = Body(default={}),
              user: User = Depends(void_perm), db: Session = Depends(get_db)):
        doc = _guard(db, doc_service.get_doc, db, model, doc_id)
        _guard(db, doc_service.void, db, doc, (payload or {}).get("reason"), user)
        audit_service.log(db, user, module=perm_prefix.split(".")[0], action="void",
                          object_type=kind, object_id=doc.id, object_no=doc.doc_no,
                          detail=(payload or {}).get("reason"), request=request)
        db.commit()
        return doc_service.fmt_doc(db, doc)

    @router.post(prefix + "/{doc_id}/unapprove", summary=f"反审核{label}")
    def _unapprove(doc_id: int, request: Request, payload: dict = Body(default={}),
                   user: User = Depends(approve_perm), db: Session = Depends(get_db)):
        doc = _guard(db, doc_service.get_doc, db, model, doc_id)
        if unapprove_handler is not None:
            _guard(db, unapprove_handler, db, doc, (payload or {}).get("reason"), user)
        else:
            _guard(db, doc_service.unapprove, db, doc, (payload or {}).get("reason"), user)
        audit_service.log(db, user, module=perm_prefix.split(".")[0], action="unapprove",
                          object_type=kind, object_id=doc.id, object_no=doc.doc_no,
                          detail=(payload or {}).get("reason"), request=request)
        db.commit()
        return doc_service.fmt_doc(db, doc)

    @router.get(prefix + "/{doc_id}/changelogs", summary=f"{label}变更历史")
    def _logs(doc_id: int, _user: User = Depends(view_perm), db: Session = Depends(get_db)):
        doc = _guard(db, doc_service.get_doc, db, model, doc_id)
        return doc_service.list_logs(db, doc)
