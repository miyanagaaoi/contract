"""重建库存结存金额列（CR-032 / TODO-011）。

背景：`stocks.stock_value`（当前库存总额度）由过账增量维护；对**历史数据/迁移后的库**，
该列初始为 0，需要用本工具按流水重算一次。

算法：复用 `stock_report_service.stock_value_map`（FIFO 回放，与批次配对报表同源），
对每个 `(仓库, 物料)` 取「未消耗批次剩余金额合计」，写回 `stocks.stock_value`。

用法（项目根目录）：
    python -m app.tools.rebuild_stock_value --dry-run   # 只看差异
    python -m app.tools.rebuild_stock_value             # 写回
"""
from __future__ import annotations

import sys
from decimal import Decimal

from app.database import SessionLocal
from app.models_master import Product, Warehouse  # noqa: F401  （注册关系）
from app.models_stock import Stock
from app.services.stock_report_service import stock_value_map


def rebuild(dry_run: bool = False) -> dict:
    with SessionLocal() as db:
        values = stock_value_map(db)
        changed, total = 0, Decimal("0")
        rows = db.query(Stock).all()
        for s in rows:
            expect = values.get((s.warehouse_id, s.product_id), Decimal("0"))
            old = Decimal(str(s.stock_value or 0))
            if old != expect:
                changed += 1
                if dry_run:
                    print(f"  [diff] 物料#{s.product_id} 仓库#{s.warehouse_id}: "
                          f"{old} -> {expect}")
                else:
                    s.stock_value = expect
            total += expect
        if not dry_run:
            db.commit()
        return {"rows": len(rows), "changed": changed, "total_value": float(total),
                "dry_run": dry_run}


if __name__ == "__main__":
    result = rebuild(dry_run="--dry-run" in sys.argv)
    print("重建完成:", result)
