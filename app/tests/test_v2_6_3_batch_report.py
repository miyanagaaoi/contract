"""V2.6.1 CR-011 回归：库存批次配对报表（入出 FIFO）口径。

用 `app.tools.seed_stock_demo` 造一套真实过账的演示数据（入库 3+1 批、出库 4 单），
锁定三条口径：
1. 一个入库批次被多次出库消耗 → 拆成多行，出库行**不重复记剩余**；
2. 未消耗（含部分剩余）批次单独一行，剩余数量/金额 = 当前结存；
3. 报表剩余合计 == 库存结存（A 60@14 + B 10@20）。
"""
from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.services import stock_report_service as svc
from app.tools import seed_stock_demo


@pytest.fixture(autouse=True)
def _clean_demo_data():
    """演示数据必须自清理：测试库是共享的，残留会影响其它库存用例。"""
    yield
    seed_stock_demo.purge()


def test_batch_pairing_rows_and_totals():
    seed_stock_demo.seed()
    with SessionLocal() as db:
        rows = svc.build_batches(db, keyword=seed_stock_demo.PREFIX)

    assert len(rows) == 7, [r["in_no"] + "/" + (r["out_no"] or "-") for r in rows]

    # A 批次1：一次性出完（100），只有出库行、无剩余
    a1 = [r for r in rows if r["in_no"].endswith("IN-A1")]
    assert len(a1) == 1 and a1[0]["out_qty"] == 100.0 and a1[0]["stock_qty"] is None

    # A 批次2：被 3 张出库单消耗（20+50+10），无剩余行
    a2 = [r for r in rows if r["in_no"].endswith("IN-A2")]
    assert [r["out_qty"] for r in a2] == [20.0, 50.0, 10.0]
    assert all(r["stock_qty"] is None for r in a2)

    # A 批次3 与 B 批次1：未消耗/部分剩余行，且剩余只出现一次
    leftovers = [r for r in rows if r["stock_qty"]]
    assert len(leftovers) == 2
    assert sum(r["stock_qty"] for r in leftovers) == 70.0          # 60 + 10
    assert sum(r["stock_amount"] for r in leftovers) == 1040.0     # 60*14 + 10*20

    # 出库类型/项目/领用方映射
    b_row = [r for r in rows if r["out_no"].endswith("OUT-B1")][0]
    assert b_row["out_type"] == "领用出库"
    assert b_row["out_project"] == "演示项目-领用"
    assert b_row["issue_party"] == "演示领用人"


def test_batch_report_matches_stock_balances():
    """报表剩余合计必须等于库存结存（同一仓库/物料）。"""
    seed_stock_demo.seed()
    from app.database import SessionLocal as SL
    from app.models_stock import Stock
    from sqlalchemy import func

    with SL() as db:
        rows = svc.build_batches(db, keyword=seed_stock_demo.PREFIX)
        by_key = {}
        for r in rows:
            if r["stock_qty"]:
                by_key[(r["product_code"])] = by_key.get(r["product_code"], 0) + r["stock_qty"]
        for code, expect in (("DEMO26-A", 60.0), ("DEMO26-B", 10.0)):
            actual = (db.query(func.coalesce(func.sum(Stock.qty), 0))
                      .filter(Stock.product.has(code=code)).scalar())
            assert float(actual) == by_key.get(code, 0.0) == expect, (code, actual)
