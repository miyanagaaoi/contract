"""通知发送队列（outbox）模型 —— 飞书接入 M2（见 `docs/27-feishu-integration-plan.md` §4.1/§4.3）。

## 为什么要有这张表

飞书消息是**跨网络的第三方调用**：会超时、会限流（同一用户 5 QPS）、会因权限或
可用范围报错。若在业务请求里直接调它：

1. 用户点"提交单据"要等一次外网往返，网络抖动直接拖慢录入；
2. 审核失败会连带把已经写入的库存/状态变化一起回滚，口径混乱；
3. 违反"操作日志与业务动作同事务"的既有约定（`12-erp-system-design.md` §5.4）。

因此业务侧只做一件事：在**同一事务**里插一条 `pending` 记录，提交即返回；
真实发送交给后台线程（`services/feishu/notify_service.py`），失败可重试、
进程重启不丢（队列在库里）。

## 幂等

`event_key` 全局唯一。飞书接口本身是"至少一次"语义，重试、重复触发都很常见，
靠这个唯一约束保证"同一业务事件只发一次"（AC-FS-07）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

# 发送状态：pending 待发 → sending 发送中 → sent / failed；skipped 表示无需发送（如无绑定）
NOTIFY_STATUSES = ["pending", "sending", "sent", "failed", "skipped"]

# 通知类别（仅用于展示与每日摘要去重；与 notify_service 入队时的取值保持一致）
NOTIFY_CATEGORIES = ["doc_submit", "doc_approved", "doc_rejected", "doc_unapproved",
                     "doc_completed", "doc_voided", "warranty", "stock", "todo", "test"]


class Notification(Base):
    """待发送/已发送的飞书消息（outbox）。"""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 幂等键，形如 `doc:purchase_order:12:submit:u3`
    event_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="feishu")
    recipient_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 收件人 open_id 快照：重试时不再查绑定表，避免绑定变更导致消息投递漂移
    recipient_open_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    msg_type: Mapped[str] = mapped_column(String(16), nullable=False, default="interactive")
    # 卡片/文本体（JSON 字符串）；与 msg_type 一起直接交给飞书 im/v1/messages 的 content
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
