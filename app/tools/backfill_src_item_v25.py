"""V2.5 数据修复：找回被编辑丢掉的 `src_item_id`，并重算"已入库/已出库数量"。

## 为什么需要它（现场缺陷）

从采购单/销售订单**下推**生成的入库/出库单，行项带 `src_item_id`（指向来源单据行）。
过账时 `push_service.backfill_received_qty` / `backfill_shipped_qty` 按 `src_item_id`
把数量回写到来源行 `received_qty` / `shipped_qty`。

但"下推生成的单据若在草稿状态被**编辑保存**过"，`doc_service.apply_items` 会整表重建行项，
而前端 payload 不含 `src_item_id` → 来源行 id 丢失 → 回写**静默跳过**：
- 来源单据的 `received_qty` 一直是 0（**收货进度不更新**）；
- `remaining_qty = qty - received_qty` 一直是全量（**已入库的采购单还能继续下推**）。

实测受影响单据：`IN202610000005`（采购单 `PO202609000029`，3 张已过账入库单但回写为 0）。

根因（`apply_items` 保留来源行）已修复；本脚本修复**已产生的存量数据**：

1. 对 `source_doc_type=purchase_order/sales_order` 且未作废的入库/出库单，
   按物料把缺失的 `src_item_id` 回填到来源单据的对应行（同物料按顺序一一对应）；
2. 按**已过账**的下游单据行重算来源行的 `received_qty` / `shipped_qty`（覆盖式，幂等）；
3. 不修改任何单据数量、金额、状态与库存（只补来源标记与数量回写）。

用法：

```bash
app\\.venv\\Scripts\\python app\\tests\\..\\tools\\backfill_src_item_v25.py            # 只报告（dry-run）
app\\.venv\\Scripts\\python app\\tools\\backfill_src_item_v25.py --fix                # 执行修复
```
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 必须导入全部模型模块：否则 flush 时 SQLAlchemy 解析不到 `products` 等被引用的表
# （实测 `--fix` 提交时报 NoReferencedTableError；dry-run 因不提交而不暴露）
import app.models_auth  # noqa: E402,F401
import app.models_doc  # noqa: E402,F401
import app.models_master  # noqa: E402,F401
import app.models_notify  # noqa: E402,F401
import app.models_stock  # noqa: E402,F401
from app.database import SessionLocal  # noqa: E402
from app.models_doc import (  # noqa: E402
    PurchaseOrder,
    SalesOrder,
    StockInOrder,
    StockOutOrder,
)

ZERO = Decimal("0")

# (下游模型, 来源模型, 下游数量回写字段)
_LINKS = [
    (StockInOrder, PurchaseOrder, "received_qty"),
    (StockOutOrder, SalesOrder, "shipped_qty"),
]


def _fix_source_items(db, down_model, up_model) -> tuple[int, int]:
    """回填缺失的 `src_item_id`（按物料顺序匹配）；返回（检查数, 修正数）。"""
    checked = fixed = 0
    docs = (db.query(down_model)
            .filter(down_model.source_doc_type == up_model.doc_type,
                    down_model.source_doc_id.isnot(None),
                    down_model.status != "voided").all())
    for doc in docs:
        up = db.get(up_model, doc.source_doc_id)
        if up is None:
            continue
        # 同物料可对应多行：按顺序取用，避免"两行同物料都指向同一来源行"
        pool: dict[int, list] = {}
        for up_item in (up.items or []):
            pool.setdefault(up_item.product_id, []).append(up_item)
        for line in (doc.items or []):
            checked += 1
            if line.src_item_id:
                continue
            candidates = pool.get(line.product_id) or []
            if not candidates:
                continue
            line.src_item_id = candidates.pop(0).id
            fixed += 1
    return checked, fixed


def _recalc_qty(db, down_model, up_model, field: str) -> tuple[int, int]:
    """按**已过账**下游行重算来源行数量（覆盖式，幂等）。"""
    sums: dict[int, Decimal] = {}
    rows = (db.query(down_model)
            .filter(down_model.source_doc_type == up_model.doc_type,
                    down_model.source_doc_id.isnot(None),
                    down_model.status != "voided",
                    down_model.posted == True).all())  # noqa: E712
    for doc in rows:
        for line in (doc.items or []):
            if line.src_item_id:
                sums[line.src_item_id] = sums.get(line.src_item_id, ZERO) + (line.qty or ZERO)
    changed = 0
    for up in db.query(up_model).all():
        for item in (up.items or []):
            want = sums.get(item.id, ZERO)
            if (item.qty or ZERO) > ZERO and want > (item.qty or ZERO):
                want = item.qty or ZERO          # 防御：回写不应超过订单数量
            if (getattr(item, field) or ZERO) != want:
                if not fix_mode:
                    print(f"  待修正 {up.doc_no} 行{item.seq}: {field} "
                          f"{float(getattr(item, field) or 0)} → {float(want)}")
                setattr(item, field, want)
                changed += 1
    return len(sums), changed


fix_mode = False


def main(argv: list[str] | None = None) -> int:
    global fix_mode
    argv = list(argv or sys.argv[1:])
    fix_mode = "--fix" in argv

    with SessionLocal() as db:
        print(f"模式：{'修正（--fix）' if fix_mode else '只报告（dry-run）'}")
        for down_model, up_model, field in _LINKS:
            label = f"{down_model.label} → {up_model.label}"
            checked, fixed = _fix_source_items(db, down_model, up_model)
            print(f"\n[{label}] 行项检查 {checked}，回填 src_item_id {fixed}")
            _, changed = _recalc_qty(db, down_model, up_model, field)
            print(f"[{label}] {field} 待修正 {changed} 行")
        if fix_mode:
            db.commit()
            print("\n已提交修正。")
        else:
            db.rollback()
            print("\n（dry-run，未改动任何数据；加 --fix 执行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
