"""数据库引擎与会话。原型：SQLite；正式版切 PostgreSQL 只改 DB_URL。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DB_URL, ensure_dirs


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


ensure_dirs()
engine = create_engine(DB_URL, connect_args={"check_same_thread": False}, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db():
    """FastAPI 依赖：请求级会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
