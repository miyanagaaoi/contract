"""应用配置。原型阶段全部走本地文件目录，无需环境变量即可运行。"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent          # app/
DATA_DIR = BASE_DIR / "data"                        # SQLite 数据文件目录
UPLOAD_DIR = BASE_DIR / "uploads"                   # 附件存储目录
LOG_DIR = BASE_DIR / "logs"

DB_FILE = DATA_DIR / "ctms.db"
DB_URL = f"sqlite:///{(DB_FILE).as_posix()}"

APP_NAME = "CTMS"
APP_VERSION = "0.1.0-prototype"

# 附件限制
MAX_UPLOAD_MB = 20
ALLOWED_UPLOAD_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".txt"}


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
