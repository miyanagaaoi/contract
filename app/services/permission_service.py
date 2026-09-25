"""权限与数据范围服务（对应 `12-erp-system-design.md` §3.4、§3.5）。

职责：
- `collect_perms`      多角色权限**并集**（超管=全部权限点）
- `get_current_user`   登录态解析（含 `CTMS_AUTH_ENABLED=0` 本地调试开关）
- `require_perm`       接口级按钮权限校验依赖
- `apply_data_scope`   列表查询的数据范围过滤（本人/本部门/本部门及下级/全部）

关键约束：**权限判定只在服务端**执行；前端隐藏按钮仅改善体验（AC-V2-41）。
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import AUTH_ENABLED
from ..database import get_db
from ..models_auth import OrgUnit, User
from ..permissions import PERM_CODES, widest_scope
from ..security import TokenError, decode_token

# auto_error=False：缺少 Authorization 头时由我们自己返回中文 401
_bearer = HTTPBearer(auto_error=False)


def collect_perms(db: Session, user: User) -> set[str]:
    """用户权限点集合：启用角色的权限并集，并剔除已下线的权限点。"""
    if user.is_superadmin:
        return set(PERM_CODES)
    codes: set[str] = set()
    for role in (user.roles or []):
        if role.enabled:
            codes.update(role.perm_codes)
    return codes & PERM_CODES


def _fallback_user(db: Session) -> User:
    """调试模式（AUTH_ENABLED=0）下使用的系统账号：第一个超级管理员。"""
    user = db.query(User).filter(User.is_superadmin == True).first()  # noqa: E712
    if user is None:
        raise HTTPException(500, "未找到超级管理员账号，请先执行：python -m app.init_db")
    return user


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """解析登录态。未登录 / 令牌无效 / 账号停用 → 401。

    成功后把当前用户写入 `db.info["user"]`，供审计层（变更历史/操作日志）
    在同一请求内取用，避免逐层透传用户参数。
    """
    user = _resolve_user(cred, db)
    db.info["user"] = user
    return user


def _resolve_user(cred: HTTPAuthorizationCredentials | None, db: Session) -> User:
    if not AUTH_ENABLED:
        return _fallback_user(db)
    if cred is None or not cred.credentials:
        raise HTTPException(401, "未登录，请先登录")
    try:
        payload = decode_token(cred.credentials)
    except TokenError as exc:
        raise HTTPException(401, str(exc))
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(401, "令牌无效")
    user = db.get(User, user_id)
    if user is None or user.status != "enabled":
        # 无状态令牌无法服务端吊销，靠每次请求回查账号状态实现"停用立即失效"
        raise HTTPException(401, "登录已失效，请重新登录")
    return user


def require_perm(code: str):
    """接口级权限校验依赖。

    用法：`user: User = Depends(require_perm("purchase.order.approve"))`
    """

    def _dep(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if user.is_superadmin:
            return user
        if code not in collect_perms(db, user):
            raise HTTPException(403, f"无权限：{code}")
        return user

    return _dep


# ---------------- 数据范围 ----------------

def descendant_org_ids(db: Session, org_id: int | None) -> list[int]:
    """某组织节点及其全部下级节点 id（物化路径前缀匹配，含自身）。"""
    if org_id is None:
        return []
    node = db.get(OrgUnit, org_id)
    if node is None:
        return [org_id]
    prefix = node.path or f"/{org_id}/"
    rows = db.query(OrgUnit.id).filter(OrgUnit.path.like(prefix + "%")).all()
    ids = [r[0] for r in rows]
    return ids or [org_id]


def data_scope_of(user: User) -> str:
    """用户生效的数据范围：多角色取**最宽**（BR-V2-08）。"""
    if user.is_superadmin:
        return "ALL"
    return widest_scope([r.data_scope for r in (user.roles or []) if r.enabled])


def apply_data_scope(query, model, user: User, db: Session):
    """按数据范围过滤查询。

    模型需具备 `org_id`（归属组织快照）与 `created_by`（创建人）字段；
    主数据（客户/供应商/物料等）**不做隔离**，调用方不要对它使用本函数。
    """
    if user.is_superadmin:
        return query
    scope = data_scope_of(user)
    if scope == "ALL":
        return query

    conds = []
    if scope == "SELF":
        conds.append(model.created_by == user.id)
    elif scope == "DEPT":
        if user.org_id is None:
            conds.append(model.created_by == user.id)
        else:
            conds.append(model.org_id == user.org_id)
    elif scope == "DEPT_SUB":
        if user.org_id is None:
            conds.append(model.created_by == user.id)
        else:
            conds.append(model.org_id.in_(descendant_org_ids(db, user.org_id)))
    if not conds:
        return query
    return query.filter(or_(*conds))
