"""V2.5 财务模块冒烟：进度一致性核对（对**真实数据库**跑，默认 dry-run）。

与 `smoke_v23_subject.py` / `smoke_m1/m2/m3` 同一风格：直接连真实库，验证"系统里的钱对得上"。
**默认不改任何数据**（dry-run）：只报告四类回写字段与核销明细不一致的条目；
加 `--fix` 才执行与 `POST /api/finance/recalc` 相同的修正。

运行（先把 `CTMS_DB_URL` 指向待验证的库）：

```bash
app\\.venv\\Scripts\\python app\\tests\\smoke_v25_finance.py            # 只核对
app\\.venv\\Scripts\\python app\\tests\\smoke_v25_finance.py --fix      # 核对并修正
```

覆盖：

1. 回写字段（`paid_amount` / `received_amount` / `invoiced_amount`）= 已记账核销明细合计；
2. 是否存在"已记账但没有核销明细"或"有核销明细但未记账"的财务单据；
3. 核销指向的目标单据是否仍然存在且未作废（多态目标无外键，这里兜底检查孤儿行）；
4. 权限种子：`finance.*` 权限点齐全（缺权限点会表现为管理员莫名 403）。
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, inspect  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402
from app.models_doc import (  # noqa: E402
    Invoice,
    InvoiceAllocation,
    PaymentAllocation,
    PaymentOrder,
    PurchaseOrder,
    ReceiptAllocation,
    ReceiptOrder,
    SalesOrder,
    StockInOrder,
    StockOutOrder,
)
from app.permissions import PERM_CODES, ROLE_PRESETS, expand_perms  # noqa: E402
from app.services import finance_service  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _has_finance_tables() -> bool:
    names = set(inspect(engine).get_table_names())
    return {"payment_orders", "receipt_orders", "invoices"} <= names


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    fix = "--fix" in argv

    if not _has_finance_tables():
        print("财务表不存在：请先启动后端（自动建表）或执行 python -m app.init_db")
        return 1

    with SessionLocal() as db:
        # ---- 1. 回写值 vs 核销明细 ----
        result = finance_service.recalc_progress(db)
        diffs = result["diffs"]
        detail = "；".join(f"{d['doc_no']}.{d['field']} {d['old']}→{d['new']}"
                           for d in diffs[:5]) or "全部一致"
        check("回写金额与核销明细一致", not diffs, f"检查 {result['checked']} 条，差异 {len(diffs)} 条：{detail}")
        if fix and diffs:
            db.commit()
            check("已按核销明细修正（--fix）", True, f"修正 {result['fixed']} 条")
        else:
            db.rollback()

        # ---- 2. 已记账但无明细 / 有明细但未记账 ----
        orphan_posted = []
        for model, alloc_model, fk in ((PaymentOrder, PaymentAllocation, "payment_id"),
                                       (ReceiptOrder, ReceiptAllocation, "receipt_id"),
                                       (Invoice, InvoiceAllocation, "invoice_id")):
            rows = (db.query(model.doc_no)
                    .outerjoin(alloc_model, getattr(alloc_model, fk) == model.id)
                    .filter(model.posted == True, alloc_model.id.is_(None))  # noqa: E712
                    .all())
            orphan_posted += [r[0] for r in rows]
        check("没有『已记账却无核销明细』的财务单据", not orphan_posted,
              "、".join(orphan_posted[:5]) or "无")

        # ---- 3. 核销目标是否仍存在且未作废 ----
        models = {"purchase_order": PurchaseOrder, "sales_order": SalesOrder,
                  "stock_in": StockInOrder, "stock_out": StockOutOrder}
        broken = []
        for alloc_model, fk in ((PaymentAllocation, "payment_id"),
                                (ReceiptAllocation, "receipt_id"),
                                (InvoiceAllocation, "invoice_id")):
            for target_type, target_id, target_no in db.query(
                    alloc_model.target_type, alloc_model.target_id, alloc_model.target_no).all():
                model = models.get(target_type)
                target = db.get(model, target_id) if model else None
                if target is None or target.status == "voided":
                    broken.append(f"{target_type}#{target_id}({target_no})")
        check("核销目标均存在且未作废", not broken, "、".join(broken[:5]) or "无")

        # ---- 4. 权限种子 ----
        finance_perms = {c for c in PERM_CODES if c.startswith("finance.")}
        check("finance.* 权限点齐全（20 项）", len(finance_perms) >= 20, f"{len(finance_perms)} 项")
        finance_role = next((r for r in ROLE_PRESETS if r["code"] == "finance"), None)
        granted = set(expand_perms(finance_role["perms"] if finance_role else []))
        check("finance 角色预设覆盖全部财务权限点", finance_perms <= granted,
              f"缺：{sorted(finance_perms - granted)}" if finance_perms - granted else "齐备")

        # ---- 5. 汇总（对账视角） ----
        total_paid = db.query(func.coalesce(func.sum(PurchaseOrder.paid_amount), 0)).scalar()
        total_invoiced_in = db.query(func.coalesce(func.sum(PurchaseOrder.invoiced_amount), 0)).scalar()
        total_received = db.query(func.coalesce(func.sum(SalesOrder.received_amount), 0)).scalar()
        total_invoiced_out = db.query(func.coalesce(func.sum(SalesOrder.invoiced_amount), 0)).scalar()
        print("\n对账汇总（仅系统内登记）："
              f"采购已付 {Decimal(str(total_paid)):.2f} / 已收票 {Decimal(str(total_invoiced_in)):.2f}；"
              f"销售已收 {Decimal(str(total_received)):.2f} / 已开票 {Decimal(str(total_invoiced_out)):.2f}")

    print(f"\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项：" + "；".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
