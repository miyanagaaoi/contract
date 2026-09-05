"""轻量增量迁移（SQLite 原型期使用；正式版切 Alembic 后由迁移管理）。

当前：为已存在的 contract_tag 表补充 auto 列（旧库升级，幂等）。
"""
from sqlalchemy import inspect, text

from .database import engine


def ensure_schema_upgrades() -> None:
    insp = inspect(engine)
    if "contract_tag" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("contract_tag")}
    if "auto" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE contract_tag ADD COLUMN auto INTEGER NOT NULL DEFAULT 0"))
