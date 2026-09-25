"""角色服务（T-V2-04）：角色 CRUD、权限点分配与数据范围。

规则（PRD §3.3、BR-V2-08/09/10）：
- 权限点只能取自 `permissions.PERM_CODES`，未知权限点被忽略（不报错，防前端旧缓存）；
- **内置角色不可删除**；系统管理员角色的 `system.*` 权限不可被摘除（防自锁）；
- 角色下仍有账号时不可删除，只能停用；
- 一个账号可绑定多个角色：权限取并集、数据范围取最宽（在 permission_service 中计算）。
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models_auth import Role, RolePermission, user_roles
from ..permissions import DATA_SCOPES, DATA_SCOPE_CODES, PERM_CODES


def get_role(db: Session, role_id: int) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise ValueError("角色不存在")
    return role


def _user_count(db: Session, role_id: int) -> int:
    return int(
        db.query(func.count(user_roles.c.user_id))
        .filter(user_roles.c.role_id == role_id)
        .scalar() or 0
    )


def fmt_role(db: Session, role: Role) -> dict:
    codes = sorted(role.perm_codes)
    return {
        "id": role.id,
        "code": role.code,
        "name": role.name,
        "data_scope": role.data_scope,
        "remark": role.remark,
        "builtin": role.builtin,
        "enabled": role.enabled,
        "perms": codes,
        "perm_count": len(codes),
        "user_count": _user_count(db, role.id),
    }


def list_roles(db: Session, keyword: str | None = None,
               include_disabled: bool = True) -> dict:
    query = db.query(Role)
    if not include_disabled:
        query = query.filter(Role.enabled == True)  # noqa: E712
    roles = query.order_by(Role.builtin.desc(), Role.id.asc()).all()
    items = [fmt_role(db, r) for r in roles]
    if keyword:
        kw = keyword.strip()
        if kw:
            items = [i for i in items if kw in i["name"] or kw in i["code"]]
    return {
        "items": items,
        "total": len(items),
        "data_scopes": [{"code": c, "label": label} for c, label in DATA_SCOPES],
        "perm_total": len(PERM_CODES),
    }


def _norm_scope(value) -> str:
    scope = str(value or "SELF").strip().upper()
    if scope not in DATA_SCOPE_CODES:
        raise ValueError(f"数据范围只能是：{' / '.join(DATA_SCOPE_CODES)}")
    return scope


def _norm_code(value) -> str:
    """角色编码：字母开头，仅含字母/数字/下划线，最长 32 字。

    注意：`str.isalnum()` 对中文同样返回 True，必须配合 `isascii()` 才安全。
    """
    code = str(value or "").strip().lower()
    if not code:
        raise ValueError("角色编码必填")
    if len(code) > 32:
        raise ValueError("角色编码最多 32 字")
    body = code.replace("_", "")
    if not body or not body.isascii() or not body.isalnum() or not code[0].isalpha():
        raise ValueError("角色编码需以字母开头，只能包含字母、数字与下划线")
    return code


def _norm_name(value) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("角色名称必填")
    if len(name) > 64:
        raise ValueError("角色名称最多 64 字")
    return name


def _set_perms(db: Session, role: Role, codes) -> None:
    """整表替换角色权限点（set 语义）。"""
    wanted = {str(c) for c in (codes or [])} & PERM_CODES
    if role.code == "sysadmin":
        # 防自锁：系统管理员必须保留系统管理权限
        wanted |= {c for c in PERM_CODES if c.startswith("system.")}
    db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
    for code in sorted(wanted):
        db.add(RolePermission(role_id=role.id, perm_code=code))
    db.flush()
    db.expire(role, ["permissions"])   # 让后续 perm_codes 重新加载


def create_role(db: Session, payload: dict) -> Role:
    code = _norm_code(payload.get("code"))
    name = _norm_name(payload.get("name"))
    if db.query(Role).filter(Role.code == code).first() is not None:
        raise ValueError("角色编码已存在")

    role = Role(
        code=code,
        name=name,
        data_scope=_norm_scope(payload.get("data_scope")),
        remark=(str(payload.get("remark") or "").strip() or None),
        builtin=False,
        enabled=bool(payload.get("enabled", True)),
    )
    db.add(role)
    db.flush()
    _set_perms(db, role, payload.get("perms") or [])
    db.commit()
    return role


def update_role(db: Session, role: Role, payload: dict) -> Role:
    if "name" in payload:
        role.name = _norm_name(payload["name"])
    if "remark" in payload:
        role.remark = str(payload.get("remark") or "").strip() or None
    if "data_scope" in payload:
        role.data_scope = _norm_scope(payload["data_scope"])
    if "enabled" in payload:
        if role.code == "sysadmin" and not payload["enabled"]:
            raise ValueError("系统管理员角色不可停用")
        role.enabled = bool(payload["enabled"])
    if payload.get("perms") is not None:
        _set_perms(db, role, payload["perms"])
    db.commit()
    return role


def set_permissions(db: Session, role: Role, codes) -> Role:
    if role.code == "sysadmin" and not codes:
        raise ValueError("系统管理员角色的权限不可全部清空")
    _set_perms(db, role, codes)
    db.commit()
    return role


def set_enabled(db: Session, role: Role, enabled: bool) -> Role:
    if role.code == "sysadmin" and not enabled:
        raise ValueError("系统管理员角色不可停用")
    role.enabled = bool(enabled)
    db.commit()
    return role


def delete_role(db: Session, role: Role) -> None:
    if role.builtin:
        raise ValueError("内置角色不可删除；如需停用请使用「停用」，或调整其权限")
    if _user_count(db, role.id) > 0:
        raise ValueError("该角色下仍有账号，请先解除绑定，或改为停用")
    db.delete(role)
    db.commit()
