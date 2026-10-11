"""存量数据回填：仓库所属公司 / 单据签约公司 / 调拨调出调入单位（V2.3 / N1、N2、N4）。

背景：V2.3 引入公司维度后，**存量仓库与单据的这几个字段都是空值**：
- 仓库没有所属公司 → 单据与库存里的仓库只显示纯仓库名（拿不到 `ZC-主仓` 效果）；
- 单据没有签约公司 → 编辑时必填校验会拦住保存，下推也会被明确拒绝。

本脚本按"**只填空值、不覆盖已有值**"的原则回填（幂等，可重复执行）：

- 仓库：`--warehouse-subject`（缺省取系统设置里第一个我方公司，如 ZC）；
- 单据：`--doc-subject`（缺省同仓库）——入库/出库单优先按**表头仓库所属公司**推断，
  其余单据用缺省主体；
- 调拨单：调出/调入单位按两端仓库所属公司推断（仓库已回填，故顺序必须是"先仓库后单据"）。

用法：

```bash
# 预览（不写库）
app\\.venv\\Scripts\\python -m app.tools.backfill_subject_v23 --dry-run

# 用 PostgreSQL 执行（推荐先备份）
set CTMS_DB_URL=postgresql+psycopg2://postgres:good789good@192.168.31.27:5444/ctms
app\\.venv\\Scripts\\python -m app.tools.backfill_subject_v23
```
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.dicts import get_subjects, subject_name_of  # noqa: E402
from app.models_doc import (  # noqa: E402
    PurchaseOrder,
    PurchaseRequest,
    SalesOrder,
    SalesRequest,
    StockInOrder,
    StockOutOrder,
    StockTransfer,
)
from app.models_master import Warehouse  # noqa: E402

DOC_MODELS = [PurchaseRequest, PurchaseOrder, SalesRequest, SalesOrder,
              StockInOrder, StockOutOrder]


def _default_subject(db, explicit: str | None) -> str:
    if explicit:
        return explicit.strip().upper()
    subs = get_subjects(db)
    if not subs:
        raise SystemExit("系统设置里没有任何我方公司（主体码），请先在「系统设置 → 我方公司」维护")
    return subs[0]["code"]


def backfill(db, *, warehouse_subject: str | None, doc_subject: str | None,
             dry_run: bool) -> dict:
    stats: dict[str, int] = {}
    default_code = _default_subject(db, doc_subject)
    wh_code = (warehouse_subject or default_code).strip().upper()
    if subject_name_of(db, wh_code) is None:
        raise SystemExit(f"主体码 {wh_code} 不在系统设置的我方公司字典中")

    # 1) 仓库所属公司
    n = 0
    for wh in db.query(Warehouse).filter(Warehouse.subject_code.is_(None)).all():
        if not dry_run:
            wh.subject_code = wh_code
        n += 1
    stats["warehouses"] = n

    # 2) 入库/出库单：优先按表头仓库所属公司（仓库已在本函数第 1 步回填）
    wh_subject = {w.id: w.subject_code for w in db.query(Warehouse).all()}
    for model in (StockInOrder, StockOutOrder):
        m = 0
        for doc in db.query(model).filter(model.subject_code.is_(None)).all():
            code = wh_subject.get(doc.warehouse_id) or default_code
            if not dry_run:
                doc.subject_code = code
                doc.subject_name = subject_name_of(db, code)
            m += 1
        stats[model.__tablename__] = m

    # 3) 其余单据：用缺省主体
    for model in (PurchaseRequest, PurchaseOrder, SalesRequest, SalesOrder):
        m = 0
        for doc in db.query(model).filter(model.subject_code.is_(None)).all():
            if not dry_run:
                doc.subject_code = default_code
                doc.subject_name = subject_name_of(db, default_code)
            m += 1
        stats[model.__tablename__] = m

    # 4) 调拨单：调出/调入单位按两端仓库所属公司推断
    m = 0
    for doc in db.query(StockTransfer).all():
        changed = False
        for side in ("from", "to"):
            code = wh_subject.get(getattr(doc, f"{side}_warehouse_id"))
            if not code:
                continue
            if getattr(doc, f"{side}_subject_code") is None:
                if not dry_run:
                    setattr(doc, f"{side}_subject_code", code)
                    setattr(doc, f"{side}_subject_name", subject_name_of(db, code))
                changed = True
        m += 1 if changed else 0
    stats["stock_transfers"] = m

    if not dry_run:
        db.commit()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="V2.3 公司维度存量回填")
    parser.add_argument("--warehouse-subject", default=None, help="仓库所属公司主体码（缺省取第一个）")
    parser.add_argument("--doc-subject", default=None, help="单据签约公司主体码（缺省取第一个）")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()

    with SessionLocal() as db:
        stats = backfill(db, warehouse_subject=args.warehouse_subject,
                         doc_subject=args.doc_subject, dry_run=args.dry_run)
    label = "待回填" if args.dry_run else "已回填"
    for table, n in stats.items():
        print(f"  {label} {table:24} {n} 行")
    print("完成" + "（dry-run，未写库）" if args.dry_run else "完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
