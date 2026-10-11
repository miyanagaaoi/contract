"""认证与权限相关 ORM 模型（V2.0，对应 `12-erp-system-design.md` §4.1）。

- OrgUnit        组织架构（公司/部门/岗位，物化路径 path 用于"及下级"查询）
- User           账号（密码 pbkdf2 加盐哈希；停用即失效）
- Role           角色（数据范围枚举 + 权限点集合）
- UserRole       账号-角色 多对多
- RolePermission 角色-权限点（perm_code 为字符串，权限点真源在 permissions.py）
- OperationLog   操作日志（登录/审核/反审核/作废/权限变更/导出/备份）
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# ---------- 关联表：账号 <-> 角色 ----------
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

# 账号状态
USER_STATUSES = ["enabled", "disabled"]


class OrgUnit(Base):
    """组织节点（树）。`path` 形如 `/1/5/12/`，下级查询用 LIKE 前缀匹配。"""

    __tablename__ = "org_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("org_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unit_type: Mapped[str] = mapped_column(String(16), nullable=False, default="部门")
    leader_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    path: Mapped[str] = mapped_column(String(255), nullable=False, default="/", index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    children: Mapped[list[OrgUnit]] = relationship(
        back_populates="parent", cascade="save-update"
    )
    parent: Mapped[OrgUnit | None] = relationship(
        remote_side=[id], back_populates="children"
    )


class User(Base):
    """账号。`is_superadmin` 绕过权限与数据范围校验（仅用于初始管理员）。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    real_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    org_id: Mapped[int | None] = mapped_column(
        ForeignKey("org_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled", index=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    must_change_pwd: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, back_populates="users", lazy="selectin"
    )
    org: Mapped[OrgUnit | None] = relationship(lazy="joined")


class Role(Base):
    """角色。权限点取并集、数据范围取最宽（多角色时）。"""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    data_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="SELF")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    users: Mapped[list[User]] = relationship(secondary=user_roles, back_populates="roles")
    permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def perm_codes(self) -> list[str]:
        return [p.perm_code for p in self.permissions]


class RolePermission(Base):
    """角色-权限点关系。权限点的定义真源在 `app/permissions.py`（代码常量）。"""

    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    perm_code: Mapped[str] = mapped_column(String(64), primary_key=True)

    role: Mapped[Role] = relationship(back_populates="permissions")


class OperationLog(Base):
    """操作日志：登录/登出、审核/反审核/作废、权限与主数据变更、导出、备份。"""

    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    real_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    module: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    object_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    object_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )


class UserIdentity(Base):
    """外部身份绑定（V2.4 飞书接入；表名 `user_identities`）。

    **为什么独立成表，而不是给 `users` 加一列 `feishu_open_id`：**

    1. 一个账号将来可能绑多个身份源（钉钉/企业微信），加列只能绑一个；
    2. `db_migrate` 的 SQLite 限制（`ALTER TABLE ADD COLUMN` 不能带外键）在加列方案下
       会让外键只能靠应用层保证，新表则可以正常带 FK + 唯一约束；
    3. 解绑 = 删行，不会在 `users` 上留下"看起来绑过、其实为空"的语义。

    `open_id` 是**应用内**唯一标识（官方推荐做主键）：换应用或换租户会变，
    故同时留 `union_id`（开发商维度）以便将来换应用时复用绑定。
    唯一约束 `(provider, open_id)` 防"一个飞书身份绑两个系统账号"。
    """

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "open_id", name="uq_user_identity_provider_open"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="feishu",
                                           index=True)
    open_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    union_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tenant_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bound_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    bound_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
