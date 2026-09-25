"""系统管理与资料库 API（V2.0）。

已实现：
- T-V2-03 组织架构（org-units）
后续（同一 router 内按 T-V2-04/05/12 扩展）：
- 角色管理、账号管理、系统参数、编号规则、操作日志、变更历史、数据备份、关于

接口清单见 `12-erp-system-design.md` §6.1；权限点见 `app/permissions.py`。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models_auth import User
from ..services import audit_service, org_service
from ..services.permission_service import require_perm

router = APIRouter(prefix="/api/system", tags=["system"])


def _run(fn, *args, **kwargs):
    """把服务的 ValueError 转成 422（与既有 settings.py 的处理方式一致）。"""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ==================== 组织架构（T-V2-03） ====================

@router.get("/org-units")
def list_org_units(keyword: str | None = Query(None, description="按名称/编码模糊过滤"),
                   include_disabled: bool = Query(True),
                   _user: User = Depends(require_perm("master.org.view")),
                   db: Session = Depends(get_db)):
    """组织树：同时返回扁平 items 与嵌套 tree（tree 供前端左侧导航渲染）。"""
    data = org_service.list_units(db, keyword=keyword, include_disabled=include_disabled)
    data["unit_types"] = org_service.UNIT_TYPES
    data["max_level"] = org_service.MAX_LEVEL
    return data


@router.post("/org-units")
def create_org_unit(request: Request, payload: dict = Body(...),
                    user: User = Depends(require_perm("master.org.edit")),
                    db: Session = Depends(get_db)):
    node = _run(org_service.create_unit, db, payload)
    audit_service.log(db, user, module="master", action="create",
                      object_type="org_unit", object_id=node.id, object_no=node.name,
                      detail=f"新建组织节点：{node.name}（{node.path}）", request=request)
    db.commit()
    return org_service.fmt_unit(db, node)


@router.get("/org-units/{unit_id}")
def get_org_unit(unit_id: int,
                 _user: User = Depends(require_perm("master.org.view")),
                 db: Session = Depends(get_db)):
    node = _run(org_service.get_unit, db, unit_id)
    return org_service.fmt_unit(db, node)


@router.put("/org-units/{unit_id}")
def update_org_unit(unit_id: int, request: Request, payload: dict = Body(...),
                    user: User = Depends(require_perm("master.org.edit")),
                    db: Session = Depends(get_db)):
    node = _run(org_service.get_unit, db, unit_id)
    _run(org_service.update_unit, db, node, payload)
    audit_service.log(db, user, module="master", action="edit",
                      object_type="org_unit", object_id=node.id, object_no=node.name,
                      detail=f"修改组织节点：{node.name}", request=request)
    db.commit()
    return org_service.fmt_unit(db, node)


@router.put("/org-units/{unit_id}/status")
def set_org_unit_status(unit_id: int, request: Request, payload: dict = Body(...),
                        user: User = Depends(require_perm("master.org.edit")),
                        db: Session = Depends(get_db)):
    """启用/停用节点：停用不影响其下历史数据与历史单据的展示。"""
    node = _run(org_service.get_unit, db, unit_id)
    enabled = bool(payload.get("enabled", True))
    _run(org_service.set_enabled, db, node, enabled)
    audit_service.log(db, user, module="master", action="enable" if enabled else "disable",
                      object_type="org_unit", object_id=node.id, object_no=node.name,
                      request=request)
    db.commit()
    return org_service.fmt_unit(db, node)


@router.delete("/org-units/{unit_id}")
def delete_org_unit(unit_id: int, request: Request,
                    user: User = Depends(require_perm("master.org.edit")),
                    db: Session = Depends(get_db)):
    """删除节点：存在子节点或归属账号时拒绝（BR-V2-10），提示改为停用。"""
    node = _run(org_service.get_unit, db, unit_id)
    name = node.name
    _run(org_service.delete_unit, db, node)
    audit_service.log(db, user, module="master", action="delete",
                      object_type="org_unit", object_id=unit_id, object_no=name,
                      request=request)
    db.commit()
    return {"ok": True}
