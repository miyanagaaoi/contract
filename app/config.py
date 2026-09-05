"""应用配置。

优先级：环境变量 > 本地默认。正式部署可用 env 覆盖：
- CTMS_DB_URL       SQLAlchemy 连接串（默认 SQLite app/data/ctms.db；正式可切 PostgreSQL）
- CTMS_UPLOAD_DIR   附件目录
- CTMS_LOG_DIR      日志目录
"""
import os
from pathlib import Path

_env = os.environ.get

BASE_DIR = Path(__file__).resolve().parent          # app/
DATA_DIR = BASE_DIR / "data"                        # SQLite 数据文件目录
UPLOAD_DIR = Path(_env("CTMS_UPLOAD_DIR") or (BASE_DIR / "uploads"))
LOG_DIR = Path(_env("CTMS_LOG_DIR") or (BASE_DIR / "logs"))

DB_FILE = DATA_DIR / "ctms.db"
DB_URL = _env("CTMS_DB_URL") or f"sqlite:///{(DB_FILE).as_posix()}"

APP_NAME = "CTMS"
APP_VERSION = "1.0.0-rc1"  # P3 正式版候选

# 附件限制
MAX_UPLOAD_MB = 20
ALLOWED_UPLOAD_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".txt"}


def is_sqlite() -> bool:
    return DB_URL.startswith("sqlite")


def ensure_dirs() -> None:
    for d in (UPLOAD_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if is_sqlite():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
