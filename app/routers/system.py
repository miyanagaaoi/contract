"""系统管理与资料库 API（V2.0）。

已实现：
- T-V2-03 组织架构（org-units）
- T-V2-04 角色管理（roles + permissions 元数据）
- T-V2-05 账号管理（users + 重置密码 + 停启用）
- T-V2-12 系统管理整合（系统参数 / 编号规则 / 操作日志 / 变更历史 / 备份 / 关于）

接口清单见 `12-erp-system-design.md` §6.1；权限点见 `app/permissions.py`。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import APP_NAME, APP_VERSION, AUTH_ENABLED, DB_FILE, DB_URL, is_sqlite
from ..database import get_db
from ..dicts import (
    NUMBER_RULE_LABELS,
    SYS_PARAM_META,
    get_number_rules,
    get_sys_params,
    set_number_rules,
    set_sys_params,
)
from ..models import Attachment, ChangeLog, Contract, Tag
from ..models_auth import OperationLog, User
from ..models_master import Customer, Product, Supplier
from ..permissions import DATA_SCOPES, PERM_CODES, perm_tree
from ..services import audit_service, backup_service, numbering_service, org_service, role_service, user_service
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


# ==================== 系统参数（T-V2-12 / AC-V2-38） ====================

@router.get("/params")
def get_params(_user: User = Depends(require_perm("system.param.view")),
               db: Session = Depends(get_db)):
    """系统参数当前值 + 元数据（中文名/类型/取值范围）。"""
    return {"params": get_sys_params(db), "meta": SYS_PARAM_META}


@router.put("/params")
def update_params(request: Request, payload: dict = Body(...),
                  user: User = Depends(require_perm("system.param.edit")),
                  db: Session = Depends(get_db)):
    """只接受已知参数键（未知键忽略、非法值 422），改完即生效。"""
    values = payload.get("params") if isinstance(payload.get("params"), dict) else payload
    updated = _run(set_sys_params, db, values)
    audit_service.log(db, user, module="system", action="edit", object_type="sys_params",
                      detail=f"修改系统参数：{', '.join(sorted((values or {}).keys()))}",
                      request=request)
    db.commit()
    return {"params": updated, "meta": SYS_PARAM_META}


# ==================== 编号规则（T-V2-12） ====================

@router.get("/number-rules")
def get_rules(_user: User = Depends(require_perm("system.number.view")),
              db: Session = Depends(get_db)):
    """编号规则 + 下一个可用编号预览（未实现编号的类别跳过预览）。"""
    rules = get_number_rules(db)
    previews: dict[str, str | None] = {}
    for kind in rules:
        try:
            previews[kind] = numbering_service.next_doc_no(db, kind)
        except ValueError:
            previews[kind] = None      # 该类单据尚未实现（M2 起自动出现）
    return {
        "rules": rules,
        "labels": NUMBER_RULE_LABELS,
        "previews": previews,
        "reset_labels": {"month": "按月重置", "never": "不重置"},
    }


@router.put("/number-rules")
def update_rules(request: Request, payload: dict = Body(...),
                 user: User = Depends(require_perm("system.param.edit")),
                 db: Session = Depends(get_db)):
    """调整前缀与序号长度（reset 策略固定：单据按月、主数据不重置）。"""
    values = payload.get("rules") if isinstance(payload.get("rules"), dict) else payload
    rules = _run(set_number_rules, db, values)
    audit_service.log(db, user, module="system", action="edit", object_type="number_rules",
                      detail=f"修改编号规则：{', '.join(sorted((values or {}).keys()))}",
                      request=request)
    db.commit()
    return {"rules": rules, "labels": NUMBER_RULE_LABELS}


# ==================== 操作日志（T-V2-12 / AC-V2-36） ====================

def _parse_day(value: str | None, *, end: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        day = datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD")
    return day.replace(hour=23, minute=59, second=59) if end else day


@router.get("/logs")
def list_logs(keyword: str | None = Query(None, description="对象单号/操作人/详情模糊"),
              module: str | None = Query(None),
              action: str | None = Query(None),
              user_id: int | None = Query(None),
              result: str | None = Query(None, description="success / fail"),
              date_from: str | None = Query(None), date_to: str | None = Query(None),
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
              _user: User = Depends(require_perm("system.log.view")),
              db: Session = Depends(get_db)):
    """操作日志：支持"动作 + 时间范围"筛选（AC-V2-36）。"""
    query = db.query(OperationLog)
    if module:
        query = query.filter(OperationLog.module == module)
    if action:
        query = query.filter(OperationLog.action == action)
    if user_id:
        query = query.filter(OperationLog.user_id == user_id)
    if result:
        query = query.filter(OperationLog.result == result)
    start, end = _parse_day(date_from), _parse_day(date_to, end=True)
    if start is not None:
        query = query.filter(OperationLog.created_at >= start)
    if end is not None:
        query = query.filter(OperationLog.created_at <= end)
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(or_(OperationLog.object_no.like(like),
                                 OperationLog.username.like(like),
                                 OperationLog.real_name.like(like),
                                 OperationLog.detail.like(like)))

    total = int(query.count() or 0)
    rows = (query.order_by(OperationLog.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    modules = [r[0] for r in db.query(OperationLog.module).distinct().all() if r[0]]
    actions = [r[0] for r in db.query(OperationLog.action).distinct().all() if r[0]]
    return {
        "items": [{
            "id": r.id, "username": r.username, "real_name": r.real_name,
            "module": r.module, "action": r.action, "object_type": r.object_type,
            "object_id": r.object_id, "object_no": r.object_no, "result": r.result,
            "detail": r.detail, "ip": r.ip,
            "created_at": r.created_at.isoformat(sep=" ", timespec="seconds") if r.created_at else None,
        } for r in rows],
        "total": total, "page": page, "page_size": page_size,
        "modules": sorted(modules), "actions": sorted(actions),
    }


# ==================== 变更历史（T-V2-12 / AC-V2-37） ====================

@router.get("/changelogs")
def list_changelogs(keyword: str | None = Query(None, description="合同编号/名称/字段/操作人模糊"),
                    field_name: str | None = Query(None),
                    source: str | None = Query(None, description="manual / auto"),
                    contract_id: int | None = Query(None),
                    date_from: str | None = Query(None), date_to: str | None = Query(None),
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
                    _user: User = Depends(require_perm("system.changelog.view")),
                    db: Session = Depends(get_db)):
    """全局变更历史（带操作人；V1.0 历史记录操作人为空，前端显示"—"）。"""
    query = db.query(ChangeLog, Contract).outerjoin(Contract, ChangeLog.contract_id == Contract.id)
    if contract_id:
        query = query.filter(ChangeLog.contract_id == contract_id)
    if field_name:
        query = query.filter(ChangeLog.field_name == field_name)
    if source:
        query = query.filter(ChangeLog.source == source)
    start, end = _parse_day(date_from), _parse_day(date_to, end=True)
    if start is not None:
        query = query.filter(ChangeLog.created_at >= start)
    if end is not None:
        query = query.filter(ChangeLog.created_at <= end)
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(or_(Contract.contract_no.like(like), Contract.name.like(like),
                                 ChangeLog.field_name.like(like), ChangeLog.note.like(like),
                                 ChangeLog.operator_name.like(like),
                                 ChangeLog.new_value.like(like)))

    total = int(query.count() or 0)
    rows = (query.order_by(ChangeLog.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    fields = [r[0] for r in db.query(ChangeLog.field_name).distinct().all() if r[0]]
    return {
        "items": [{
            "id": log.id,
            "contract_id": log.contract_id,
            "contract_no": contract.contract_no if contract else None,
            "contract_name": contract.name if contract else None,
            "field_name": log.field_name,
            "old_value": log.old_value,
            "new_value": log.new_value,
            "note": log.note,
            "source": log.source,
            "operator_name": log.operator_name,
            "created_at": log.created_at.isoformat(sep=" ", timespec="seconds") if log.created_at else None,
        } for log, contract in rows],
        "total": total, "page": page, "page_size": page_size,
        "fields": sorted(fields),
    }


# ==================== 备份（T-V2-12 / AC-V2-39） ====================

@router.get("/backup")
def list_backups(_user: User = Depends(require_perm("system.backup.download"))):
    return {"items": backup_service.list_backups()}


@router.post("/backup")
def create_backup(request: Request,
                  user: User = Depends(require_perm("system.backup.create")),
                  db: Session = Depends(get_db)):
    """生成备份（SQLite 在线一致性快照 + 附件目录打包），并写操作日志。"""
    info = _run(backup_service.create_backup)
    audit_service.log(db, user, module="system", action="backup", object_type="backup",
                      object_no=info["name"],
                      detail=f"生成备份 {info['name']}（{info['size_bytes']} 字节）",
                      request=request)
    db.commit()
    return info


@router.get("/backup/{name}")
def download_backup(name: str,
                    _user: User = Depends(require_perm("system.backup.download"))):
    path = _run(backup_service.resolve_backup, name)
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.delete("/backup/{name}")
def delete_backup(name: str, request: Request,
                  user: User = Depends(require_perm("system.backup.create")),
                  db: Session = Depends(get_db)):
    _run(backup_service.delete_backup, name)
    audit_service.log(db, user, module="system", action="delete", object_type="backup",
                      object_no=name, detail=f"删除备份 {name}", request=request)
    db.commit()
    return {"ok": True}


# ==================== 关于（T-V2-12） ====================

@router.get("/about")
def about(_user: User = Depends(require_perm("system.about.view")),
          db: Session = Depends(get_db)):
    """应用与数据概览（排障用：版本、库位置、数据量、权限点数量）。"""
    counts = {
        "contracts": int(db.query(func.count(Contract.id)).scalar() or 0),
        "contracts_deleted": int(db.query(func.count(Contract.id))
                                 .filter(Contract.deleted == True).scalar() or 0),  # noqa: E712
        "tags": int(db.query(func.count(Tag.id)).scalar() or 0),
        "attachments": int(db.query(func.count(Attachment.id)).scalar() or 0),
        "change_logs": int(db.query(func.count(ChangeLog.id)).scalar() or 0),
        "operation_logs": int(db.query(func.count(OperationLog.id)).scalar() or 0),
        "users": int(db.query(func.count(User.id)).scalar() or 0),
        "customers": int(db.query(func.count(Customer.id)).scalar() or 0),
        "suppliers": int(db.query(func.count(Supplier.id)).scalar() or 0),
        "products": int(db.query(func.count(Product.id)).scalar() or 0),
    }
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "server_time": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "auth_enabled": AUTH_ENABLED,
        "database": {
            "kind": "sqlite" if is_sqlite() else "other",
            "file": str(DB_FILE) if is_sqlite() else DB_URL.split("@")[-1],
        },
        "counts": counts,
        "permission_count": len(PERM_CODES),
        "backups": backup_service.list_backups()[:5],
    }
