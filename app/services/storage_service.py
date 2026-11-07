"""附件存储抽象（CR-046）：本地磁盘 / SMB 挂载目录。

设计取舍（见 PRD CR-046）：
- 只做 **SMB 挂载路径**，不引入 SMB 协议库：NAS 侧把共享挂载到容器（CIFS volume 或
  宿主机挂载），本服务只读写该目录 —— Docker/飞牛/群晖部署最稳，也不需要在应用里存密码；
- 两种后端：`local`（默认，容器内 `/data/uploads`）与 `smb`（配置的挂载路径 + 前缀）；
- 配置存 `kv_settings.attachment_storage`；**不含任何密码**（凭据由挂载层管理）；
- 附件表记录 `storage_backend + stored_path(key)`，切换后端后旧附件仍可按记录的后端读取；
- 下载/预览统一走应用鉴权代理，不直接暴露存储路径。
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from .. import config
from ..models import KVSetting

KEY = "attachment_storage"
DEFAULT: dict = {"backend": "local", "smb_path": "", "prefix": "ctms/"}
BACKENDS = ("local", "smb")


def _load(db: Session) -> dict:
    row = db.get(KVSetting, KEY)
    data = dict(DEFAULT)
    if row is not None:
        try:
            stored = json.loads(row.value)
            if isinstance(stored, dict):
                data.update({k: v for k, v in stored.items() if k in DEFAULT})
        except (json.JSONDecodeError, TypeError):
            pass
    return data


def get_config(db: Session) -> dict:
    """返回当前配置（附可用性信息，供设置页展示）。"""
    cfg = _load(db)
    return {**cfg, "root": str(_root(cfg)), "writable": _writable(_root(cfg))}


def save_config(db: Session, values: dict) -> dict:
    cfg = _load(db)
    if "backend" in values:
        backend = str(values.get("backend") or "local").strip()
        if backend not in BACKENDS:
            raise ValueError("存储后端只能是 local / smb")
        cfg["backend"] = backend
    if "smb_path" in values:
        cfg["smb_path"] = str(values.get("smb_path") or "").strip()
    if "prefix" in values:
        cfg["prefix"] = (str(values.get("prefix") or "").strip().strip("/") + "/") if values.get("prefix") else ""
    if cfg["backend"] == "smb":
        if not cfg["smb_path"]:
            raise ValueError("选择 SMB 时必须填写共享挂载路径（如 /mnt/ctms-share）")
        base = Path(cfg["smb_path"])
        if not base.exists():
            raise ValueError(f"挂载路径不可用：{base}（请先在 NAS/宿主机挂载该共享）")
        if not _writable(base):
            raise ValueError(f"挂载路径不可写：{base}")
        # 前缀子目录首次使用时自动创建
        try:
            _root(cfg).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"无法创建前缀目录 {_root(cfg)}：{exc}")
    raw = json.dumps(cfg, ensure_ascii=False)
    row = db.get(KVSetting, KEY)
    if row is None:
        db.add(KVSetting(key=KEY, value=raw))
    else:
        row.value = raw
    db.commit()
    return get_config(db)


def _root(cfg: dict) -> Path:
    if cfg["backend"] == "smb":
        return Path(cfg["smb_path"]) / (cfg["prefix"] or "")
    return Path(config.UPLOAD_DIR)


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".probe-{uuid.uuid4().hex[:8]}"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        return False


def save_bytes(db: Session, data: bytes, rel_key: str) -> tuple[str, str]:
    """写入当前启用的后端，返回 `(backend, key)`；写入失败抛 `OSError`。"""
    cfg = _load(db)
    root = _root(cfg)
    target = root / rel_key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return cfg["backend"], rel_key


def _root_of(db: Session, backend: str) -> Path:
    cfg = _load(db)
    if backend == "smb":
        return Path(cfg["smb_path"]) / (cfg["prefix"] or "")
    return Path(config.UPLOAD_DIR)


def read_bytes(db: Session, backend: str | None, rel_key: str) -> bytes:
    path = _root_of(db, backend or "local") / rel_key
    if not path.exists():
        raise FileNotFoundError(rel_key)
    return path.read_bytes()


def delete_bytes(db: Session, backend: str | None, rel_key: str) -> None:
    try:
        (_root_of(db, backend or "local") / rel_key).unlink(missing_ok=True)
    except OSError:
        pass


def probe(db: Session) -> dict:
    """连接自检：写/读/删一个探针文件，返回可展示结果。"""
    cfg = _load(db)
    root = _root(cfg)
    result = {"backend": cfg["backend"], "root": str(root), "ok": False, "message": ""}
    try:
        if cfg["backend"] == "smb" and not cfg["smb_path"]:
            result["message"] = "未配置 SMB 挂载路径"
            return result
        root.mkdir(parents=True, exist_ok=True)
        name = f".probe-{uuid.uuid4().hex[:8]}.txt"
        (root / name).write_bytes(b"ctms-probe")
        got = (root / name).read_bytes()
        (root / name).unlink(missing_ok=True)
        result["ok"] = got == b"ctms-probe"
        result["message"] = "读写正常" if result["ok"] else "写入后读取不一致"
    except OSError as exc:
        result["message"] = f"{type(exc).__name__}: {exc}"
    return result


def migrate_local_to_current(db: Session, limit: int | None = None) -> dict:
    """把手动迁移工具：本地附件复制到当前后端（不删除源文件）。

    返回 `{moved, skipped, failed}`；幂等（目标已存在则跳过）。
    """
    from ..models import Attachment

    cfg = _load(db)
    if cfg["backend"] == "local":
        return {"moved": 0, "skipped": 0, "failed": 0, "message": "当前后端是 local，无需迁移"}
    root = _root(cfg)
    local_root = Path(config.UPLOAD_DIR)
    query = db.query(Attachment).filter(
        (Attachment.storage_backend.is_(None)) | (Attachment.storage_backend == "local"))
    rows = query.limit(limit).all() if limit else query.all()
    moved = skipped = failed = 0
    for att in rows:
        src = local_root / att.stored_path
        dst = root / att.stored_path
        if not src.exists():
            failed += 1
            continue
        if dst.exists():
            att.storage_backend = cfg["backend"]
            skipped += 1
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            att.storage_backend = cfg["backend"]
            moved += 1
        except OSError:
            failed += 1
    db.commit()
    return {"moved": moved, "skipped": skipped, "failed": failed,
            "message": f"迁移到 {cfg['backend']}：成功 {moved}，跳过 {skipped}，失败 {failed}"}
