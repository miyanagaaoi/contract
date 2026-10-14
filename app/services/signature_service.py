"""电子签名图片服务：账号预存手写签名扫描件，打印单据时嵌入签字位。

存储口径（避免给 `User` 模型加列做迁移）：
- 文件落在 `UPLOAD_DIR/signatures/signature_{user_id}.{png|jpg|jpeg}`；
- "是否有签名"完全由**文件是否存在**判断（`has_signature`），无库表状态；
- 只做扩展名与字节数校验（项目 venv 没有 Pillow，不引入新依赖，不解析像素）。
"""
from __future__ import annotations

import base64
from pathlib import Path

from ..config import UPLOAD_DIR

#: 签名图片目录（模块属性而非函数内常量：测试可用 monkeypatch 指到临时目录）
SIGNATURE_DIR = UPLOAD_DIR / "signatures"

#: 允许的扩展名 → MIME（查看接口的 Content-Type 与 data URL 前缀共用）
ALLOWED_TYPES: dict[str, str] = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}

#: 大小上限 500KB：签名是白底小图，不需要更大；也防恶意大文件撑爆打印 HTML
MAX_SIGNATURE_BYTES = 500 * 1024


def _candidate_paths(user_id: int) -> list[Path]:
    return [SIGNATURE_DIR / f"signature_{user_id}.{ext}" for ext in ALLOWED_TYPES]


def find_signature(user_id: int) -> Path | None:
    """返回该账号已存在的签名文件路径；一个账号最多一份（换格式上传时删旧存新）。"""
    for path in _candidate_paths(user_id):
        if path.is_file():
            return path
    return None


def has_signature(user_id: int) -> bool:
    return find_signature(user_id) is not None


def save_signature(user_id: int, filename: str | None, data: bytes) -> Path:
    """校验并落盘签名图片；失败抛 ValueError（路由层转 422）。

    换扩展名重新上传时删除旧文件，保证"一个账号一份签名"的单一事实。
    """
    ext = (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    if ext not in ALLOWED_TYPES:
        raise ValueError("签名图片仅支持 PNG / JPG 格式")
    if len(data) > MAX_SIGNATURE_BYTES:
        raise ValueError("签名图片不能超过 500KB")
    SIGNATURE_DIR.mkdir(parents=True, exist_ok=True)
    for old in _candidate_paths(user_id):
        if old.is_file() and old.suffix.lstrip(".") != ext:
            old.unlink(missing_ok=True)
    path = SIGNATURE_DIR / f"signature_{user_id}.{ext}"
    path.write_bytes(data)
    return path


def delete_signature(user_id: int) -> bool:
    """删除签名文件；返回是否真的删了（不存在时 False，路由层据此 404）。"""
    removed = False
    for path in _candidate_paths(user_id):
        if path.is_file():
            path.unlink(missing_ok=True)
            removed = True
    return removed


def signature_data_url(user_id: int) -> str | None:
    """签名图转 data URL（打印 HTML 内嵌用；打印页是 blob 打开，不能引用需鉴权的接口）。"""
    path = find_signature(user_id)
    if path is None:
        return None
    mime = ALLOWED_TYPES[path.suffix.lstrip(".").lower()]
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"
