"""账号服务（T-V2-05）：账号 CRUD、角色分配、重置密码、停用启用。

规则（PRD §3.2、BR-V2-09/10/11）：
- 登录名唯一且创建后**不可修改**（审计线索）；
- 新账号与重置密码后 `must_change_pwd=True` → 首次登录强制改密（AC-V2-08）；
- 密码强度取自系统参数 `pwd_min_length`（默认 8，需含字母与数字）；
- **不可停用自己**，**不可停用最后一个超级管理员**（防把系统锁死）；
- 账号不做物理删除（保留历史归属与审计），需要"移除"即停用。
"""
from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..dicts import get_sys_params
from ..models_auth import Role, User
from ..security import check_password_strength, hash_password


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise ValueError("账号不存在")
    return user


def _fmt_dt(value) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None


def fmt_user(db: Session, user: User) -> dict:
    roles = list(user.roles or [])
    return {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "org_id": user.org_id,
        "org_name": user.org.name if user.org else None,
        "phone": user.phone,
        "email": user.email,
        "status": user.status,
        "is_superadmin": user.is_superadmin,
        "must_change_pwd": user.must_change_pwd,
        "last_login_at": _fmt_dt(user.last_login_at),
        "remark": user.remark,
        "roles": [{"id": r.id, "code": r.code, "name": r.name} for r in roles],
        "role_names": [r.name for r in roles],
    }


def list_users(db: Session, *, keyword: str | None = None, org_id: int | None = None,
               role_id: int | None = None, status: str | None = None,
               page: int = 1, page_size: int = 20) -> dict:
    query = db.query(User)
    if keyword:
        kw = f"%{(keyword or '').strip()}%"
        query = query.filter(or_(User.username.like(kw), User.real_name.like(kw)))
    if org_id:
        query = query.filter(User.org_id == org_id)
    if status:
        query = query.filter(User.status == status)
    if role_id:
        query = query.filter(User.roles.any(Role.id == role_id))

    total = query.count()
    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 20)))
    rows = query.order_by(User.id.asc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [fmt_user(db, u) for u in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _norm_roles(db: Session, role_ids) -> list[Role]:
    ids: list[int] = []
    for raw in (role_ids or []):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []
    roles = db.query(Role).filter(Role.id.in_(set(ids))).all()
    if len(roles) != len(set(ids)):
        raise ValueError("存在无效的角色")
    return roles


def _min_pwd_len(db: Session) -> int:
    return int(get_sys_params(db).get("pwd_min_length") or 8)


def _check_password(db: Session, password: str) -> None:
    err = check_password_strength(password, _min_pwd_len(db))
    if err:
        raise ValueError(err)


def _enabled_superadmin_count(db: Session, exclude_id: int | None = None) -> int:
    query = db.query(func.count(User.id)).filter(
        User.is_superadmin == True,  # noqa: E712
        User.status == "enabled",
    )
    if exclude_id:
        query = query.filter(User.id != exclude_id)
    return int(query.scalar() or 0)


def _apply_status(db: Session, user: User, status: str, operator: User) -> None:
    if status not in ("enabled", "disabled"):
        raise ValueError("账号状态只能是 enabled / disabled")
    if status == "disabled":
        if operator is not None and user.id == operator.id:
            raise ValueError("不能停用当前登录账号")
        if user.is_superadmin and _enabled_superadmin_count(db, exclude_id=user.id) == 0:
            raise ValueError("不能停用最后一个超级管理员")
    user.status = status


def create_user(db: Session, payload: dict, operator: User) -> User:
    username = str(payload.get("username") or "").strip()
    real_name = str(payload.get("real_name") or "").strip()
    if not username or not real_name:
        raise ValueError("登录名与真实姓名必填")
    if len(username) > 64 or len(real_name) > 64:
        raise ValueError("登录名与真实姓名最多 64 字")
    if db.query(User).filter(User.username == username).first() is not None:
        raise ValueError("登录名已存在")

    password = str(payload.get("password") or "")
    if not password:
        raise ValueError("初始密码必填")
    _check_password(db, password)

    user = User(
        username=username,
        real_name=real_name,
        password_hash=hash_password(password),
        org_id=(payload.get("org_id") or None),
        phone=(str(payload.get("phone") or "").strip() or None),
        email=(str(payload.get("email") or "").strip() or None),
        status="enabled",
        is_superadmin=False,
        must_change_pwd=True,          # 新账号首次登录强制改密
        remark=(str(payload.get("remark") or "").strip() or None),
        created_by=(operator.id if operator else None),
    )
    user.roles = _norm_roles(db, payload.get("role_ids"))
    db.add(user)
    db.commit()
    return user


def update_user(db: Session, user: User, payload: dict, operator: User) -> User:
    if "real_name" in payload:
        name = str(payload.get("real_name") or "").strip()
        if not name:
            raise ValueError("真实姓名不能为空")
        user.real_name = name
    if "org_id" in payload:
        user.org_id = payload.get("org_id") or None
    if "phone" in payload:
        user.phone = str(payload.get("phone") or "").strip() or None
    if "email" in payload:
        user.email = str(payload.get("email") or "").strip() or None
    if "remark" in payload:
        user.remark = str(payload.get("remark") or "").strip() or None
    if "role_ids" in payload:
        user.roles = _norm_roles(db, payload.get("role_ids"))
    if "status" in payload:
        _apply_status(db, user, str(payload["status"]), operator)
    db.commit()
    return user


def set_enabled(db: Session, user: User, enabled: bool, operator: User) -> User:
    _apply_status(db, user, "enabled" if enabled else "disabled", operator)
    db.commit()
    return user


def reset_password(db: Session, user: User, new_password: str) -> User:
    """管理员重置密码：重置后该账号下次登录强制改密。"""
    _check_password(db, new_password)
    user.password_hash = hash_password(new_password)
    user.must_change_pwd = True
    db.commit()
    return user
