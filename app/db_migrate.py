"""轻量增量迁移（SQLite 原型期使用；正式版切 Alembic 后由迁移管理）。

当前：为已存在的表补充新列（幂等）。
"""
from sqlalchemy import inspect, text

from .database import engine

_ADD_COLUMNS = [
    ("contract_tag", "auto", "INTEGER NOT NULL DEFAULT 0"),
    ("contracts", "subject_code", "VARCHAR(8)"),
]


def ensure_schema_upgrades() -> None:
    insp = inspect(engine)
    for table, col, ddl in _ADD_COLUMNS:
        if table not in insp.get_table_names():
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if col not in cols:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
