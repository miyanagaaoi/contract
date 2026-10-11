"""飞书接入 API（V2.4，见 `docs/27-feishu-integration-plan.md` §4.2）。

分两组路由：

- `auth_router`（`/api/auth/feishu`）：免登入口、授权码回调兑换、自助绑定/解绑；
- `system_router`（`/api/system/feishu`）：配置自检、连通性测试、测试消息、outbox 运维。

**安全口径**：任何响应都**不返回 app_secret**；`app_id` 只以掩码形式出现。
飞书只负责证明"你是谁"，登录成功后签发的仍是本系统 JWT（`security.create_token`），
权限、数据范围、审计与密码登录完全同源（AC-FS-02）。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import APP_NAME, APP_VERSION, FEISHU_APP_ID, FEISHU_REDIRECT_URI, FEISHU_API_BASE, feishu_ready
from ..database import get_db
from ..models_auth import User, UserIdentity
from ..services import audit_service
from ..services.feishu import card, client, identity_service, notify_service
from ..services.permission_service import get_current_user, require_perm
from .auth import roles_brief, user_brief

auth_router = APIRouter(prefix="/api/auth/feishu", tags=["feishu"])
system_router = APIRouter(prefix="/api/system/feishu", tags=["feishu-admin"])

PROVIDER = identity_service.PROVIDER


def _to_http(exc: Exception) -> HTTPException:
    """把服务层异常映射为 HTTP 状态：未绑定 401、state 失效 400、
    未启用 503、飞书侧失败 502。"""
    if isinstance(exc, identity_service.IdentityError):
        return HTTPException(status_code=exc.status, detail=str(exc))
    if isinstance(exc, client.FeishuError):
        status = 503 if exc.kind == "config" else 502
        return HTTPException(status_code=status, detail=str(exc))
    return HTTPException(status_code=500, detail="飞书接口调用失败")


def _mask_app_id(app_id: str) -> str | None:
    if not app_id:
        return None
    return app_id[:6] + "***" if len(app_id) > 6 else app_id


def _fmt_dt(value) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None


# ==================== 免登（公开） ====================

@auth_router.get("/config", summary="飞书登录入口开关（公开）")
def feishu_config():
    """登录页据此决定是否显示「飞书登录」。不泄露任何密钥。"""
    return {"enabled": feishu_ready(),
            "redirect_uri": FEISHU_REDIRECT_URI or None}


@auth_router.get("/authorize-url", summary="取免登授权地址（公开）")
def feishu_authorize_url():
    """返回带一次性 `state` 的授权地址；前端拿到后整页跳转过去。"""
    if not feishu_ready():
        raise HTTPException(status_code=503, detail="飞书登录未启用，请联系管理员配置")
    state = identity_service.make_state()
    return {"url": client.build_authorize_url(state)}


@auth_router.post("/login", summary="飞书免登（授权码换本系统令牌）")
def feishu_login(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    """`{code, state}` → 本系统 JWT。未绑定的飞书账号一律拒绝（方案 §5.1 方案 A）。"""
    code = str(payload.get("code") or "").strip()
    state = str(payload.get("state") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="缺少授权码，请重新发起飞书登录")
    try:
        result = identity_service.login_by_code(db, code=code, state=state, request=request)
    except (identity_service.IdentityError, client.FeishuError) as exc:
        raise _to_http(exc)
    user = db.get(User, result["user_id"])
    if user is None:
        raise HTTPException(status_code=401, detail="账号不存在，请联系管理员")
    return {
        "token": result["token"],
        "token_type": "Bearer",
        "expires_at": result["expires_at"],
        "must_change_pwd": result["must_change_pwd"],
        "user": user_brief(user),
        "roles": roles_brief(user),
    }


# ==================== 自助绑定（需登录） ====================

@auth_router.get("/bind-info", summary="当前账号的飞书绑定状态")
def feishu_bind_info(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ident = identity_service.identity_of(db, user.id)
    return {
        "enabled": feishu_ready(),
        "bound": ident is not None,
        "display_name": ident.display_name if ident else None,
        "union_id": ident.union_id if ident else None,
        "bound_at": _fmt_dt(ident.bound_at) if ident else None,
        "last_login_at": _fmt_dt(ident.last_login_at) if ident else None,
    }


@auth_router.post("/bind", summary="把飞书身份绑定到当前账号")
def feishu_bind(request: Request, payload: dict = Body(...),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    code = str(payload.get("code") or "").strip()
    state = str(payload.get("state") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="缺少授权码，请重新发起绑定")
    try:
        ident = identity_service.bind_by_code(db, user=user, code=code, state=state,
                                             request=request)
    except (identity_service.IdentityError, client.FeishuError) as exc:
        raise _to_http(exc)
    return {"ok": True, "display_name": ident.display_name, "open_id": ident.open_id}


@auth_router.delete("/bind", summary="解绑当前账号的飞书身份")
def feishu_unbind(request: Request, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    removed = identity_service.unbind(db, user.id)
    audit_service.log(db, user, module="auth", action="feishu_unbind",
                      object_type="user", object_id=user.id, object_no=user.username,
                      detail="解绑飞书身份" if removed else "解绑飞书身份（本无绑定）",
                      request=request)
    db.commit()
    return {"ok": True, "removed": removed}


# ==================== 系统管理（需权限点） ====================

@system_router.get("/config", summary="飞书接入状态与配置自检")
def admin_feishu_config(_user: User = Depends(require_perm("system.feishu.view")),
                        db: Session = Depends(get_db)):
    total_users = int(db.query(User).count() or 0)
    bound = int(db.query(UserIdentity).filter(UserIdentity.provider == PROVIDER).count() or 0)
    unbound_rows = (db.query(User)
                    .filter(User.status == "enabled",
                            ~User.id.in_(db.query(UserIdentity.user_id)
                                         .filter(UserIdentity.provider == PROVIDER)))
                    .order_by(User.id).limit(10).all())
    binding_rows = (db.query(UserIdentity)
                    .filter(UserIdentity.provider == PROVIDER).all())
    return {
        "enabled": feishu_ready(),
        "app_id": _mask_app_id(FEISHU_APP_ID),
        "redirect_uri": FEISHU_REDIRECT_URI or None,
        "api_base": FEISHU_API_BASE,
        "base_url_configured": bool(FEISHU_REDIRECT_URI),
        "bound_users": bound,
        "total_users": total_users,
        "unbound_users": [{"id": u.id, "username": u.username, "real_name": u.real_name}
                          for u in unbound_rows],
        # 账号管理页据此显示"已绑定/未绑定"（小团队，全量返回没有压力）
        "bindings": {r.user_id: {"open_id": r.open_id, "display_name": r.display_name,
                                 "bound_at": _fmt_dt(r.bound_at)} for r in binding_rows},
        "outbox": notify_service.outbox_stats(db),
    }


@system_router.post("/check", summary="连通性自检（出网取应用令牌）")
def admin_feishu_check(_user: User = Depends(require_perm("system.feishu.view"))):
    try:
        return client.check_connectivity()
    except client.FeishuError as exc:
        raise _to_http(exc)


@system_router.post("/test-message", summary="给当前账号发一条测试卡片")
def admin_feishu_test(request: Request,
                      user: User = Depends(require_perm("system.feishu.edit")),
                      db: Session = Depends(get_db)):
    """**同步**发送：管理员需要马上看到失败原因（权限不足 / 不在可用范围 / 网络不通）。

    这是运维动作，不在业务事务内，因此不违反"业务请求不发网络调用"的约束。
    """
    open_id = identity_service.bound_open_id(db, user.id)
    if not open_id:
        raise HTTPException(status_code=422,
                            detail="当前账号尚未绑定飞书，请先绑定后再发测试消息")
    card_obj, _ = card.build_test_card(app_name=APP_NAME, version=APP_VERSION,
                                       user_name=user.real_name or user.username)
    try:
        client.send_message(receive_id=open_id, msg_type="interactive",
                            content=json.dumps(card_obj, ensure_ascii=False))
    except client.FeishuError as exc:
        audit_service.log(db, user, module="system", action="feishu_test", result="fail",
                          detail=str(exc)[:200], request=request)
        db.commit()
        raise _to_http(exc)
    audit_service.log(db, user, module="system", action="feishu_test",
                      detail="飞书测试消息发送成功", request=request)
    db.commit()
    return {"ok": True}


@system_router.get("/outbox", summary="通知发送队列状态")
def admin_feishu_outbox(_user: User = Depends(require_perm("system.feishu.view")),
                        db: Session = Depends(get_db)):
    return notify_service.outbox_stats(db)


@system_router.post("/retry-failed", summary="重试所有失败通知")
def admin_feishu_retry(_user: User = Depends(require_perm("system.feishu.edit")),
                       db: Session = Depends(get_db)):
    return {"ok": True, "reset": notify_service.retry_failed(db)}


@system_router.post("/unbind", summary="管理员解绑某账号的飞书身份")
def admin_feishu_unbind(request: Request, payload: dict = Body(...),
                        user: User = Depends(require_perm("system.feishu.edit")),
                        db: Session = Depends(get_db)):
    """换人 / 离职场景：管理员把某账号上的飞书绑定摘掉，避免消息继续投递给下一位使用者。"""
    try:
        target_id = int(payload.get("user_id") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="账号 ID 不合法")
    if target_id <= 0:
        raise HTTPException(status_code=422, detail="缺少账号 ID")
    target = db.get(User, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    removed = identity_service.unbind(db, target_id)
    audit_service.log(db, user, module="system", action="feishu_unbind",
                      object_type="user", object_id=target_id, object_no=target.username,
                      detail="管理员解绑飞书身份" if removed else "管理员解绑（本无绑定）",
                      request=request)
    db.commit()
    return {"ok": True, "removed": removed}
