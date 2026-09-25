"""资料库（主数据）API（T-V2-07~11，对应 `12-erp-system-design.md` §6.2）。

资源与权限点：
- 客户        `/api/master/customers`         master.customer.view / .edit
- 供应商      `/api/master/suppliers`         master.supplier.view / .edit
- 商品类型    `/api/master/product-types`     master.ptype.view / .edit
- 计量单位    `/api/master/uoms`              master.uom.view / .edit
- 仓库        `/api/master/warehouses`        master.wh.view / .edit
- 物料        `/api/master/products`          master.product.view / .edit

统一约定：
- `GET` 列表（关键字 + 状态筛选，客户/供应商/物料分页）、`POST` 新增、`GET/{id}` 详情、
  `PUT/{id}` 修改、`PUT/{id}/status` 停用/启用、`DELETE/{id}` 删除（有引用时 422 提示改为停用）；
- `GET /api/master/options/{kind}` 轻量下拉（供单据页与合同表单引用），**登录即可**；
- 写操作全部记操作日志（`module="master"`）。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models_auth import User
from ..services import audit_service, master_service
from ..services.permission_service import get_current_user, require_perm

router = APIRouter(prefix="/api/master", tags=["master"])


def _run(fn, *args, **kwargs):
    """服务层 ValueError → HTTP 422（与 system.py 一致）。"""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _label_of(obj) -> str | None:
    return getattr(obj, "code", None) or getattr(obj, "name", None)


def _register_resource(path: str, *, view_perm: str, edit_perm: str, label: str,
                       obj_type: str, create_fn, get_fn, update_fn, status_fn,
                       delete_fn, fmt_fn) -> None:
    """注册资源的"新增 / 详情 / 修改 / 启停用 / 删除"端点（列表端点各资源签名不同，单独定义）。"""

    @router.post(path, summary=f"新增{label}")
    def _create(request: Request, payload: dict = Body(...),
                user: User = Depends(require_perm(edit_perm)),
                db: Session = Depends(get_db)):
        obj = _run(create_fn, db, payload, user)
        audit_service.log(db, user, module="master", action="create", object_type=obj_type,
                          object_id=obj.id, object_no=_label_of(obj),
                          detail=f"新建{label}：{getattr(obj, 'name', '')}", request=request)
        db.commit()
        return fmt_fn(db, obj)

    @router.get(path + "/{item_id}", summary=f"{label}详情")
    def _get(item_id: int, _user: User = Depends(require_perm(view_perm)),
             db: Session = Depends(get_db)):
        return fmt_fn(db, _run(get_fn, db, item_id))

    @router.put(path + "/{item_id}", summary=f"修改{label}")
    def _update(item_id: int, request: Request, payload: dict = Body(...),
                user: User = Depends(require_perm(edit_perm)),
                db: Session = Depends(get_db)):
        obj = _run(get_fn, db, item_id)
        _run(update_fn, db, obj, payload)
        audit_service.log(db, user, module="master", action="edit", object_type=obj_type,
                          object_id=obj.id, object_no=_label_of(obj),
                          detail=f"修改{label}：{getattr(obj, 'name', '')}", request=request)
        db.commit()
        return fmt_fn(db, obj)

    @router.put(path + "/{item_id}/status", summary=f"{label}启用/停用")
    def _status(item_id: int, request: Request, payload: dict = Body(...),
                user: User = Depends(require_perm(edit_perm)),
                db: Session = Depends(get_db)):
        obj = _run(get_fn, db, item_id)
        enabled = bool(payload.get("enabled", True))
        _run(status_fn, db, obj, enabled)
        audit_service.log(db, user, module="master",
                          action="enable" if enabled else "disable",
                          object_type=obj_type, object_id=obj.id, object_no=_label_of(obj),
                          detail=f"{'启用' if enabled else '停用'}{label}：{getattr(obj, 'name', '')}",
                          request=request)
        db.commit()
        return fmt_fn(db, obj)

    @router.delete(path + "/{item_id}", summary=f"删除{label}")
    def _delete(item_id: int, request: Request,
                user: User = Depends(require_perm(edit_perm)),
                db: Session = Depends(get_db)):
        obj = _run(get_fn, db, item_id)
        label_value, code_value = getattr(obj, "name", None), _label_of(obj)
        _run(delete_fn, db, obj)
        audit_service.log(db, user, module="master", action="delete", object_type=obj_type,
                          object_id=item_id, object_no=code_value,
                          detail=f"删除{label}：{label_value}", request=request)
        db.commit()
        return {"ok": True}


# ==================== 元数据与下拉 ====================

@router.get("/meta", summary="主数据枚举")
def master_meta(_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return master_service.meta(db)


@router.get("/options/{kind}", summary="主数据轻量下拉（登录即可）")
def master_options(kind: str, keyword: str | None = Query(None),
                   product_type_id: int | None = Query(None),
                   _user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    return _run(master_service.options, db, kind, keyword, product_type_id)


# ==================== 客户 ====================

@router.get("/customers", summary="客户列表")
def list_customers(keyword: str | None = Query(None, description="名称/编码/简称/联系人模糊"),
                   status: str | None = Query(None, description="enabled / disabled"),
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
                   _user: User = Depends(require_perm("master.customer.view")),
                   db: Session = Depends(get_db)):
    return master_service.list_parties(db, "customer", keyword=keyword, status=status,
                                       page=page, page_size=page_size)


_register_resource(
    "/customers", view_perm="master.customer.view", edit_perm="master.customer.edit",
    label="客户", obj_type="customer",
    create_fn=lambda db, payload, user: master_service.create_party(db, "customer", payload, user),
    get_fn=lambda db, item_id: master_service.get_party(db, "customer", item_id),
    update_fn=lambda db, obj, payload: master_service.update_party(db, "customer", obj, payload),
    status_fn=lambda db, obj, enabled: master_service.set_party_status(db, "customer", obj, enabled),
    delete_fn=lambda db, obj: master_service.delete_party(db, "customer", obj),
    fmt_fn=lambda db, obj: master_service.fmt_party("customer", obj),
)


# ==================== 供应商 ====================

@router.get("/suppliers", summary="供应商列表")
def list_suppliers(keyword: str | None = Query(None),
                   status: str | None = Query(None),
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
                   _user: User = Depends(require_perm("master.supplier.view")),
                   db: Session = Depends(get_db)):
    return master_service.list_parties(db, "supplier", keyword=keyword, status=status,
                                       page=page, page_size=page_size)


_register_resource(
    "/suppliers", view_perm="master.supplier.view", edit_perm="master.supplier.edit",
    label="供应商", obj_type="supplier",
    create_fn=lambda db, payload, user: master_service.create_party(db, "supplier", payload, user),
    get_fn=lambda db, item_id: master_service.get_party(db, "supplier", item_id),
    update_fn=lambda db, obj, payload: master_service.update_party(db, "supplier", obj, payload),
    status_fn=lambda db, obj, enabled: master_service.set_party_status(db, "supplier", obj, enabled),
    delete_fn=lambda db, obj: master_service.delete_party(db, "supplier", obj),
    fmt_fn=lambda db, obj: master_service.fmt_party("supplier", obj),
)


# ==================== 商品类型（树） ====================

@router.get("/product-types", summary="商品类型树")
def list_product_types(keyword: str | None = Query(None),
                       include_disabled: bool = Query(True),
                       _user: User = Depends(require_perm("master.ptype.view")),
                       db: Session = Depends(get_db)):
    return master_service.list_product_types(db, keyword=keyword, include_disabled=include_disabled)


_register_resource(
    "/product-types", view_perm="master.ptype.view", edit_perm="master.ptype.edit",
    label="商品类型", obj_type="product_type",
    create_fn=lambda db, payload, user: master_service.create_product_type(db, payload),
    get_fn=lambda db, item_id: master_service.get_product_type(db, item_id),
    update_fn=lambda db, obj, payload: master_service.update_product_type(db, obj, payload),
    status_fn=lambda db, obj, enabled: master_service.set_product_type_enabled(db, obj, enabled),
    delete_fn=lambda db, obj: master_service.delete_product_type(db, obj),
    fmt_fn=lambda db, obj: master_service.fmt_product_type(db, obj),
)


# ==================== 计量单位 ====================

@router.get("/uoms", summary="计量单位列表")
def list_uoms(keyword: str | None = Query(None),
              include_disabled: bool = Query(True),
              _user: User = Depends(require_perm("master.uom.view")),
              db: Session = Depends(get_db)):
    return master_service.list_uoms(db, keyword=keyword, include_disabled=include_disabled)


_register_resource(
    "/uoms", view_perm="master.uom.view", edit_perm="master.uom.edit",
    label="计量单位", obj_type="uom",
    create_fn=lambda db, payload, user: master_service.create_uom(db, payload),
    get_fn=lambda db, item_id: master_service.get_uom(db, item_id),
    update_fn=lambda db, obj, payload: master_service.update_uom(db, obj, payload),
    status_fn=lambda db, obj, enabled: master_service.set_uom_enabled(db, obj, enabled),
    delete_fn=lambda db, obj: master_service.delete_uom(db, obj),
    fmt_fn=lambda db, obj: master_service.fmt_uom(obj),
)


# ==================== 仓库 ====================

@router.get("/warehouses", summary="仓库列表")
def list_warehouses(keyword: str | None = Query(None),
                    include_disabled: bool = Query(True),
                    _user: User = Depends(require_perm("master.wh.view")),
                    db: Session = Depends(get_db)):
    return master_service.list_warehouses(db, keyword=keyword, include_disabled=include_disabled)


_register_resource(
    "/warehouses", view_perm="master.wh.view", edit_perm="master.wh.edit",
    label="仓库", obj_type="warehouse",
    create_fn=lambda db, payload, user: master_service.create_warehouse(db, payload),
    get_fn=lambda db, item_id: master_service.get_warehouse(db, item_id),
    update_fn=lambda db, obj, payload: master_service.update_warehouse(db, obj, payload),
    status_fn=lambda db, obj, enabled: master_service.set_warehouse_enabled(db, obj, enabled),
    delete_fn=lambda db, obj: master_service.delete_warehouse(db, obj),
    fmt_fn=lambda db, obj: master_service.fmt_warehouse(db, obj),
)


# ==================== 物料 ====================

@router.get("/products", summary="物料列表")
def list_products(keyword: str | None = Query(None, description="名称/编码/规格/品牌/条码模糊"),
                  product_type_id: int | None = Query(None, description="按类型（含下级）过滤"),
                  status: str | None = Query(None),
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
                  _user: User = Depends(require_perm("master.product.view")),
                  db: Session = Depends(get_db)):
    return _run(master_service.list_products, db, keyword=keyword,
                product_type_id=product_type_id, status=status, page=page, page_size=page_size)


_register_resource(
    "/products", view_perm="master.product.view", edit_perm="master.product.edit",
    label="物料", obj_type="product",
    create_fn=lambda db, payload, user: master_service.create_product(db, payload, user),
    get_fn=lambda db, item_id: master_service.get_product(db, item_id),
    update_fn=lambda db, obj, payload: master_service.update_product(db, obj, payload),
    status_fn=lambda db, obj, enabled: master_service.set_product_status(db, obj, enabled),
    delete_fn=lambda db, obj: master_service.delete_product(db, obj),
    fmt_fn=lambda db, obj: master_service.fmt_product(db, obj),
)
