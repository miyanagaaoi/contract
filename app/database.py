"""数据库引擎与会话。默认 SQLite；正式版可用 CTMS_DB_URL 指向 PostgreSQL。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DB_URL, ensure_dirs, is_sqlite


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


ensure_dirs()
if is_sqlite():
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False}, future=True)
else:
    engine = create_engine(DB_URL, future=True, pool_pre_ping=True)


if is_sqlite():
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _connection_record):  # pragma: no cover - sqlite only
        """SQLite 默认不启用外键，这里显式开启以支持级联删除。"""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db():
    """FastAPI 依赖：请求级会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
