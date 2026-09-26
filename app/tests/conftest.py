"""pytest 全局夹具：把测试隔离到**临时 SQLite 库**（V2.1 / T-V2.1-29）。

## 为什么需要这个文件

项目原先没有 `conftest.py`，测试**直接连真实业务库** `app/data/ctms.db`，并以初始
密码 `admin / admin12345` 登录。该密码在首次登录强制改密后即会变化（实际部署中就是
如此），届时所有依赖登录的用例会在 **setup 阶段 ERROR**——实测 **172 个**。
后果有二：

1. 声明的"244 passed"基线**不可复现**，取决于库的历史状态；
2. 测试过程会**读写并污染真实库**（e2e 更是会真实建单）。

## 做法

1. 在导入 `app.*` **之前**把 `CTMS_DB_URL` 指向系统临时目录下的专用库。
   ⚠️ 顺序不可颠倒：`app/config.py` 在 import 时即读取该变量并据此创建 engine。
2. 会话开始前删除旧临时库，保证每次运行都是**干净基线**。
3. 主动建表 + 增量迁移 + 种子（与 `app.main.lifespan` 一致），使不使用
   `TestClient` 的纯单元测试也能拿到完整结构。

## 效果

`pytest app/tests -q` 不再读写真实库、不依赖任何既有账号密码；临时库位于系统
临时目录（默认 `%TEMP%/ctms_pytest.db`），不污染工作区。需要事后排查时该文件会保留。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------- 关键：必须最先执行
_TMP_DB = Path(tempfile.gettempdir()) / "ctms_pytest.db"
os.environ["CTMS_DB_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"
# 测试用固定密钥，避免依赖开发机 app/data/.jwt_secret
os.environ.setdefault("CTMS_JWT_SECRET", "pytest-only-secret-not-for-production-0123456789")


def _remove_tmp_db() -> None:
    """删除上一次运行遗留的临时库（含 WAL/SHM）。"""
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{_TMP_DB}{suffix}")
        if path.exists():
            try:
                path.unlink()
            except OSError:  # 被占用时交给 SQLAlchemy 自行覆盖
                pass


def pytest_configure(config) -> None:  # noqa: ARG001
    """会话开始前：清库并重建干净基线。"""
    _remove_tmp_db()

    from app.config import ensure_dirs
    from app.database import Base, SessionLocal, engine
    from app.db_migrate import ensure_schema_upgrades
    from app.init_db import seed_auth, seed_dicts

    import app.models_auth  # noqa: F401  让 create_all 感知权限/组织/账号表
    import app.models_doc  # noqa: F401  单据表
    import app.models_master  # noqa: F401  主数据表
    import app.models_stock  # noqa: F401  库存表

    ensure_dirs()
    Base.metadata.create_all(bind=engine)
    ensure_schema_upgrades()
    with SessionLocal() as db:
        seed_dicts(db)
        seed_auth(db)
