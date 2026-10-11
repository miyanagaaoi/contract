"""应用配置。

优先级：**真实环境变量 > `.env` 文件 > 代码默认值**。正式部署可用 env 覆盖：
- CTMS_DB_URL       SQLAlchemy 连接串（默认 SQLite app/data/ctms.db；正式可切 PostgreSQL）
- CTMS_UPLOAD_DIR   附件目录
- CTMS_LOG_DIR      日志目录
- CTMS_ENV_FILE     `.env` 文件路径（默认项目根目录 `.env`）

`.env` 由本模块自行加载（零依赖，见 `load_env_file`）：项目不引入 python-dotenv，
但"照 `.env.example` 填一个 `.env` 就能生效"是最自然的用法，否则它就是必然的踩坑点
（已真实发生过：填完值却不生效，且没有任何报错）。
"""
import os
from pathlib import Path


def parse_env_text(text: str) -> dict[str, str]:
    """解析 `.env` 文本 → 键值对（纯函数，便于单测）。

    支持：`KEY=VALUE`、`#` 注释、空行、`export ` 前缀、值两侧成对引号。
    **不支持**变量展开、多行值、命令替换 —— 那是 shell 的职责，配置文件里不该有。

    设计取舍：不合法的行**静默跳过**。配置问题不该让服务起不来 —— 缺值会各自走默认值
    或降级分支（例如飞书没配就整体降级），比"启动即崩"更符合内网系统的运维习惯。
    """
    result: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        # 只接受合法环境变量名，避免把 `Foo Bar=x` 之类塞进 os.environ
        if not key or not (key[0].isalpha() or key[0] == "_"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


def load_env_file(path: Path | None = None) -> Path | None:
    """把 `.env` 注入 `os.environ`，返回实际加载的文件路径（没有文件则 None）。

    **已有环境变量优先**（用 `os.environ.setdefault`）：生产上由 NSSM / Docker Compose /
    systemd 注入的值，永远不会被仓库里那份 `.env` 覆盖 —— 这是刻意的，
    避免"本地文件意外改写生产配置"这种最难排查的事故。
    """
    target = path or Path(os.environ.get("CTMS_ENV_FILE") or (BASE_DIR.parent / ".env"))
    try:
        if not target.is_file():
            return None
        data = parse_env_text(target.read_text(encoding="utf-8"))
    except OSError:
        return None
    for key, value in data.items():
        os.environ.setdefault(key, value)
    return target


BASE_DIR = Path(__file__).resolve().parent          # app/

# ⚠️ 必须在**任何配置读取之前**执行：下面的目录 / 数据库 / 密钥都是模块级常量，
#    在 import 那一刻就被 os.environ 定死了。
load_env_file()

_env = os.environ.get

DATA_DIR = BASE_DIR / "data"                        # SQLite 数据文件目录
UPLOAD_DIR = Path(_env("CTMS_UPLOAD_DIR") or (BASE_DIR / "uploads"))
LOG_DIR = Path(_env("CTMS_LOG_DIR") or (BASE_DIR / "logs"))

_DEFAULT_DB_FILE = DATA_DIR / "ctms.db"
DB_URL = _env("CTMS_DB_URL") or f"sqlite:///{_DEFAULT_DB_FILE.as_posix()}"


def _sqlite_file_of(url: str, fallback: Path) -> Path:
    """从 SQLite 连接串推导数据文件路径。

    ⚠️ **必须与 `DB_URL` 同源**：备份服务（`backup_service`）是按**文件**做一致性快照的
    （`sqlite3` 在线 backup API），若此处退回默认路径，那么一旦用 `CTMS_DB_URL` 指向别的库，
    **备份就会备错文件**——表现为"备份成功"但内容不是当前运行的库，属静默故障。
    V2.1 修复（此前 `DB_FILE` 硬编码为 `app/data/ctms.db`，与 `DB_URL` 可指向不同库）。
    """
    prefix = "sqlite:///"
    if url.startswith(prefix):
        return Path(url[len(prefix):])
    return fallback


DB_FILE = _sqlite_file_of(DB_URL, _DEFAULT_DB_FILE)

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


# ---------- 飞书接入（可选，见 `docs/27-feishu-integration-plan.md`） ----------
# 默认**关闭**：未启用时登录页不显示飞书入口、不启动发送线程、飞书接口无任何副作用，
# 对既有密码登录与全部既有测试零影响（AC-FS-09）。
# app_secret 只从环境变量读：不落库、不进 git、不进日志（与 CTMS_JWT_SECRET 同策略）。
FEISHU_ENABLED = (_env("CTMS_FEISHU_ENABLED") or "0") == "1"
FEISHU_APP_ID = (_env("CTMS_FEISHU_APP_ID") or "").strip()
FEISHU_APP_SECRET = (_env("CTMS_FEISHU_APP_SECRET") or "").strip()
FEISHU_REDIRECT_URI = (_env("CTMS_FEISHU_REDIRECT_URI") or "").strip()
# 卡片里"查看单据"跳转链接的根地址（内网地址即可：链接是给**用户浏览器**打开的，飞书服务器不访问它）
FEISHU_BASE_URL = (_env("CTMS_FEISHU_BASE_URL") or "").strip().rstrip("/")
# 域名可覆盖（飞书国际版为 open.larksuite.com / accounts.larksuite.com），便于私有化与测试
FEISHU_API_BASE = (_env("CTMS_FEISHU_API_BASE") or "https://open.feishu.cn").rstrip("/")
FEISHU_ACCOUNTS_BASE = (_env("CTMS_FEISHU_ACCOUNTS_BASE") or "https://accounts.feishu.cn").rstrip("/")
# 网络与重试（发送串行节流，守住飞书"同一用户 5 QPS"的限制）
FEISHU_TIMEOUT = float(_env("CTMS_FEISHU_TIMEOUT") or 10)
FEISHU_MAX_ATTEMPTS = int(_env("CTMS_FEISHU_MAX_ATTEMPTS") or 5)
FEISHU_SEND_INTERVAL_MS = int(_env("CTMS_FEISHU_SEND_INTERVAL_MS") or 300)


def feishu_ready() -> bool:
    """飞书接入是否可用：开关打开且必要配置齐全；缺一即整体降级（不影响登录与业务）。"""
    return bool(FEISHU_ENABLED and FEISHU_APP_ID and FEISHU_APP_SECRET and FEISHU_REDIRECT_URI)


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
