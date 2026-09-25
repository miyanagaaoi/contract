"""备份服务（T-V2-12 / AC-V2-39，对应 `12-erp-system-design.md` §5.5）。

口径：
- 备份内容 = **SQLite 数据文件一致性快照**（`sqlite3` 在线 backup API，而非文件复制，
  避免写入事务期间复制出损坏库）+ `uploads/` 附件目录；
- 产物：`app/data/backups/ctms_backup_YYYYmmdd_HHMMSS.zip`；
- 下载：仅允许 `backups/` 目录下、符合命名白名单的 `.zip`（防路径穿越）。

非 SQLite（如 PostgreSQL）部署：数据库部分由数据库自身的备份工具负责，
本服务退化为"仅附件打包"，并在返回值中标注。
"""
from __future__ import annotations

import re
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from ..config import DATA_DIR, DB_FILE, UPLOAD_DIR, is_sqlite

BACKUP_DIR = DATA_DIR / "backups"
_NAME_RE = re.compile(r"^ctms_backup_\d{8}_\d{6}\.zip$")


def backup_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def _safe_arcname(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def create_backup() -> dict:
    """生成备份 zip，返回 {name, size_bytes, created_at, includes, path}。"""
    ensure = backup_dir()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"ctms_backup_{stamp}.zip"
    target = ensure / name

    includes: list[str] = []
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        if is_sqlite() and DB_FILE.exists():
            with tempfile.TemporaryDirectory() as tmp:
                snapshot = Path(tmp) / "ctms.db"
                src = sqlite3.connect(str(DB_FILE))
                try:
                    dst = sqlite3.connect(str(snapshot))
                    try:
                        src.backup(dst)          # 在线一致性快照
                    finally:
                        dst.close()
                finally:
                    src.close()
                zf.write(snapshot, "ctms.db")
            includes.append("ctms.db")
        else:
            includes.append("(跳过数据库：当前部署非 SQLite，请用数据库自身备份工具)")

        if UPLOAD_DIR.exists():
            files = [p for p in UPLOAD_DIR.rglob("*") if p.is_file()]
            for path in files:
                zf.write(path, f"uploads/{_safe_arcname(path, UPLOAD_DIR)}")
            includes.append(f"uploads/（{len(files)} 个附件）")

        zf.writestr("backup_info.txt", "\n".join([
            f"应用：CTMS",
            f"生成时间：{datetime.now().isoformat(timespec='seconds')}",
            f"内容：{'；'.join(includes)}",
            "还原方式：解压后以 ctms.db 覆盖 app/data/ctms.db，uploads/ 覆盖 app/uploads/",
        ]))

    stat = target.stat()
    return {
        "name": name,
        "path": str(target),
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "includes": includes,
    }


def list_backups() -> list[dict]:
    """已生成的备份列表（按时间倒序）。"""
    ensure = backup_dir()
    rows = []
    for path in sorted(ensure.glob("ctms_backup_*.zip"), reverse=True):
        stat = path.stat()
        rows.append({
            "name": path.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    return rows


def resolve_backup(name: str) -> Path:
    """把备份文件名解析为磁盘路径（白名单 + 目录约束，防路径穿越）。"""
    raw = (name or "").strip()
    if not _NAME_RE.match(raw):
        raise ValueError("备份文件名非法")
    path = (backup_dir() / raw).resolve()
    root = backup_dir().resolve()
    if root not in path.parents:
        raise ValueError("备份文件路径非法")
    if not path.is_file():
        raise ValueError("备份文件不存在")
    return path


def delete_backup(name: str) -> None:
    resolve_backup(name).unlink()
