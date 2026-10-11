"""通知 outbox：入队、后台发送、退避重试（V2.4，见 `docs/27-feishu-integration-plan.md` §4.3）。

## 三条硬约束

1. **业务请求内绝不发网络调用**：入队只 `db.add`，发送交给后台线程。
   飞书会超时、会限流（同一用户 5 QPS）、会因权限或可用范围报错 —— 一次外网往返
   不能挂在"提交单据"的响应路径上，更不能把业务事务一起回滚。
2. **失败不影响业务**：发送异常只写 `last_error`，单据该提交成功还是成功（AC-FS-06）。
3. **至多一次实际发送**：本地 `event_key` 唯一约束 + 发送前**原子抢占**
   （`UPDATE ... WHERE status='pending'`），双保险。后者是为将来 `uvicorn --workers N`
   或多副本部署准备的 —— 那时每个进程都有一个 worker（方案 §4.3 的警示）。
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ... import config
from ...database import SessionLocal
from ...models_notify import Notification
from ...permissions import DOC_APPROVE_PERM
from ..permission_service import apply_data_scope, users_with_perm
from . import card as card_mod
from . import client, identity_service

log = logging.getLogger("ctms.feishu")

# 重试退避（分钟）：第 1 次失败后等 1 分钟，第 2 次 5 分钟，之后 30 分钟
BACKOFF_MINUTES = [1, 5, 30]

_WORKER_STOP = threading.Event()
_WORKER_THREAD: threading.Thread | None = None
_POLL_SECONDS = 2.0


# ---------------- 入队（在业务事务内） ----------------

def enqueue(db: Session, *, event_key: str, category: str, recipient_user_id: int,
            card_obj: dict, msg_type: str = "interactive") -> Notification | None:
    """把一条消息写进 outbox（**不提交**，由调用方随业务事务一起提交）。

    返回新建的记录；重复（`event_key` 已存在）或收件人未绑定飞书时返回 None。
    """
    if not config.feishu_ready():
        return None
    open_id = identity_service.bound_open_id(db, recipient_user_id)
    if not open_id:
        return None       # 未绑定飞书：不投递（管理页可见"未绑定人数"）

    content = json.dumps(card_obj, ensure_ascii=False)
    row = Notification(event_key=event_key, category=category, channel="feishu",
                       recipient_user_id=recipient_user_id, recipient_open_id=open_id,
                       msg_type=msg_type, payload=content, status="pending")
    try:
        # savepoint：万一并发撞上 event_key 唯一约束，只回滚这一条，
        # **不污染**调用方的业务事务（否则用户提交单据会因为"消息重复"而失败）
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        return None
    return row


def enqueue_doc_todo(db: Session, *, doc, kind: str, kind_label: str,
                     actor_name: str | None = None) -> int:
    """单据提交后：给**有审核权限且数据范围可见**的账号各推一条待办。"""
    if not config.feishu_ready() or doc is None:
        return 0
    perm = DOC_APPROVE_PERM.get(kind)
    if not perm:
        return 0
    card_obj, _ = card_mod.build_doc_todo_card(doc, kind=kind, kind_label=kind_label,
                                              actor_name=actor_name)
    model = type(doc)
    count = 0
    for user in users_with_perm(db, perm):
        if user.id == getattr(doc, "created_by", None):
            continue      # 不给发起人自己推"待我审核"
        # 数据范围之外的人即使有权限点也看不到该单据，推了只会点开 403
        scoped = apply_data_scope(db.query(model).filter(model.id == doc.id), model, user, db)
        if scoped.first() is None:
            continue
        if enqueue(db, event_key=f"doc:{kind}:{doc.id}:submit:u{user.id}",
                   category="doc_submit", recipient_user_id=user.id,
                   card_obj=card_obj) is not None:
            count += 1
    return count


def enqueue_doc_result(db: Session, *, doc, kind: str, kind_label: str, result: str,
                       reason: str | None = None, operator: str | None = None) -> int:
    """审核/驳回/反审核/作废后：把结果推给**提交人**（无提交人则推给创建人）。"""
    if not config.feishu_ready() or doc is None:
        return 0
    target = getattr(doc, "submitted_by", None) or getattr(doc, "created_by", None)
    if not target:
        return 0
    card_obj, _ = card_mod.build_doc_result_card(doc, kind=kind, kind_label=kind_label,
                                                result=result, reason=reason, operator=operator)
    if enqueue(db, event_key=f"doc:{kind}:{doc.id}:{result}:u{target}",
               category=f"doc_{result}",
               recipient_user_id=int(target), card_obj=card_obj) is None:
        return 0
    return 1


# ---------------- 发送（后台线程） ----------------

def _next_retry_delay_minutes(attempts: int) -> int:
    idx = min(max(attempts - 1, 0), len(BACKOFF_MINUTES) - 1)
    return BACKOFF_MINUTES[idx]


def send_pending(db: Session, *, limit: int = 20) -> dict:
    """发送一批待发通知。返回 `{"sent": n, "failed": n}`。"""
    if not config.feishu_ready():
        return {"sent": 0, "failed": 0, "skipped": "飞书接入未启用"}
    sent = failed = 0
    for _ in range(max(limit, 0)):
        now = datetime.now()
        row = (db.query(Notification)
               .filter(Notification.status == "pending",
                       or_(Notification.next_retry_at.is_(None),
                           Notification.next_retry_at <= now))
               .order_by(Notification.id).first())
        if row is None:
            break

        # 原子抢占：多进程/多副本下只有一个执行者能把它从 pending 改成 sending。
        #
        # ⚠️ 真实踩过的坑：`query.update(synchronize_session=False)` **不会**同步 session 里
        # 已加载的对象快照。若不紧跟 `expire_all()`，那份陈旧对象（status=pending、
        # attempts=0）会在后续 flush 时把旧值原样写回，**覆盖本次抢占** ——
        # 表现为 attempts 不增长、或消息已发出却被改回 pending。
        claimed = (db.query(Notification)
                   .filter(Notification.id == row.id, Notification.status == "pending")
                   .update({"status": "sending", "attempts": Notification.attempts + 1},
                           synchronize_session=False))
        db.commit()
        db.expire_all()
        if claimed != 1:
            continue

        row = db.get(Notification, row.id)
        if row is None:                     # 极端情况：被其他进程删了
            continue
        try:
            client.send_message(
                receive_id=row.recipient_open_id or "",
                msg_type=row.msg_type,
                content=row.payload,
                # 传标准 UUID（由 event_key 派生）：飞书侧 1 小时内去重，与本地唯一约束互补
                uuid=str(uuid.uuid5(uuid.NAMESPACE_URL, row.event_key)),
            )
            row.status = "sent"
            row.sent_at = datetime.now()
            row.last_error = None
            sent += 1
        except client.FeishuError as exc:
            row.last_error = str(exc)[:500]
            if (row.attempts or 0) >= config.FEISHU_MAX_ATTEMPTS:
                row.status = "failed"
            else:
                row.status = "pending"
                row.next_retry_at = (datetime.now()
                                     + timedelta(minutes=_next_retry_delay_minutes(row.attempts or 1)))
            failed += 1
        except Exception as exc:             # noqa: BLE001 - 兜底：任何异常都不能打死 worker
            row.last_error = f"未预期异常：{exc}"[:500]
            row.status = "pending"
            row.next_retry_at = datetime.now() + timedelta(minutes=5)
            failed += 1
        db.commit()

        # 串行节流：守住飞书"同一用户 5 QPS"，也避免突发把接口打限流
        time.sleep(max(config.FEISHU_SEND_INTERVAL_MS, 0) / 1000.0)
    return {"sent": sent, "failed": failed}


def _loop() -> None:
    while not _WORKER_STOP.wait(_POLL_SECONDS):
        try:
            with SessionLocal() as db:
                result = send_pending(db, limit=20)
            if result.get("sent") or result.get("failed"):
                log.info("飞书通知发送：sent=%s failed=%s", result.get("sent"), result.get("failed"))
        except Exception:                     # noqa: BLE001 - 线程不能因单轮异常退出
            log.exception("飞书通知发送线程本轮异常（已忽略，下轮继续）")


# ---------------- 线程生命周期 ----------------

def start_worker() -> bool:
    """启动发送线程（幂等）。飞书未启用时不启动，返回 False。"""
    global _WORKER_THREAD
    if not config.feishu_ready():
        return False
    if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
        return True
    _WORKER_STOP.clear()
    thread = threading.Thread(target=_loop, name="feishu-notify", daemon=True)
    thread.start()
    _WORKER_THREAD = thread
    log.info("飞书通知发送线程已启动")
    return True


def stop_worker(timeout: float = 3.0) -> None:
    """停止发送线程（应用关闭与测试用）。"""
    global _WORKER_THREAD
    _WORKER_STOP.set()
    thread = _WORKER_THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)
    _WORKER_THREAD = None


def is_running() -> bool:
    return _WORKER_THREAD is not None and _WORKER_THREAD.is_alive()


# ---------------- 运维视图 ----------------

def outbox_stats(db: Session) -> dict:
    """系统管理页展示：积压、失败与最近失败原因。"""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    pending = int(db.query(Notification)
                  .filter(Notification.status.in_(("pending", "sending"))).count() or 0)
    failed = int(db.query(Notification).filter(Notification.status == "failed").count() or 0)
    sent = int(db.query(Notification)
               .filter(Notification.status == "sent", Notification.sent_at >= today).count() or 0)
    rows = (db.query(Notification).filter(Notification.status == "failed")
            .order_by(Notification.id.desc()).limit(5).all())
    return {
        "pending": pending, "failed": failed, "sent_today": sent,
        "worker_running": is_running(),
        "recent_failures": [{"event_key": r.event_key, "attempts": r.attempts,
                             "error": r.last_error,
                             "created_at": r.created_at.isoformat(sep=" ", timespec="seconds")
                             if r.created_at else None} for r in rows],
    }


def retry_failed(db: Session, *, limit: int = 50) -> int:
    """把 `failed` 重置为 `pending`（管理员手动重试；清空退避时间与错误）。"""
    rows = (db.query(Notification).filter(Notification.status == "failed")
            .order_by(Notification.id).limit(limit).all())
    for row in rows:
        row.status = "pending"
        row.attempts = 0
        row.next_retry_at = None
        row.last_error = None
    db.commit()
    return len(rows)
