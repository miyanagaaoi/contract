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
APP_VERSION = "2.0.0-dev"  # V2.0 ERP 进销存（M1 开发中）

# 附件限制
MAX_UPLOAD_MB = 20
ALLOWED_UPLOAD_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".txt"}

# ---------- V2.0：认证与权限（见 12-erp-system-design.md §3.7） ----------
AUTH_ENABLED = (_env("CTMS_AUTH_ENABLED") or "1") == "1"   # 0 = 跳过认证，仅本地调试
JWT_HOURS = int(_env("CTMS_JWT_HOURS") or 8)
JWT_SECRET_FILE = DATA_DIR / ".jwt_secret"
_JWT_SECRET = _env("CTMS_JWT_SECRET") or ""


def is_sqlite() -> bool:
    return DB_URL.startswith("sqlite")


def ensure_dirs() -> None:
    for d in (UPLOAD_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if is_sqlite():
        DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_jwt_secret() -> str:
    """JWT 签名密钥：env 优先；否则首次调用生成随机密钥并落盘（避免硬编码密钥）。"""
    global _JWT_SECRET
    if _JWT_SECRET:
        return _JWT_SECRET
    if JWT_SECRET_FILE.exists():
        _JWT_SECRET = JWT_SECRET_FILE.read_text(encoding="utf-8").strip()
    if not _JWT_SECRET:
        import secrets

        ensure_dirs()
        _JWT_SECRET = secrets.token_urlsafe(48)
        JWT_SECRET_FILE.write_text(_JWT_SECRET, encoding="utf-8")
    return _JWT_SECRET
