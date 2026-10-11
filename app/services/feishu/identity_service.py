"""飞书身份绑定与免登（V2.4 起，见 `docs/27-feishu-integration-plan.md` §5）。

## 核心口径

- **飞书只做认证，不做授权**：本模块只回答"这个飞书账号对应哪个系统账号"，
  拿到账号后由 `security.create_token` 签发本系统 JWT，权限/数据范围/审计完全沿用既有逻辑。
- **未绑定则自动建号，但只建"身份"不建"权限"**（2026-02 业务要求）：
  扫码登录发现 `open_id` 没有绑定时，按飞书返回的信息自动创建系统账号并绑定，
  新账号**零角色、零权限点、无数据范围**，只能看到「等待管理员分配角色」页；
  管理员在账号管理 / 飞书接入里分配角色后才真正可用。
  `CTMS_FEISHU_AUTO_PROVISION=0` 可退回旧口径（未绑定一律 401），用于一键收紧。
- **绝不按手机号/邮箱自动匹配到既有账号**（官方明确手机号/邮箱未经实时核验，改号即越权）：
  自动建号只**新建**账号，登录名与既有账号冲突时加数字后缀，不会顶替任何已有账号。
- **`state` 无状态防重放**（§5.3）：`时间戳.nonce.HMAC`，10 分钟有效，不引入会话表。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ... import config
from ...config import get_jwt_secret
from ...models_auth import User, UserIdentity
from ...security import create_token, hash_password
from .. import audit_service
from ..permission_service import pending_role
from . import client

PROVIDER = "feishu"
_STATE_TTL = 600                    # state 有效期（秒）
_STATE_MODES = ("login", "bind")    # state 可携带的调用场景


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


def make_state(mode: str = "login") -> str:
    """生成一次性 state（内含时间戳、随机数与**调用场景**，HMAC 签名）。

    场景（`login` / `bind`）签进 state 而**不**放 sessionStorage：sessionStorage 是
    按 origin 隔离的 —— 用户从 `localhost` 登录、回调却跳到内网 IP 时标记就丢了，
    自助绑定会被误当成免登（表现为"刚绑定完又提示未绑定"）。签进 state 则一定随回调回来。
    """
    scene = mode if mode in _STATE_MODES else "login"
    raw = f"{int(time.time())}.{secrets.token_urlsafe(12)}.{scene}"
    sig = hmac.new(get_jwt_secret().encode("utf-8"), raw.encode("ascii"),
                   hashlib.sha256).digest()
    return f"{raw}.{_b64e(sig)}"


def verify_state(state: str) -> str:
    """校验 state 的签名与时效；返回携带的场景（`login` / `bind`）。

    失败抛 `IdentityError`（防 CSRF / 重放）。返回值仅供调用方记账，
    真正决定"调哪个接口"的是**接口本身**，不是 state。
    """
    parts = (state or "").split(".")
    if len(parts) != 4:
        raise IdentityError("登录状态参数格式错误，请重新发起飞书登录")
    ts_s, nonce, scene, sig = parts
    raw = f"{ts_s}.{nonce}.{scene}"
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
    return scene if scene in _STATE_MODES else "login"


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


# ---------------- 自动建号（未绑定飞书账号首次扫码） ----------------

_USERNAME_DROP = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_USERNAME = 48          # users.username 是 64：留出 `_NN` 去重后缀的余量


def _clean_username(raw: str) -> str:
    """把飞书字段清洗成合法登录名（去空白/非法字符，首尾不留下 `.` `_` `-`）。"""
    return _USERNAME_DROP.sub("", str(raw or "").strip()).strip("._-")[:_MAX_USERNAME]


def _email_local(info: dict) -> str:
    for key in ("email", "enterprise_email"):
        value = str(info.get(key) or "")
        if "@" in value:
            return value.split("@", 1)[0]
    return ""


def username_candidates(info: dict) -> list[str]:
    """登录名候选，按"管理员越好认"排序：工号 → 邮箱前缀 → 手机号 → open_id 片段。

    刻意**不**用飞书姓名做主候选：中文姓名清洗后为空，硬转拼音只会多一个要维护的依赖；
    姓名类字段只用于 `real_name`（账号列表里显示的就是它）。
    """
    open_id = str(info.get("open_id") or "")
    raw = [str(info.get("employee_no") or ""), _email_local(info),
           str(info.get("mobile") or ""), f"fs_{open_id[-10:]}"]
    out: list[str] = []
    for item in raw:
        name = _clean_username(item)
        if name and name.lower() not in {o.lower() for o in out}:
            out.append(name)
    return out or ["feishu_user"]


def _username_taken(db: Session, username: str) -> bool:
    """大小写不敏感判重：`ZhangSan` 与 `zhangsan` 并存会让管理员彻底分不清谁是谁。"""
    return (db.query(User.id)
            .filter(func.lower(User.username) == username.lower())
            .first()) is not None


def unique_username(db: Session, info: dict) -> str:
    """取一个未占用的登录名（冲突时加 `_2`/`_3`…，绝不顶替既有账号）。"""
    for base in username_candidates(info):
        if not _username_taken(db, base):
            return base
        for index in range(2, 100):
            candidate = f"{base}_{index}"[:64]
            if not _username_taken(db, candidate):
                return candidate
    raise IdentityError("无法生成唯一登录名，请让管理员在账号管理中手工创建", status=409)


def _short(value, limit: int) -> str | None:
    return str(value or "").strip()[:limit] or None


def provision_user_from_feishu(db: Session, *, info: dict,
                               request=None) -> tuple[User, UserIdentity]:
    """按飞书身份自动建号并绑定：**只建身份，不给任何角色**。

    与「先绑定后免登」的唯一差别是省掉"管理员预先建号"这一步，权限边界**没有**放松：
    新账号零角色 → `collect_perms` 为空、菜单为空、数据范围为最窄，登录后只能停在
    「等待管理员分配角色」页，管理员分配角色后才可用。

    密码写成随机串：管理员重置密码之前该账号**无法**用密码登录，
    因此不会出现"自动建号顺带开了一个猜得到的口令"。
    """
    open_id = str(info.get("open_id") or "")
    if not open_id:
        raise IdentityError("飞书未返回 open_id，无法自动建号")
    display_name = str(info.get("name") or info.get("en_name") or "").strip()[:64]
    username = unique_username(db, info)

    user = User(
        username=username,
        real_name=display_name or username,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        org_id=None,
        phone=_short(info.get("mobile"), 32),
        email=_short(info.get("email") or info.get("enterprise_email"), 128),
        status="enabled",
        is_superadmin=False,
        # 没有可用初始密码，若强制改密会把用户永久卡在改密页（改密要验原密码）
        must_change_pwd=False,
        remark="飞书扫码登录自动创建，待管理员分配角色",
        created_by=None,
    )
    db.add(user)
    db.flush()

    ident = bind(db, user=user, open_id=open_id,
                 union_id=str(info.get("union_id") or "") or None,
                 tenant_key=str(info.get("tenant_key") or "") or None,
                 display_name=display_name or None)
    audit_service.log(db, None, module="auth", action="feishu_signup",
                      object_type="user", object_id=user.id, object_no=user.username,
                      detail=f"飞书扫码登录自动建号（{user.real_name}），未分配角色，"
                             f"open_id={open_id}", request=request)
    return user, ident


# ---------------- 免登 / 自助绑定 ----------------

def _exchange(code: str, state: str) -> dict:
    """校验 state 并用授权码换飞书用户信息。"""
    verify_state(state)
    user_token = client.oauth_exchange_code(code)
    return client.get_user_info(user_token)


def login_by_code(db: Session, *, code: str, state: str, request=None) -> dict:
    """飞书免登：换身份 → 查绑定（未绑定则自动建号）→ 签发**本系统** JWT。

    账号停用 → 403。自动建号开关关闭时，未绑定 → 401（旧口径）。
    返回里的 `auto_provisioned` / `pending_roles` 供前端提示"账号已创建，待分配角色"。
    """
    info = _exchange(code, state)
    open_id = str(info.get("open_id") or "")
    user, ident = user_by_open_id(db, open_id)
    auto_provisioned = False
    if ident is None or user is None:
        if not config.FEISHU_AUTO_PROVISION:
            # 审计：免登失败也要留痕（与密码登录失败同样的处理方式）
            audit_service.log(db, None, module="auth", action="feishu_login", result="fail",
                              object_no=open_id, detail="飞书账号未绑定系统账号",
                              request=request)
            db.commit()
            raise IdentityError("飞书账号尚未绑定系统账号，请联系管理员绑定后再登录", status=401)
        # 自动建号：零角色，权限由管理员后续分配（AC-FS-01B）
        try:
            user, ident = provision_user_from_feishu(db, info=info, request=request)
        except IntegrityError:
            # 并发扫码（两个标签页先后完成授权）时唯一约束会挡下第二次建号：
            # 回滚后按 open_id 再查一次 —— 对方已建好就直接复用，否则给出可重试的提示，
            # 不能把 IntegrityError 漏成 500「飞书接口调用失败」。
            db.rollback()
            user, ident = user_by_open_id(db, open_id)
            if ident is None or user is None:
                audit_service.log(db, None, module="auth", action="feishu_login",
                                  result="fail", object_no=open_id,
                                  detail="并发自动建号冲突", request=request)
                db.commit()
                raise IdentityError("账号创建冲突，请重新扫码登录一次", status=409)
        else:
            auto_provisioned = True
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
                      detail=("飞书免登（自动建号，待分配角色）" if auto_provisioned
                              else "飞书免登"),
                      request=request)
    waiting = pending_role(db, user)
    db.commit()
    return {"token": token, "token_type": "Bearer", "expires_at": expires_at,
            "user_id": user.id, "must_change_pwd": user.must_change_pwd,
            "auto_provisioned": auto_provisioned, "pending_roles": waiting}


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
