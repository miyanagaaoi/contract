"""系统管理与资料库 API（V2.0）。

已实现：
- T-V2-03 组织架构（org-units）
- T-V2-04 角色管理（roles + permissions 元数据）
- T-V2-05 账号管理（users + 重置密码 + 停启用）

后续（同一 router 扩展）：系统参数、编号规则、操作日志、变更历史、数据备份、关于。

接口清单见 `12-erp-system-design.md` §6.1；权限点见 `app/permissions.py`。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models_auth import User
from ..permissions import DATA_SCOPES, perm_tree
from ..services import audit_service, org_service, role_service, user_service
from ..services.permission_service import require_perm

router = APIRouter(prefix="/api/system", tags=["system"])


def _run(fn, *args, **kwargs):
    """把服务层的 ValueError 转成 422（与既有 settings.py 的处理方式一致）。"""
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
    """组织树：同时返回扁平 items 与嵌套 tree（tree 供前端左侧树渲染）。"""
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


# ==================== 角色管理（T-V2-04） ====================

@router.get("/permissions")
def list_permissions(_user: User = Depends(require_perm("master.role.view"))):
    """权限点元数据：按模块分组的权限树 + 数据范围枚举（角色配置界面用）。"""
    return {
        "tree": perm_tree(),
        "data_scopes": [{"code": c, "label": label} for c, label in DATA_SCOPES],
    }


@router.get("/roles")
def list_roles(keyword: str | None = Query(None),
               include_disabled: bool = Query(True),
               _user: User = Depends(require_perm("master.role.view")),
               db: Session = Depends(get_db)):
    return role_service.list_roles(db, keyword=keyword, include_disabled=include_disabled)


@router.post("/roles")
def create_role(request: Request, payload: dict = Body(...),
                user: User = Depends(require_perm("master.role.edit")),
                db: Session = Depends(get_db)):
    role = _run(role_service.create_role, db, payload)
    audit_service.log(db, user, module="master", action="create",
                      object_type="role", object_id=role.id, object_no=role.code,
                      detail=f"新建角色：{role.name}", request=request)
    db.commit()
    return role_service.fmt_role(db, role)


@router.get("/roles/{role_id}")
def get_role(role_id: int,
             _user: User = Depends(require_perm("master.role.view")),
             db: Session = Depends(get_db)):
    role = _run(role_service.get_role, db, role_id)
    return role_service.fmt_role(db, role)


@router.put("/roles/{role_id}")
def update_role(role_id: int, request: Request, payload: dict = Body(...),
                user: User = Depends(require_perm("master.role.edit")),
                db: Session = Depends(get_db)):
    role = _run(role_service.get_role, db, role_id)
    _run(role_service.update_role, db, role, payload)
    audit_service.log(db, user, module="master", action="edit",
                      object_type="role", object_id=role.id, object_no=role.code,
                      detail=f"修改角色：{role.name}（{len(role.perm_codes)} 个权限点）",
                      request=request)
    db.commit()
    return role_service.fmt_role(db, role)


@router.put("/roles/{role_id}/permissions")
def set_role_permissions(role_id: int, request: Request, payload: dict = Body(...),
                         user: User = Depends(require_perm("master.role.edit")),
                         db: Session = Depends(get_db)):
    """整表替换角色权限点（set 语义）；未知权限点被忽略。"""
    role = _run(role_service.get_role, db, role_id)
    before = len(role.perm_codes)
    _run(role_service.set_permissions, db, role, payload.get("perms") or [])
    audit_service.log(db, user, module="system", action="perm_change",
                      object_type="role", object_id=role.id, object_no=role.code,
                      detail=f"角色「{role.name}」权限点 {before} → {len(role.perm_codes)}",
                      request=request)
    db.commit()
    return role_service.fmt_role(db, role)


@router.put("/roles/{role_id}/status")
def set_role_status(role_id: int, request: Request, payload: dict = Body(...),
                    user: User = Depends(require_perm("master.role.edit")),
                    db: Session = Depends(get_db)):
    role = _run(role_service.get_role, db, role_id)
    enabled = bool(payload.get("enabled", True))
    _run(role_service.set_enabled, db, role, enabled)
    audit_service.log(db, user, module="master", action="enable" if enabled else "disable",
                      object_type="role", object_id=role.id, object_no=role.code,
                      request=request)
    db.commit()
    return role_service.fmt_role(db, role)


@router.delete("/roles/{role_id}")
def delete_role(role_id: int, request: Request,
                user: User = Depends(require_perm("master.role.edit")),
                db: Session = Depends(get_db)):
    role = _run(role_service.get_role, db, role_id)
    code, name = role.code, role.name
    _run(role_service.delete_role, db, role)
    audit_service.log(db, user, module="master", action="delete",
                      object_type="role", object_id=role_id, object_no=code,
                      detail=f"删除角色：{name}", request=request)
    db.commit()
    return {"ok": True}


# ==================== 账号管理（T-V2-05） ====================

@router.get("/users")
def list_users(keyword: str | None = Query(None, description="登录名/姓名模糊"),
               org_id: int | None = Query(None),
               role_id: int | None = Query(None),
               status: str | None = Query(None, description="enabled / disabled"),
               page: int = Query(1, ge=1),
               page_size: int = Query(20, ge=1, le=200),
               _user: User = Depends(require_perm("master.user.view")),
               db: Session = Depends(get_db)):
    return user_service.list_users(db, keyword=keyword, org_id=org_id, role_id=role_id,
                                   status=status, page=page, page_size=page_size)


@router.post("/users")
def create_user(request: Request, payload: dict = Body(...),
                user: User = Depends(require_perm("master.user.edit")),
                db: Session = Depends(get_db)):
    created = _run(user_service.create_user, db, payload, user)
    audit_service.log(db, user, module="master", action="create",
                      object_type="user", object_id=created.id, object_no=created.username,
                      detail=f"新建账号：{created.real_name}", request=request)
    db.commit()
    return user_service.fmt_user(db, created)


@router.get("/users/{user_id}")
def get_user(user_id: int,
             _user: User = Depends(require_perm("master.user.view")),
             db: Session = Depends(get_db)):
    target = _run(user_service.get_user, db, user_id)
    return user_service.fmt_user(db, target)


@router.put("/users/{user_id}")
def update_user(user_id: int, request: Request, payload: dict = Body(...),
                user: User = Depends(require_perm("master.user.edit")),
                db: Session = Depends(get_db)):
    target = _run(user_service.get_user, db, user_id)
    _run(user_service.update_user, db, target, payload, user)
    audit_service.log(db, user, module="master", action="edit",
                      object_type="user", object_id=target.id, object_no=target.username,
                      detail=f"修改账号：{target.real_name}", request=request)
    db.commit()
    return user_service.fmt_user(db, target)


@router.put("/users/{user_id}/status")
def set_user_status(user_id: int, request: Request, payload: dict = Body(...),
                    user: User = Depends(require_perm("master.user.edit")),
                    db: Session = Depends(get_db)):
    """启用/停用账号：停用后既有令牌立即失效（每次请求回查状态）。"""
    target = _run(user_service.get_user, db, user_id)
    enabled = bool(payload.get("enabled", True))
    _run(user_service.set_enabled, db, target, enabled, user)
    audit_service.log(db, user, module="master", action="enable" if enabled else "disable",
                      object_type="user", object_id=target.id, object_no=target.username,
                      request=request)
    db.commit()
    return user_service.fmt_user(db, target)


@router.post("/users/{user_id}/reset-password")
def reset_user_password(user_id: int, request: Request, payload: dict = Body(...),
                        user: User = Depends(require_perm("master.user.resetpwd")),
                        db: Session = Depends(get_db)):
    """管理员重置密码：重置后该账号下次登录强制改密。"""
    target = _run(user_service.get_user, db, user_id)
    new_password = str(payload.get("new_password") or "")
    _run(user_service.reset_password, db, target, new_password)
    audit_service.log(db, user, module="master", action="reset_pwd",
                      object_type="user", object_id=target.id, object_no=target.username,
                      detail="管理员重置密码", request=request)
    db.commit()
    return {"ok": True}
