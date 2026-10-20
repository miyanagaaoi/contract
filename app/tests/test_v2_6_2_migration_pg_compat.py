"""V2.6.2：增量迁移 DDL 的跨库兼容性检查（SQLite / PostgreSQL 双跑）。

背景（真实故障，2026-10-20）：`is_red` 的迁移 DDL 写成
`BOOLEAN NOT NULL DEFAULT 0`——SQLite 接受整数默认值，PostgreSQL 直接报
`DatatypeMismatch: column "is_red" is of type boolean but default expression is of type integer`，
导致群晖/生产容器**启动即失败**。测试库是 SQLite，跑不出来，因此这里做静态规则检查。

规则：
1. `BOOLEAN` 列的 `DEFAULT` 只能是 `TRUE/FALSE/0/1`——其中 `0/1` 在 PG 上不安全，
   因此统一要求 `TRUE/FALSE`；
2. 新增列不允许出现 `AUTOINCREMENT`（PG 无此关键字）；
3. `DATETIME` 统一写 `TIMESTAMP`（PG 无 DATETIME 类型）。
"""
from __future__ import annotations

import re

from app.db_migrate import _ADD_COLUMNS


def test_boolean_defaults_are_pg_compatible():
    bad = []
    for table, col, ddl in _ADD_COLUMNS:
        if re.search(r"\bBOOLEAN\b", ddl, re.I) and re.search(r"DEFAULT\s+0\b|DEFAULT\s+1\b", ddl):
            bad.append(f"{table}.{col}: {ddl}")
    assert not bad, "BOOLEAN 默认值必须写 TRUE/FALSE（PG 不接受 0/1）：\n" + "\n".join(bad)


def test_no_autoincrement_and_no_datetime_type():
    bad = []
    for table, col, ddl in _ADD_COLUMNS:
        upper = ddl.upper()
        if "AUTOINCREMENT" in upper:
            bad.append(f"{table}.{col}: {ddl}")
        if re.search(r"\bDATETIME\b", upper):
            bad.append(f"{table}.{col}: {ddl}（请用 TIMESTAMP）")
    assert not bad, "跨库不兼容的 DDL：\n" + "\n".join(bad)


def test_column_names_and_tables_unique():
    """同一 (表, 列) 不能重复登记（重复会导致 PG 上重复 ALTER 或迁移歧义）。"""
    seen: set[tuple[str, str]] = set()
    dup = []
    for table, col, _ddl in _ADD_COLUMNS:
        key = (table, col)
        if key in seen:
            dup.append(f"{table}.{col}")
        seen.add(key)
    assert not dup, "重复的迁移列：" + ", ".join(dup)
