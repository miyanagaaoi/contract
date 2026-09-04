"""数据库引擎与会话。原型：SQLite；正式版切 PostgreSQL 只改 DB_URL。"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DB_URL, ensure_dirs


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


ensure_dirs()
engine = create_engine(DB_URL, connect_args={"check_same_thread": False}, future=True)


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
