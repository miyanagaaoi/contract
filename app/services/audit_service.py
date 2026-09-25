"""审计服务：操作日志写入（对应 `12-erp-system-design.md` §5.4）。

约定：
- `log()` 只 `db.add()`，**不提交**——由调用方在同一事务内提交，保证日志与业务动作一致；
- 失败场景（如登录失败、越权）需调用方显式 `commit()` 后再抛异常，否则日志会随回滚丢失；
- 操作日志与"变更历史（CHANGE_LOG）"的职责区分：前者记**动作**（谁在何时对哪个对象做了什么），
  后者记**字段级前后值**。
"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from ..models_auth import OperationLog, User


def client_ip(request: Request | None) -> str | None:
    """取客户端 IP：优先 X-Forwarded-For（经 Nginx 反代时），否则取直连地址。"""
    if request is None:
        return None
    headers = getattr(request, "headers", None)
    if headers:
        fwd = headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    client = getattr(request, "client", None)
    return client.host if client else None


def log(db: Session, user: User | None, *, module: str, action: str,
        object_type: str | None = None, object_id: int | None = None,
        object_no: str | None = None, result: str = "success",
        detail: str | None = None, request: Request | None = None) -> OperationLog:
    """写一条操作日志（调用方负责 commit）。"""
    entry = OperationLog(
        user_id=getattr(user, "id", None),
        username=getattr(user, "username", None),
        real_name=getattr(user, "real_name", None),
        module=module,
        action=action,
        object_type=object_type,
        object_id=object_id,
        object_no=object_no,
        result=result,
        detail=detail,
        ip=client_ip(request),
    )
    db.add(entry)
    return entry
