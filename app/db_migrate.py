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
    # ---- V2.1：合同行项绑定系统物料档案（N4；约束在应用层，见 models.ContractItem） ----
    ("contract_items", "product_id", "INTEGER"),
    ("contract_items", "product_code", "VARCHAR(32)"),
    ("contract_items", "product_name", "VARCHAR(128)"),
    # ---- V2.1：经办人姓名快照（N1；配合既有 handler_user_id，账号停用后仍可显示） ----
    ("purchase_requests", "handler_name", "VARCHAR(64)"),
    ("purchase_orders", "handler_name", "VARCHAR(64)"),
    ("sales_requests", "handler_name", "VARCHAR(64)"),
    ("sales_orders", "handler_name", "VARCHAR(64)"),
    ("stock_in_orders", "handler_name", "VARCHAR(64)"),
    ("stock_out_orders", "handler_name", "VARCHAR(64)"),
    ("stock_takes", "handler_name", "VARCHAR(64)"),
    # ---- V2.3：仓库所属公司 / 单据签约公司 / 调拨调出·调入单位（subject_code 取值见 dicts.get_subjects）----
    ("warehouses", "subject_code", "VARCHAR(8)"),
    ("purchase_requests", "subject_code", "VARCHAR(8)"),
    ("purchase_requests", "subject_name", "VARCHAR(64)"),
    ("purchase_orders", "subject_code", "VARCHAR(8)"),
    ("purchase_orders", "subject_name", "VARCHAR(64)"),
    ("sales_requests", "subject_code", "VARCHAR(8)"),
    ("sales_requests", "subject_name", "VARCHAR(64)"),
    ("sales_orders", "subject_code", "VARCHAR(8)"),
    ("sales_orders", "subject_name", "VARCHAR(64)"),
    ("stock_in_orders", "subject_code", "VARCHAR(8)"),
    ("stock_in_orders", "subject_name", "VARCHAR(64)"),
    ("stock_out_orders", "subject_code", "VARCHAR(8)"),
    ("stock_out_orders", "subject_name", "VARCHAR(64)"),
    ("stock_takes", "subject_code", "VARCHAR(8)"),
    ("stock_takes", "subject_name", "VARCHAR(64)"),
    ("stock_transfers", "subject_code", "VARCHAR(8)"),
    ("stock_transfers", "subject_name", "VARCHAR(64)"),
    ("stock_transfers", "from_subject_code", "VARCHAR(8)"),
    ("stock_transfers", "from_subject_name", "VARCHAR(64)"),
    ("stock_transfers", "to_subject_code", "VARCHAR(8)"),
    ("stock_transfers", "to_subject_name", "VARCHAR(64)"),
    # ---- V2.5：财务回写字段（审核付款单/收款单/发票时回写，红冲时回退；见 finance_service） ----
    # 新表（payment_orders / receipt_orders / invoices 及三张核销表）由 create_all 直接建，
    # 这里只补既有单据表上的回写列；NOT NULL + 常量默认值在 SQLite 与 PG 上均可直接 ADD COLUMN。
    ("purchase_orders", "paid_amount", "NUMERIC(16,2) NOT NULL DEFAULT 0"),
    ("purchase_orders", "invoiced_amount", "NUMERIC(16,2) NOT NULL DEFAULT 0"),
    ("sales_orders", "received_amount", "NUMERIC(16,2) NOT NULL DEFAULT 0"),
    ("sales_orders", "invoiced_amount", "NUMERIC(16,2) NOT NULL DEFAULT 0"),
]

_ADD_INDEXES: list[tuple[str, str, str]] = [
    ("ix_contracts_customer_id", "contracts", "customer_id"),
    ("ix_contracts_supplier_id", "contracts", "supplier_id"),
    ("ix_contracts_org_id", "contracts", "org_id"),
    ("ix_contracts_created_by", "contracts", "created_by"),
    ("ix_change_logs_object", "change_logs", "object_type, object_id"),
    ("ix_contract_items_product_id", "contract_items", "product_id"),
    # V2.3：按公司筛选（仓库归属 / 单据签约公司 / 库存结存按仓库公司）
    ("ix_warehouses_subject_code", "warehouses", "subject_code"),
    ("ix_purchase_requests_subject_code", "purchase_requests", "subject_code"),
    ("ix_purchase_orders_subject_code", "purchase_orders", "subject_code"),
    ("ix_sales_requests_subject_code", "sales_requests", "subject_code"),
    ("ix_sales_orders_subject_code", "sales_orders", "subject_code"),
    ("ix_stock_in_orders_subject_code", "stock_in_orders", "subject_code"),
    ("ix_stock_out_orders_subject_code", "stock_out_orders", "subject_code"),
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


def _relax_nullable_column(table: str, column: str, model) -> bool:
    """把某表的指定列由 NOT NULL 改为可空（SQLite 需"改名→建新表→拷数据→删旧表"）。

    历史数据完整保留；列已是可空时直接跳过（幂等）。
    注意：SQLite 重命名表**不会**重命名其索引（索引名全局唯一），
    故先释放旧索引名，否则按新模型建表时 CREATE INDEX 会因同名索引已存在而失败。
    """
    insp = inspect(engine)
    if table not in _table_names(insp):
        return False
    cols = {c["name"]: c for c in insp.get_columns(table)}
    target = cols.get(column)
    if target is None or target.get("nullable"):
        return False

    legacy = f"{table}_legacy"
    index_names = [i["name"] for i in insp.get_indexes(table) if i.get("name")]
    with engine.begin() as conn:
        for name in index_names:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        conn.execute(text(f"DROP TABLE IF EXISTS {legacy}"))
        conn.execute(text(f"ALTER TABLE {table} RENAME TO {legacy}"))
        model.__table__.create(conn)
        common = [c.name for c in model.__table__.columns if c.name in cols]
        columns = ", ".join(common)
        conn.execute(text(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM {legacy}"))
        conn.execute(text(f"DROP TABLE {legacy}"))
    return True


def _relax_change_logs() -> bool:
    """`change_logs.contract_id` 放开为可空（M2 单据变更历史需要，AC-V2-37）。"""
    from .models import ChangeLog

    return _relax_nullable_column("change_logs", "contract_id", ChangeLog)


def _relax_attachments() -> bool:
    """`attachments.contract_id` 放开为可空（T-V2-27 附件扩展到单据）。"""
    from .models import Attachment

    return _relax_nullable_column("attachments", "contract_id", Attachment)


def ensure_schema_upgrades() -> dict:
    """执行全部增量升级，返回本次实际变更统计（便于日志观察）。

    顺序说明：表重建会丢掉该表的索引，故先重建、再补列与索引（`insp` 需重新采集）。
    """
    result = {
        "change_logs_rebuilt": _relax_change_logs(),
        "attachments_rebuilt": _relax_attachments(),
    }
    insp = inspect(engine)
    result["columns_added"] = _add_columns(insp)
    result["indexes_created"] = _add_indexes(insp)
    _backfill_changelog()
    return result
