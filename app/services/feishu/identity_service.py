"""飞书身份绑定与免登（V2.4，见 `docs/27-feishu-integration-plan.md` §5）。

## 核心口径

- **飞书只做认证，不做授权**：本模块只回答"这个飞书账号对应哪个系统账号"，
  拿到账号后由 `security.create_token` 签发本系统 JWT，权限/数据范围/审计完全沿用既有逻辑。
- **默认"先绑定后免登"**（§5.1 方案 A）：未绑定的飞书账号一律拒绝，绝不自动建号，
  也不按手机号/邮箱自动匹配（官方明确手机号/邮箱未经实时核验，改号即越权）。
- **`state` 无状态防重放**（§5.3）：`时间戳.nonce.HMAC`，10 分钟有效，不引入会话表。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime

from sqlalchemy.orm import Session

from ...config import get_jwt_secret
from ...models_auth import User, UserIdentity
from ...security import create_token
from .. import audit_service
from . import client

PROVIDER = "feishu"
_STATE_TTL = 600            # state 有效期（秒）


class IdentityError(Exception):
    """身份匹配/绑定失败。`status` 供路由层映射 HTTP 状态码。"""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ---------------- state 防重放 ----------------

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(txt: str) -> bytes:
    return base64.urlsafe_b64decode(txt + "=" * (-len(txt) % 4))


def make_state() -> str:
    """生成一次性 state（内含时间戳与随机数，HMAC 签名）。"""
    raw = f"{int(time.time())}.{secrets.token_urlsafe(12)}"
    sig = hmac.new(get_jwt_secret().encode("utf-8"), raw.encode("ascii"),
                   hashlib.sha256).digest()
    return f"{raw}.{_b64e(sig)}"


def verify_state(state: str) -> None:
    """校验 state 的签名与时效；失败抛 `IdentityError`（防 CSRF / 重放）。"""
    parts = (state or "").split(".")
    if len(parts) != 3:
        raise IdentityError("登录状态参数格式错误，请重新发起飞书登录")
    ts_s, nonce, sig = parts
    raw = f"{ts_s}.{nonce}"
    expect = hmac.new(get_jwt_secret().encode("utf-8"), raw.encode("ascii"),
                      hashlib.sha256).digest()
    try:
        actual = _b64d(sig)
    except Exception:
        raise IdentityError("登录状态参数校验失败，请重新发起飞书登录")
    if not hmac.compare_digest(expect, actual):
        raise IdentityError("登录状态参数校验失败，请重新发起飞书登录")
    try:
        issued = int(ts_s)
    except (TypeError, ValueError):
        raise IdentityError("登录状态参数校验失败，请重新发起飞书登录")
    if abs(int(time.time()) - issued) > _STATE_TTL:
        raise IdentityError("飞书登录已超时（超过 10 分钟），请重新发起")


# ---------------- 绑定查询 ----------------

def identity_of(db: Session, user_id: int, provider: str = PROVIDER) -> UserIdentity | None:
    """某系统账号的外部身份绑定。"""
    return (db.query(UserIdentity)
            .filter(UserIdentity.user_id == user_id, UserIdentity.provider == provider)
            .first())


def user_by_open_id(db: Session, open_id: str, provider: str = PROVIDER) -> tuple[User | None, UserIdentity | None]:
    """按 `open_id` 反查系统账号。返回 `(user, identity)`；未绑定返回 `(None, None)`。"""
    ident = (db.query(UserIdentity)
             .filter(UserIdentity.provider == provider, UserIdentity.open_id == open_id)
             .first())
    if ident is None:
        return None, None
    return db.get(User, ident.user_id), ident


def bind_map(db: Session, user_ids: list[int]) -> dict[int, dict]:
    """批量取绑定信息（账号列表页展示用，避免 N+1）。"""
    if not user_ids:
        return {}
    rows = (db.query(UserIdentity)
            .filter(UserIdentity.provider == PROVIDER, UserIdentity.user_id.in_(user_ids))
            .all())
    return {r.user_id: {"open_id": r.open_id, "display_name": r.display_name,
                        "bound_at": r.bound_at} for r in rows}


def bound_open_id(db: Session, user_id: int) -> str | None:
    """取某账号绑定的 `open_id`（推送收件人）。未绑定返回 None。"""
    ident = identity_of(db, user_id)
    if ident is None:
        return None
    user = db.get(User, ident.user_id)
    # 与登录态一致：停用账号不投递
    if user is None or user.status != "enabled":
        return None
    return ident.open_id


# ---------------- 绑定写操作 ----------------

def bind(db: Session, *, user: User, open_id: str, union_id: str | None = None,
         tenant_key: str | None = None, display_name: str | None = None,
         bound_by: int | None = None) -> UserIdentity:
    """把某个飞书身份绑定到系统账号（幂等：重复绑定同一对则只刷新快照）。"""
    if not open_id:
        raise IdentityError("缺少飞书 open_id，无法绑定")

    existing = (db.query(UserIdentity)
                .filter(UserIdentity.provider == PROVIDER, UserIdentity.open_id == open_id)
                .first())
    if existing is not None:
        if existing.user_id != user.id:
            other = db.get(User, existing.user_id)
            raise IdentityError(
                f"该飞书账号已绑定到其他系统账号（{other.username if other else existing.user_id}），"
                f"请先在那边解绑", status=409)
        existing.union_id = union_id or existing.union_id
        existing.tenant_key = tenant_key or existing.tenant_key
        existing.display_name = display_name or existing.display_name
        return existing

    # 同一系统账号只保留一个飞书身份（换人场景：先解绑再绑）
    current = identity_of(db, user.id)
    if current is not None:
        db.delete(current)
        db.flush()

    ident = UserIdentity(user_id=user.id, provider=PROVIDER, open_id=open_id,
                         union_id=union_id, tenant_key=tenant_key,
                         display_name=display_name, bound_at=datetime.now(),
                         bound_by=bound_by if bound_by is not None else user.id)
    db.add(ident)
    db.flush()
    return ident


def unbind(db: Session, user_id: int, provider: str = PROVIDER) -> bool:
    """解绑（返回是否确有绑定被删除）。解绑后该账号的飞书免登立即失效。"""
    ident = identity_of(db, user_id, provider)
    if ident is None:
        return False
    db.delete(ident)
    db.flush()
    return True


# ---------------- 免登 / 自助绑定 ----------------

def _exchange(code: str, state: str) -> dict:
    """校验 state 并用授权码换飞书用户信息。"""
    verify_state(state)
    user_token = client.oauth_exchange_code(code)
    return client.get_user_info(user_token)


def login_by_code(db: Session, *, code: str, state: str, request=None) -> dict:
    """飞书免登：换身份 → 查绑定 → 签发**本系统** JWT。

    未绑定 → `IdentityError(status=401)`（AC-FS-01）；账号停用 → 401。
    """
    info = _exchange(code, state)
    open_id = str(info.get("open_id") or "")
    user, ident = user_by_open_id(db, open_id)
    if ident is None or user is None:
        # 审计：免登失败也要留痕（与密码登录失败同样的处理方式）
        audit_service.log(db, None, module="auth", action="feishu_login", result="fail",
                          object_no=open_id, detail="飞书账号未绑定系统账号", request=request)
        db.commit()
        raise IdentityError("飞书账号尚未绑定系统账号，请联系管理员绑定后再登录", status=401)
    if user.status != "enabled":
        audit_service.log(db, user, module="auth", action="feishu_login", result="fail",
                          detail="账号已停用", request=request)
        db.commit()
        raise IdentityError("账号已停用，请联系管理员", status=403)

    # 快照刷新（姓名/union_id 可能变化）
    ident.display_name = str(info.get("name") or ident.display_name or "")
    ident.union_id = str(info.get("union_id") or ident.union_id or "") or None
    ident.last_login_at = datetime.now()

    token, expires_at = create_token(user_id=user.id, username=user.username,
                                     real_name=user.real_name, org_id=user.org_id)
    user.last_login_at = datetime.now()
    audit_service.log(db, user, module="auth", action="feishu_login",
                      object_type="user", object_id=user.id, object_no=user.username,
                      detail="飞书免登", request=request)
    db.commit()
    return {"token": token, "token_type": "Bearer", "expires_at": expires_at,
            "user_id": user.id, "must_change_pwd": user.must_change_pwd}


def bind_by_code(db: Session, *, user: User, code: str, state: str, request=None) -> UserIdentity:
    """自助绑定：已登录用户把自己的飞书身份绑到当前账号。"""
    info = _exchange(code, state)
    ident = bind(db, user=user, open_id=str(info.get("open_id") or ""),
                 union_id=str(info.get("union_id") or "") or None,
                 tenant_key=str(info.get("tenant_key") or "") or None,
                 display_name=str(info.get("name") or "") or None,
                 bound_by=user.id)
    audit_service.log(db, user, module="auth", action="feishu_bind",
                      object_type="user", object_id=user.id, object_no=user.username,
                      detail=f"绑定飞书身份（{ident.display_name or ident.open_id}）",
                      request=request)
    db.commit()
    return ident
