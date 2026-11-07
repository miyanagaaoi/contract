"""附件 API（T7 / AC-09 / BR11；T-V2-27 扩展到单据）。

合同附件（V1.0 既有，保持兼容）：
- GET    /api/contracts/{cid}/attachments          附件列表
- POST   /api/contracts/{cid}/attachments          上传（multipart, ≤20MB, 类型白名单）
- DELETE /api/contracts/{cid}/attachments/{aid}    删除（留痕）

通用附件（V2.0/M2：附件可挂到任意单据，`object_type` + `object_id`）：
- GET    /api/attachments/list?object_type=&object_id=
- POST   /api/attachments/upload?object_type=&object_id=
- DELETE /api/attachments/{aid}?reason=
- GET    /api/attachments/{aid}/download           下载/预览（?inline=1），按所属对象鉴权
"""
from __future__ import annotations

import hashlib
import mimetypes
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import ALLOWED_UPLOAD_EXT, MAX_UPLOAD_MB, UPLOAD_DIR
from ..database import get_db
from ..models import Attachment, ChangeLog, Contract
from ..models_auth import User
from ..services import audit_service, storage_service
from ..services.permission_service import collect_perms, get_current_user, require_perm

router = APIRouter(prefix="/api", tags=["attachments"])

# 附件所属对象 → (查看权限, 维护权限)
OBJECT_PERMS: dict[str, tuple[str, str]] = {
    "contract": ("contract.view", "contract.edit"),
    "purchase_request": ("purchase.request.view", "purchase.request.edit"),
    "purchase_order": ("purchase.order.view", "purchase.order.edit"),
    "sales_request": ("sales.request.view", "sales.request.edit"),
    "sales_order": ("sales.order.view", "sales.order.edit"),
    "stock_in": ("stock.in.view", "stock.in.edit"),
    "stock_out": ("stock.out.view", "stock.out.edit"),
    "stock_take": ("stock.take.view", "stock.take.edit"),
    # V2.6：发票原始文件（发票包导入的 PDF/OFD/XML）
    "invoice": ("finance.invoice.view", "finance.invoice.create"),
}


def _get_contract(db: Session, contract_id: int) -> Contract:
    c = db.get(Contract, contract_id)
    if c is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    return c


def _get_attachment(db: Session, attachment_id: int) -> Attachment:
    a = db.get(Attachment, attachment_id)
    if a is None or a.deleted:
        raise HTTPException(status_code=404, detail="附件不存在")
    return a


def _log_attachment(db: Session, contract: Contract, action: str, file_name: str) -> None:
    db.add(ChangeLog(contract_id=contract.id, field_name="附件", old_value=None,
                     new_value=action, note=file_name, source="manual"))


# ==================== 通用附件（T-V2-27） ====================

def _permissions_of(object_type: str) -> tuple[str, str]:
    perms = OBJECT_PERMS.get((object_type or "").strip())
    if perms is None:
        raise HTTPException(status_code=422,
                            detail=f"不支持的附件对象类型：{object_type}（可选：{'/'.join(OBJECT_PERMS)}）")
    return perms


def _assert_perm(db: Session, user: User, code: str) -> None:
    if user.is_superadmin:
        return
    if code not in collect_perms(db, user):
        raise HTTPException(status_code=403, detail=f"无权限：{code}")


def _assert_object_exists(db: Session, object_type: str, object_id: int) -> None:
    """附件必须挂在真实存在的对象上（合同或 7 类单据之一）。"""
    if object_type == "contract":
        _get_contract(db, object_id)
        return
    from ..models_doc import DOC_MODELS

    model = DOC_MODELS.get(object_type)
    if model is None:
        raise HTTPException(status_code=422, detail=f"不支持的附件对象类型：{object_type}")
    doc = db.get(model, object_id)
    if doc is None or doc.deleted:
        raise HTTPException(status_code=404, detail="单据不存在")


def _fmt(att: Attachment) -> dict:
    return {
        "id": att.id, "file_name": att.file_name, "content_type": att.content_type,
        "size_bytes": att.size_bytes, "object_type": att.object_type, "object_id": att.object_id,
        "contract_id": att.contract_id,
        "uploaded_at": att.uploaded_at.isoformat() if att.uploaded_at else None,
    }


@router.get("/attachments/list", summary="通用附件列表")
def list_object_attachments(object_type: str = Query(...), object_id: int = Query(...),
                            user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    view_perm, _ = _permissions_of(object_type)
    _assert_perm(db, user, view_perm)
    _assert_object_exists(db, object_type, object_id)
    rows = (db.query(Attachment)
            .filter(Attachment.object_type == object_type, Attachment.object_id == object_id,
                    Attachment.deleted == False)  # noqa: E712
            .order_by(Attachment.id.desc()).all())
    return [_fmt(a) for a in rows]


async def _store_upload(db: Session, file: UploadFile,
                        folder_key: str) -> tuple[str, str, int, str, str]:
    """保存上传文件到**当前启用的存储后端**，返回 (backend, key, size, original, sha256)。"""
    original = Path(file.filename or "").name
    if not original:
        raise HTTPException(status_code=422, detail="文件名无效")
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(status_code=422, detail=f"不支持的文件类型 {suffix or '(无后缀)'}")

    import io

    buf = io.BytesIO()
    size = 0
    digest = hashlib.sha256()
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"附件超过 {MAX_UPLOAD_MB}MB 限制")
        digest.update(chunk)
        buf.write(chunk)
    key = f"{folder_key}/{uuid.uuid4().hex}{suffix}"
    try:
        backend, key = storage_service.save_bytes(db, buf.getvalue(), key)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"写入附件存储失败：{exc}")
    return backend, key, size, original, digest.hexdigest()


def _remove_stored(db: Session, backend: str, key: str) -> None:
    """删除刚落盘但判定为重复的附件文件（忽略异常）。"""
    storage_service.delete_bytes(db, backend, key)


@router.post("/attachments/upload", summary="通用附件上传")
async def upload_object_attachment(object_type: str = Query(...), object_id: int = Query(...),
                                   file: UploadFile = File(...),
                                   user: User = Depends(get_current_user),
                                   db: Session = Depends(get_db)):
    _, edit_perm = _permissions_of(object_type)
    _assert_perm(db, user, edit_perm)
    _assert_object_exists(db, object_type, object_id)

    backend, stored_path, size, original, sha = await _store_upload(
        db, file, f"{object_type}/{object_id}")
    # CR-033：同一对象重复上传同一文件 → 直接返回已有附件（不落第二份）
    exists = (db.query(Attachment)
              .filter(Attachment.object_type == object_type,
                      Attachment.object_id == object_id,
                      Attachment.sha256 == sha,
                      Attachment.deleted == False)  # noqa: E712
              .first())
    if exists is not None:
        _remove_stored(db, backend, stored_path)
        return _fmt(exists)
    att = Attachment(
        contract_id=object_id if object_type == "contract" else None,
        object_type=object_type, object_id=object_id,
        file_name=original, stored_path=stored_path,
        content_type=file.content_type or mimetypes.guess_type(original)[0],
        size_bytes=size, sha256=sha, storage_backend=backend,
    )
    db.add(att)
    db.flush()
    if object_type == "contract":
        _log_attachment(db, _get_contract(db, object_id), "上传附件", original)
    audit_service.log(db, user, module="attachment", action="create",
                      object_type=object_type, object_id=object_id, object_no=original,
                      detail=f"上传附件（{size} 字节）")
    db.commit()
    db.refresh(att)
    return _fmt(att)


@router.delete("/attachments/{attachment_id}", summary="通用附件删除")
def delete_object_attachment(attachment_id: int, reason: str | None = Query(None),
                             user: User = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    att = _get_attachment(db, attachment_id)
    object_type = att.object_type or "contract"
    _, edit_perm = _permissions_of(object_type)
    _assert_perm(db, user, edit_perm)
    att.deleted = True
    if att.contract_id:
        _log_attachment(db, _get_contract(db, att.contract_id),
                        f"删除附件（{reason or '未填原因'}）", att.file_name)
    audit_service.log(db, user, module="attachment", action="delete",
                      object_type=object_type, object_id=att.object_id,
                      object_no=att.file_name, detail=reason)
    db.commit()
    return {"ok": True, "id": attachment_id}


# ==================== 合同附件（V1.0 兼容） ====================

@router.get("/contracts/{contract_id}/attachments")
def list_attachments(contract_id: int,
                     _user: User = Depends(require_perm("contract.view")),
                     db: Session = Depends(get_db)):
    _get_contract(db, contract_id)
    rows = db.query(Attachment).filter(
        Attachment.contract_id == contract_id, Attachment.deleted == False  # noqa: E712
    ).order_by(Attachment.id.desc()).all()
    return [
        {"id": a.id, "file_name": a.file_name, "content_type": a.content_type,
         "size_bytes": a.size_bytes,
         "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None}
        for a in rows
    ]


@router.post("/contracts/{contract_id}/attachments")
async def upload_attachment(contract_id: int, file: UploadFile = File(...),
                            user: User = Depends(require_perm("contract.edit")),
                            db: Session = Depends(get_db)):
    contract = _get_contract(db, contract_id)
    if contract.deleted:
        raise HTTPException(status_code=400, detail="合同已停用，不能上传附件")

    backend, stored_path, size, original, sha = await _store_upload(db, file, str(contract_id))
    exists = (db.query(Attachment)
              .filter(Attachment.object_type == "contract", Attachment.object_id == contract_id,
                      Attachment.sha256 == sha, Attachment.deleted == False)  # noqa: E712
              .first())
    if exists is not None:
        _remove_stored(db, backend, stored_path)
        return {"id": exists.id, "file_name": exists.file_name, "size_bytes": exists.size_bytes,
                "uploaded_at": exists.uploaded_at.isoformat() if exists.uploaded_at else None,
                "duplicated": True}
    att = Attachment(
        contract_id=contract_id, object_type="contract", object_id=contract_id,
        file_name=original, stored_path=stored_path,
        content_type=file.content_type or mimetypes.guess_type(original)[0],
        size_bytes=size, sha256=sha, storage_backend=backend,
    )
    db.add(att)
    db.flush()
    _log_attachment(db, contract, "上传附件", original)
    db.commit()
    db.refresh(att)
    return {"id": att.id, "file_name": att.file_name, "size_bytes": att.size_bytes,
            "uploaded_at": att.uploaded_at.isoformat() if att.uploaded_at else None}


@router.delete("/contracts/{contract_id}/attachments/{attachment_id}")
def delete_attachment(contract_id: int, attachment_id: int, reason: str | None = Query(None),
                      _user: User = Depends(require_perm("contract.edit")),
                      db: Session = Depends(get_db)):
    contract = _get_contract(db, contract_id)
    att = _get_attachment(db, attachment_id)
    if att.contract_id != contract_id:
        raise HTTPException(status_code=404, detail="附件不属于该合同")
    att.deleted = True
    _log_attachment(db, contract, f"删除附件（{reason or '未填原因'}）", att.file_name)
    db.commit()
    return {"ok": True, "id": attachment_id}


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int, inline: bool = Query(False),
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """下载/预览：按附件所属对象的**查看权限**鉴权（单据附件不受合同权限限制）。"""
    att = _get_attachment(db, attachment_id)
    object_type = att.object_type or "contract"
    view_perm, _ = _permissions_of(object_type)
    _assert_perm(db, user, view_perm)

    try:
        data = storage_service.read_bytes(db, getattr(att, "storage_backend", "local"),
                                          att.stored_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="文件已丢失")
    media_type = att.content_type or "application/octet-stream"
    disposition = "inline" if inline else "attachment"
    quoted = quote(att.file_name)
    from fastapi import Response

    return Response(content=data, media_type=media_type,
                    headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quoted}"})
