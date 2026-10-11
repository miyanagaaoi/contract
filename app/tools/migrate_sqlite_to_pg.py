"""SQLite → PostgreSQL 数据迁移（V2.3 / N5）。

背景：开发/演示库长期跑在 SQLite（`app/data/ctms.db`），正式库改用 PostgreSQL。
本脚本把**现有 SQLite 全量业务数据**搬到 PG，并保证迁移后：

1. 表结构由 ORM 模型（`Base.metadata`）在目标库创建 —— 与 SQLite 侧
   `db_migrate.ensure_schema_upgrades()` 的增量结果一致（含 V2.3 的新列）；
2. 逐表拷贝数据（按外键依赖顺序），布尔/日期/数值类型由 SQLAlchemy 按目标方言转换；
3. 自增主键序列重置为 `max(id)`，避免后续插入主键冲突（SQLite 与 PG 的关键差异）；
4. 迁移后逐表比对行数，不一致直接报错退出（非 0 退出码），避免"看起来成功"的静默故障。

用法（必须在项目根目录执行）：

```bash
# 1) 全量迁移（默认源 app/data/ctms.db，目标由 --pg-url 指定）
app\\.venv\\Scripts\\python -m app.tools.migrate_sqlite_to_pg \\
    --pg-url "postgresql+psycopg2://postgres:good789good@192.168.31.27:5444/ctms"

# 2) 目标库已有数据时先清空（危险：会删除目标库全部业务数据）
... --truncate

# 3) 只校验行数，不写入
... --verify-only
```

迁移后以 PG 启动后端：

```bash
set CTMS_DB_URL=postgresql+psycopg2://postgres:good789good@192.168.31.27:5444/ctms
app\\.venv\\Scripts\\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import MetaData, create_engine, select, text

# 让脚本可 `python app/tools/migrate_sqlite_to_pg.py` 直接运行（此时包路径未加入）
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SQLITE = ROOT / "app" / "data" / "ctms.db"
DEFAULT_PG_URL = os.environ.get(
    "CTMS_PG_URL", "postgresql+psycopg2://postgres:good789good@192.168.31.27:5444/ctms")


def _load_models() -> MetaData:
    """导入全部 ORM 模型（建表前必须先 import，否则 metadata 里没有表）。"""
    from app.database import Base

    import app.models  # noqa: F401
    import app.models_auth  # noqa: F401
    import app.models_doc  # noqa: F401
    import app.models_master  # noqa: F401
    import app.models_stock  # noqa: F401

    return Base.metadata


def _ensure_schema(target_engine, metadata: MetaData) -> None:
    """在目标库建表 + 补齐增量列/索引（与 SQLite 侧 `db_migrate` 同源清单）。"""
    metadata.create_all(bind=target_engine)
    result = _upgrade_columns(target_engine)
    print(f"  结构就绪：新增列 {result['columns']}，新增索引 {result['indexes']}")


def _upgrade_columns(engine) -> dict:
    """在新库上补列/补索引（与 `db_migrate._ADD_COLUMNS` 同源清单）。"""
    from sqlalchemy import inspect

    from app.db_migrate import _ADD_COLUMNS, _ADD_INDEXES

    insp = inspect(engine)
    tables = set(insp.get_table_names())
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
    created = 0
    existing: set[str] = set()
    for t in tables:
        existing |= {i["name"] for i in insp.get_indexes(t) if i.get("name")}
    for name, table, cols in _ADD_INDEXES:
        if table not in tables or name in existing:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))
        created += 1
    return {"columns": added, "indexes": created}


def _truncate_target(engine, metadata: MetaData) -> None:
    """按外键依赖的逆序清空目标表（CASCADE 兜底）。"""
    with engine.begin() as conn:
        for table in reversed(metadata.sorted_tables):
            conn.execute(text(f'TRUNCATE TABLE "{table.name}" CASCADE'))
    print(f"  已清空目标库 {len(metadata.sorted_tables)} 张表")


def _copy_table(src_conn, dst_conn, src_meta: MetaData, table, *, dry_run: bool) -> int:
    src_table = src_meta.tables.get(table.name)
    if src_table is None:
        return 0
    cols = [c.name for c in table.columns if c.name in src_table.columns]
    rows = [dict(r._mapping) for r in src_conn.execute(select(*[src_table.c[c] for c in cols]))]
    if not rows or dry_run:
        return len(rows)
    # 分批插入：单条 executemany 在几万行量级下最省事，也便于失败时定位表名
    dst_conn.execute(table.insert(), rows)
    return len(rows)


def _reset_sequences(engine, metadata: MetaData) -> None:
    """把 PG 自增序列推进到当前最大 id（SQLite 无此概念，漏做会导致主键冲突）。"""
    fixed = 0
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            pk = list(table.primary_key.columns)
            if len(pk) != 1 or pk[0].name != "id":
                continue
            seq = conn.execute(
                text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": table.name}).scalar()
            if not seq:
                continue
            conn.execute(text(
                f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM \"{table.name}\"), 1), true)"
            ))
            fixed += 1
    print(f"  已重置 {fixed} 张表的自增序列")


def _verify(src_engine, dst_engine, metadata: MetaData) -> list[str]:
    problems: list[str] = []
    with src_engine.connect() as s, dst_engine.connect() as d:
        for table in metadata.sorted_tables:
            try:
                src_n = s.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar() or 0
            except Exception:
                continue
            dst_n = d.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar() or 0
            if int(src_n) != int(dst_n):
                problems.append(f"{table.name}: SQLite {src_n} ≠ PG {dst_n}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 迁移（V2.3）")
    parser.add_argument("--sqlite", default=str(DEFAULT_SQLITE), help="源 SQLite 文件路径")
    parser.add_argument("--pg-url", default=DEFAULT_PG_URL, help="目标 PostgreSQL 连接串")
    parser.add_argument("--truncate", action="store_true", help="迁移前清空目标库全部表")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    parser.add_argument("--verify-only", action="store_true", help="只比对行数")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        print(f"源库不存在：{sqlite_path}", file=sys.stderr)
        return 2

    metadata = _load_models()
    src_engine = create_engine(f"sqlite:///{sqlite_path.as_posix()}", future=True)
    dst_engine = create_engine(args.pg_url, future=True, pool_pre_ping=True)

    print(f"源：{sqlite_path}")
    print(f"目标：{args.pg_url}")

    if args.verify_only:
        problems = _verify(src_engine, dst_engine, metadata)
        if problems:
            print("行数不一致：")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("校验通过：全部表行数一致")
        return 0

    _ensure_schema(dst_engine, metadata)
    if args.truncate:
        _truncate_target(dst_engine, metadata)

    src_meta = MetaData()
    src_meta.reflect(bind=src_engine)

    total = 0
    with src_engine.connect() as s:
        with dst_engine.begin() as d:
            for table in metadata.sorted_tables:
                n = _copy_table(s, d, src_meta, table, dry_run=args.dry_run)
                if n:
                    total += n
                    print(f"  {table.name:32} {n}")
    print(f"共迁移 {total} 行" + ("（dry-run，未写入）" if args.dry_run else ""))

    if not args.dry_run:
        _reset_sequences(dst_engine, metadata)
        problems = _verify(src_engine, dst_engine, metadata)
        if problems:
            print("行数校验失败：")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("迁移完成，行数校验通过")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
