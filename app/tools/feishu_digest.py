"""每日飞书提醒（V2.4 / M3）：待办 + 质保到期 + 库存预警。

## 用法（由既有计划任务每日调用一次）

```bash
python -m app.tools.feishu_digest                      # 全部三类
python -m app.tools.feishu_digest --kinds warranty,stock
python -m app.tools.feishu_digest --dry-run             # 只打印内容，不写库
```

Windows 计划任务 / 宝塔计划任务 / 容器 cron 的既有做法见 `docs/08` §57、`docs/09` §9。

## 为什么是 "CLI + 计划任务"，而不是 Celery / APScheduler

本项目的运维方式本来就是"计划任务跑一行命令"（每日备份就是这么做的），沿用即可：
不新增常驻进程、不新增依赖、失败可见（有 stdout 与退出码）。

## 幂等与打扰控制

- `event_key = digest:{日期}:u{用户}`，**同日同一用户只发一次**（AC-FS-08）；
- 本人**没有任何内容**（无待办、无预警、无到期）时**不发**空消息；
- 每条最多列 `DIGEST_MAX_ITEMS` 条，其余折叠为"等 N 项"（卡片 ≤30 KB，也避免刷屏）。
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .. import config
from ..database import SessionLocal
from ..dicts import get_sys_params
from ..models import Contract
from ..models_auth import User
from ..models_doc import DOC_MODELS
from ..models_master import Product
from ..models_stock import Stock
from ..permissions import DOC_APPROVE_PERM
from ..services.feishu import card as card_mod
from ..services.feishu import identity_service, notify_service
from ..services.permission_service import apply_data_scope, collect_perms


def warranty_rows(db: Session, window_days: int, limit: int) -> tuple[list[dict], int]:
    """质保即将到期（口径与 `routers/dashboard.py` 的 `expiring` 一致）。"""
    today = date.today()
    horizon = today + timedelta(days=window_days)
    base = (db.query(Contract)
            .filter(Contract.deleted == False,                       # noqa: E712
                    Contract.has_warranty == True,                   # noqa: E712
                    Contract.warranty_released == False,             # noqa: E712
                    Contract.warranty_end.isnot(None),
                    Contract.warranty_end >= today,
                    Contract.warranty_end <= horizon))
    total = int(base.count() or 0)
    rows = base.order_by(Contract.warranty_end).limit(limit).all()
    return ([{"contract_no": c.contract_no, "name": c.name,
              "warranty_end": c.warranty_end.isoformat(),
              "days_left": (c.warranty_end - today).days} for c in rows], total)


def stock_rows(db: Session, limit: int) -> tuple[list[dict], int]:
    """库存低于安全库存（口径与 `dashboard._stock_alerts` 一致）。"""
    query = (db.query(Stock)
             .join(Product, Stock.product_id == Product.id)
             .filter(Product.safety_stock.isnot(None),
                     Stock.qty < Product.safety_stock,
                     Product.status == "enabled"))
    total = int(query.count() or 0)
    rows = query.order_by((Product.safety_stock - Stock.qty).desc()).limit(limit).all()
    return ([{"product_name": s.product.name if s.product else "",
              "warehouse_name": s.warehouse.name if s.warehouse else "",
              "qty": float(s.qty or 0),
              "safety_stock": float(s.product.safety_stock or 0) if s.product else 0.0}
             for s in rows], total)


def todo_rows(db: Session, user: User, perms: set[str], limit: int) -> list[dict]:
    """按用户列出"待我审核"的单据（口径与 `dashboard._todos` 一致）。"""
    out: list[dict] = []
    for kind, model in DOC_MODELS.items():
        perm = DOC_APPROVE_PERM.get(kind)
        if perm is None:
            continue
        if not user.is_superadmin and perm not in perms:
            continue
        query = apply_data_scope(
            db.query(model).filter(model.status == "submitted"), model, user, db)
        for doc in query.order_by(model.id.desc()).limit(limit).all():
            out.append({
                "kind": kind,
                "label": getattr(model, "label", kind),
                "id": doc.id,
                "doc_no": doc.doc_no,
                "party": (getattr(doc, "supplier_name", None)
                          or getattr(doc, "customer_name", None) or ""),
                "amount": float(getattr(doc, "total_amount", 0) or 0),
            })
    return out


def build_markdown(*, today: date, todos: list[dict], todos_total: int,
                   warranty: list[dict], warranty_total: int,
                   stock: list[dict], stock_total: int) -> tuple[str, int]:
    """组装摘要 markdown；返回 `(markdown, 条目总数)`（总数为 0 时不发）。"""
    lines = [f"**CTMS 每日提醒 · {today.isoformat()}**"]
    count = 0

    if todos:
        lines.append(f"\n**待我审核：{todos_total} 张**")
        for t in todos:
            lines.append(f"- {t['label']} {t['doc_no']}（{t['party'] or '—'} / {t['amount']:,.2f}）")
        if todos_total > len(todos):
            lines.append(f"- …等共 {todos_total} 张")
        count += todos_total

    if warranty:
        lines.append(f"\n**质保即将到期：{warranty_total} 项**")
        for w in warranty:
            lines.append(f"- {w['contract_no']} {w['name']}｜到期 {w['warranty_end']}"
                         f"（剩 {w['days_left']} 天）")
        if warranty_total > len(warranty):
            lines.append(f"- …等共 {warranty_total} 项")
        count += warranty_total

    if stock:
        lines.append(f"\n**库存预警：{stock_total} 项**")
        for s in stock:
            lines.append(f"- {s['warehouse_name']} / {s['product_name']}："
                         f"现有 {s['qty']:g}，安全库存 {s['safety_stock']:g}")
        if stock_total > len(stock):
            lines.append(f"- …等共 {stock_total} 项")
        count += stock_total

    return "\n".join(lines), count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CTMS 每日飞书提醒（待办/质保/库存）")
    parser.add_argument("--kinds", default="todo,warranty,stock",
                        help="要包含的内容，逗号分隔（todo,warranty,stock）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印将要发送的内容，不写库、不发消息")
    parser.add_argument("--limit", type=int, default=card_mod.DIGEST_MAX_ITEMS,
                        help="每类最多列几条")
    args = parser.parse_args(argv)

    kinds = {k.strip() for k in (args.kinds or "").split(",") if k.strip()}
    if not config.feishu_ready() and not args.dry_run:
        print("[feishu_digest] 飞书接入未启用（需 CTMS_FEISHU_ENABLED=1 且配置齐全），跳过")
        return 0

    today = date.today()
    queued = 0
    considered = 0
    with SessionLocal() as db:
        params = get_sys_params(db)
        window = int(params.get("warranty_window_days") or 30)
        warranty, warranty_total = (warranty_rows(db, window, args.limit)
                                    if "warranty" in kinds else ([], 0))
        stock, stock_total = (stock_rows(db, args.limit) if "stock" in kinds else ([], 0))

        for user in db.query(User).filter(User.status == "enabled").all():
            if identity_service.bound_open_id(db, user.id) is None:
                continue          # 未绑定飞书：跳过（管理页可见"未绑定人数"）
            considered += 1
            perms = collect_perms(db, user)
            todos = todo_rows(db, user, perms, args.limit) if "todo" in kinds else []
            markdown, count = build_markdown(
                today=today, todos=todos, todos_total=len(todos),
                warranty=warranty, warranty_total=warranty_total,
                stock=stock, stock_total=stock_total)
            if count == 0:
                continue          # 没有内容就不打扰
            if args.dry_run:
                print(f"--- {user.username}（{user.real_name}）---")
                print(markdown)
                print()
                continue
            card_obj, _ = card_mod.build_digest_card(
                title=f"CTMS 每日提醒 {today.isoformat()}", markdown=markdown)
            if notify_service.enqueue(db, event_key=f"digest:{today.isoformat()}:u{user.id}",
                                      category="todo", recipient_user_id=user.id,
                                      card_obj=card_obj) is not None:
                queued += 1
        if not args.dry_run:
            db.commit()

    if args.dry_run:
        print(f"[feishu_digest] dry-run：已绑定飞书账号 {considered} 个（未写库）")
    else:
        print(f"[feishu_digest] 入队 {queued} 条摘要（已绑定账号 {considered} 个）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
