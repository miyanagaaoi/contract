"""认证 API（T-V2-02）：登录 / 登出 / 当前用户 / 修改密码。

对应验收场景：
- AC-V2-01 登录与鉴权（错误密码 401，成功返回令牌与权限菜单）
- AC-V2-02 未登录拦截（业务接口 401）
- AC-V2-08 首登强制改密（`must_change_pwd`）

设计要点（`12-erp-system-design.md` §3.1）：
- 无状态 JWT；不做 refresh token；登录/登出/改密均写操作日志；
- 失败日志需先 `commit()` 再抛异常，否则随事务回滚丢失。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import AUTH_ENABLED
from ..database import get_db
from ..dicts import get_sys_params
from ..models_auth import User
from ..permissions import menu_tree_for
from ..security import check_password_strength, create_token, hash_password, verify_password
from ..services import audit_service
from ..services.permission_service import collect_perms, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_brief(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "org_id": user.org_id,
        "org_name": user.org.name if user.org else None,
        "is_superadmin": user.is_superadmin,
        "must_change_pwd": user.must_change_pwd,
    }


def roles_brief(user: User) -> list[dict]:
    return [
        {"id": r.id, "code": r.code, "name": r.name, "data_scope": r.data_scope}
        for r in (user.roles or []) if r.enabled
    ]


@router.post("/login")
def login(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    """登录：校验账号密码 → 签发令牌 → 记录登录时间与操作日志。"""
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")

    user = db.query(User).filter(User.username == username).first()
    if user is None or not verify_password(password, user.password_hash):
        audit_service.log(db, None, module="auth", action="login", result="fail",
                          object_no=username, detail="用户名或密码错误", request=request)
        db.commit()
        # 统一提示，不区分"账号不存在/密码错误"，避免账号枚举
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if user.status != "enabled":
        audit_service.log(db, user, module="auth", action="login", result="fail",
                          detail="账号已停用", request=request)
        db.commit()
        raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")

    token, expires_at = create_token(
        user_id=user.id, username=user.username, real_name=user.real_name, org_id=user.org_id
    )
    user.last_login_at = datetime.now()
    audit_service.log(db, user, module="auth", action="login",
                      object_type="user", object_id=user.id, object_no=user.username,
                      request=request)
    db.commit()
    return {
        "token": token,
        "token_type": "Bearer",
        "expires_at": expires_at,
        "must_change_pwd": user.must_change_pwd,
        "user": user_brief(user),
    }


@router.post("/logout")
def logout(request: Request,
           user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    """登出：令牌为无状态，服务端仅记录日志（前端清除本地令牌即可）。"""
    audit_service.log(db, user, module="auth", action="logout", request=request)
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """当前用户：基本信息 + 角色 + 权限点 + 按权限裁剪的菜单树。"""
    perms = collect_perms(db, user)
    return {
        "user": user_brief(user),
        "roles": roles_brief(user),
        "perms": sorted(perms),
        "menus": menu_tree_for(perms, user.is_superadmin),
        "auth_enabled": AUTH_ENABLED,
    }


@router.post("/change-password")
def change_password(request: Request, payload: dict = Body(...),
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """修改密码：校验原密码 + 强度策略；成功后清除首登强制改密标记。"""
    old = str(payload.get("old_password") or "")
    new = str(payload.get("new_password") or "")

    if not verify_password(old, user.password_hash):
        raise HTTPException(status_code=422, detail="原密码不正确")

    params = get_sys_params(db)
    err = check_password_strength(new, int(params.get("pwd_min_length") or 8))
    if err:
        raise HTTPException(status_code=422, detail=err)
    if verify_password(new, user.password_hash):
        raise HTTPException(status_code=422, detail="新密码不能与原密码相同")

    user.password_hash = hash_password(new)
    user.must_change_pwd = False
    audit_service.log(db, user, module="auth", action="change_pwd",
                      object_type="user", object_id=user.id, object_no=user.username,
                      request=request)
    db.commit()
    return {"ok": True}
