"""附件 API（T7，对应 AC-09 / BR11）。

- GET    /api/contracts/{cid}/attachments          附件列表
- POST   /api/contracts/{cid}/attachments          上传（multipart, ≤20MB, 类型白名单）
- DELETE /api/contracts/{cid}/attachments/{aid}    删除（留痕）
- GET    /api/attachments/{aid}/download           下载/预览(?inline=1 可浏览器预览)
"""
from __future__ import annotations

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

router = APIRouter(prefix="/api", tags=["attachments"])


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


@router.get("/contracts/{contract_id}/attachments")
def list_attachments(contract_id: int, db: Session = Depends(get_db)):
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
async def upload_attachment(contract_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    contract = _get_contract(db, contract_id)
    if contract.deleted:
        raise HTTPException(status_code=400, detail="合同已停用，不能上传附件")

    original = Path(file.filename or "").name
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(status_code=422, detail=f"不支持的文件类型 {suffix or '(无后缀)'}")
    if not original:
        raise HTTPException(status_code=422, detail="文件名无效")

    folder = UPLOAD_DIR / str(contract_id)
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    target = folder / stored_name

    size = 0
    with target.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"附件超过 {MAX_UPLOAD_MB}MB 限制")
            out.write(chunk)

    att = Attachment(
        contract_id=contract_id,
        file_name=original,
        stored_path=f"{contract_id}/{stored_name}",
        content_type=file.content_type or mimetypes.guess_type(original)[0],
        size_bytes=size,
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
def download_attachment(attachment_id: int, inline: bool = Query(False), db: Session = Depends(get_db)):
    att = _get_attachment(db, attachment_id)
    path = UPLOAD_DIR / att.stored_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件已丢失")
    media_type = att.content_type or "application/octet-stream"
    disposition = "inline" if inline else "attachment"
    quoted = quote(att.file_name)
    return FileResponse(path, media_type=media_type,
                        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quoted}"})
