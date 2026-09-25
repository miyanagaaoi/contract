"""轻量增量迁移（SQLite；V2.0 起含权限、主数据与单据所需的新增列）。

幂等：仅对**已存在**的表补列/补索引，重复执行安全。

注意（SQLite 限制）：`ALTER TABLE ADD COLUMN` 不能加外键约束，也不能加"无默认值的 NOT NULL"列，
因此新列一律**可空且无外键**，外键关系由应用层保证——与 V1.0 的 `subject_code` 处理一致
（见 `12-erp-system-design.md` §4.5）。
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from .database import engine

_ADD_COLUMNS: list[tuple[str, str, str]] = [
    # ---- V1.0 ----
    ("contract_tag", "auto", "INTEGER NOT NULL DEFAULT 0"),
    ("contracts", "subject_code", "VARCHAR(8)"),
    # ---- V2.0：合同档案化与审计 ----
    ("contracts", "customer_id", "INTEGER"),
    ("contracts", "supplier_id", "INTEGER"),
    ("contracts", "org_id", "INTEGER"),
    ("contracts", "created_by", "INTEGER"),
    ("change_logs", "operator_id", "INTEGER"),
    ("change_logs", "operator_name", "VARCHAR(64)"),
    ("change_logs", "object_type", "VARCHAR(32)"),
    ("change_logs", "object_id", "INTEGER"),
    ("attachments", "object_type", "VARCHAR(32)"),
    ("attachments", "object_id", "INTEGER"),
]

_ADD_INDEXES: list[tuple[str, str, str]] = [
    ("ix_contracts_customer_id", "contracts", "customer_id"),
    ("ix_contracts_supplier_id", "contracts", "supplier_id"),
    ("ix_contracts_org_id", "contracts", "org_id"),
    ("ix_contracts_created_by", "contracts", "created_by"),
    ("ix_change_logs_object", "change_logs", "object_type, object_id"),
]


def _table_names(insp) -> set[str]:
    return set(insp.get_table_names())


def _add_columns(insp) -> int:
    tables = _table_names(insp)
    added = 0
    for table, col, ddl in _ADD_COLUMNS:
        if table not in tables:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if col in cols:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        added += 1
    return added


def _add_indexes(insp) -> int:
    tables = _table_names(insp)
    existing: set[str] = set()
    for t in tables:
        try:
            existing |= {i["name"] for i in insp.get_indexes(t)}
        except Exception:  # pragma: no cover - 视图等特殊对象
            continue
    created = 0
    for name, table, cols in _ADD_INDEXES:
        if table not in tables or name in existing:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))
        created += 1
    return created


def _backfill_changelog() -> None:
    """历史变更记录补齐对象标识：object_type='contract'、object_id=contract_id。

    仅填补空值，不覆盖已有数据（幂等）。
    """
    insp = inspect(engine)
    if "change_logs" not in _table_names(insp):
        return
    cols = {c["name"] for c in insp.get_columns("change_logs")}
    if "object_id" not in cols or "object_type" not in cols:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE change_logs SET object_type = 'contract', object_id = contract_id "
            "WHERE object_type IS NULL AND contract_id IS NOT NULL"
        ))


def _relax_change_logs() -> bool:
    """把 `change_logs.contract_id` 由 NOT NULL 改为可空（M2 单据变更历史需要）。

    SQLite 不支持 `ALTER COLUMN`，故采用"改名 → 按当前模型建新表 → 拷数据 → 删旧表"，
    历史数据完整保留；已是可空结构时直接跳过（幂等）。
    """
    insp = inspect(engine)
    if "change_logs" not in _table_names(insp):
        return False
    cols = {c["name"]: c for c in insp.get_columns("change_logs")}
    contract_col = cols.get("contract_id")
    if contract_col is None or contract_col.get("nullable"):
        return False

    from .models import ChangeLog

    legacy = "change_logs_legacy"
    # SQLite 重命名表**不会**重命名其索引（索引名全局唯一），故先释放旧索引名，
    # 否则按新模型建表时 CREATE INDEX 会因同名索引已存在而失败。
    index_names = [i["name"] for i in insp.get_indexes("change_logs") if i.get("name")]
    with engine.begin() as conn:
        for name in index_names:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        conn.execute(text(f"DROP TABLE IF EXISTS {legacy}"))
        conn.execute(text(f"ALTER TABLE change_logs RENAME TO {legacy}"))
        ChangeLog.__table__.create(conn)
        common = [c.name for c in ChangeLog.__table__.columns if c.name in cols]
        columns = ", ".join(common)
        conn.execute(text(f"INSERT INTO change_logs ({columns}) SELECT {columns} FROM {legacy}"))
        conn.execute(text(f"DROP TABLE {legacy}"))
    return True


def ensure_schema_upgrades() -> dict:
    """执行全部增量升级，返回本次实际变更统计（便于日志观察）。

    顺序说明：`change_logs` 重建会丢掉该表的索引，故先重建、再补列与索引（`insp` 需重新采集）。
    """
    result = {"change_logs_rebuilt": _relax_change_logs()}
    insp = inspect(engine)
    result["columns_added"] = _add_columns(insp)
    result["indexes_created"] = _add_indexes(insp)
    _backfill_changelog()
    return result
