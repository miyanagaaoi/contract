"""合同正文 / 模板 / 签署 API（CR-045）。"""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session

from ..config import MAX_UPLOAD_MB
from ..database import get_db
from ..models import Attachment, Contract
from ..models_auth import User
from ..models_contract_body import ContractTemplate
from ..services import audit_service, signature_service, storage_service
from ..services.permission_service import require_perm, require_superadmin

router = APIRouter(tags=["contracts"])

FIELD_TYPES = ("text", "textarea", "number", "date", "select")
SIGN_STATES = {"none": "未签", "our_signed": "我方已签", "completed": "已生效"}


def _template_fmt(tpl: ContractTemplate) -> dict:
    try:
        fields = json.loads(tpl.fields_json or "[]")
    except json.JSONDecodeError:
        fields = []
    return {"id": tpl.id, "name": tpl.name, "contract_type": tpl.contract_type,
            "body_html": tpl.body_html, "fields": fields, "enabled": tpl.enabled,
            "updated_at": tpl.updated_at.isoformat(sep=" ", timespec="minutes")
            if tpl.updated_at else None}


def _contract_fmt(c: Contract) -> dict:
    try:
        values = json.loads(c.field_values or "{}")
    except (json.JSONDecodeError, TypeError):
        values = {}
    return {"contract_id": c.id, "contract_no": c.contract_no, "name": c.name,
            "template_id": c.template_id, "field_values": values,
            "body_html": c.body_html or "", "body_hash": c.body_hash,
            "sign_status": c.sign_status or "none",
            "sign_status_label": SIGN_STATES.get(c.sign_status or "none"),
            "our_signed_by": c.our_signed_by, "our_signed_name": c.our_signed_name,
            "our_signed_at": c.our_signed_at.isoformat(sep=" ", timespec="minutes")
            if c.our_signed_at else None}


@router.get("/api/contract-templates", summary="合同模板列表（CR-045）")
def list_templates(_user: User = Depends(require_perm("contract.view")),
                   db: Session = Depends(get_db)):
    rows = (db.query(ContractTemplate).order_by(ContractTemplate.id.desc()).all())
    return {"items": [_template_fmt(t) for t in rows],
            "field_types": [{"value": t, "label": {"text": "单行文本", "textarea": "多行文本",
                                                   "number": "数字", "date": "日期",
                                                   "select": "下拉选择"}[t]} for t in FIELD_TYPES]}


def _validate_fields(raw_fields) -> list[dict]:
    if raw_fields is None:
        return []
    if not isinstance(raw_fields, list):
        raise HTTPException(status_code=422, detail="字段定义必须是数组")
    out = []
    seen = set()
    for i, f in enumerate(raw_fields, 1):
        key = str((f or {}).get("key") or "").strip()
        if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise HTTPException(status_code=422, detail=f"第 {i} 个字段 key 非法（字母/下划线开头）")
        if key in seen:
            raise HTTPException(status_code=422, detail=f"字段 key 重复：{key}")
        seen.add(key)
        ftype = str((f or {}).get("type") or "text").strip()
        if ftype not in FIELD_TYPES:
            raise HTTPException(status_code=422, detail=f"字段 {key} 类型不支持：{ftype}")
        item = {"key": key, "label": str((f or {}).get("label") or key).strip(),
                "type": ftype, "required": bool((f or {}).get("required")),
                "placeholder": str((f or {}).get("placeholder") or "").strip() or None}
        if ftype == "select":
            opts = (f or {}).get("options") or []
            item["options"] = [str(o) for o in opts if str(o).strip()]
        out.append(item)
    return out


def _render(body_html: str, fields: list[dict], values: dict) -> str:
    missing = [f["label"] for f in fields
               if f.get("required") and not str(values.get(f["key"]) or "").strip()]
    if missing:
        raise HTTPException(status_code=422, detail="必填字段未填写：" + "、".join(missing))
    rendered = body_html or ""
    for f in fields:
        value = values.get(f["key"], "")
        text = "" if value is None else str(value).strip()
        safe = html.escape(text).replace("\n", "<br/>")
        rendered = rendered.replace("{{" + f["key"] + "}}", safe)
    # 未定义但正文里出现的占位符：清空，避免模板语法外露
    rendered = re.sub(r"\{\{[A-Za-z_][A-Za-z0-9_]*\}\}", "", rendered)
    return rendered


@router.post("/api/contract-templates", summary="新建合同模板（仅管理员）")
def create_template(payload: dict = Body(...), user: User = Depends(require_superadmin),
                    db: Session = Depends(get_db)):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="模板名称必填")
    fields = _validate_fields(payload.get("fields"))
    tpl = ContractTemplate(name=name,
                           contract_type=str(payload.get("contract_type") or "采购"),
                           body_html=str(payload.get("body_html") or ""),
                           fields_json=json.dumps(fields, ensure_ascii=False),
                           created_by=user.id, created_by_name=user.real_name)
    db.add(tpl)
    db.commit()
    return _template_fmt(tpl)


@router.put("/api/contract-templates/{tpl_id}", summary="修改合同模板（仅管理员）")
def update_template(tpl_id: int, payload: dict = Body(...),
                    user: User = Depends(require_superadmin),
                    db: Session = Depends(get_db)):
    tpl = db.get(ContractTemplate, tpl_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="模板名称必填")
        tpl.name = name
    if "contract_type" in payload:
        tpl.contract_type = str(payload.get("contract_type") or "采购")
    if "body_html" in payload:
        tpl.body_html = str(payload.get("body_html") or "")
    if "fields" in payload:
        tpl.fields_json = json.dumps(_validate_fields(payload.get("fields")), ensure_ascii=False)
    if "enabled" in payload:
        tpl.enabled = bool(payload.get("enabled"))
    db.commit()
    return _template_fmt(tpl)


@router.delete("/api/contract-templates/{tpl_id}", summary="删除合同模板（仅管理员）")
def delete_template(tpl_id: int, _user: User = Depends(require_superadmin),
                    db: Session = Depends(get_db)):
    tpl = db.get(ContractTemplate, tpl_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    db.delete(tpl)
    db.commit()
    return {"ok": True}


def _get_contract(db: Session, contract_id: int) -> Contract:
    c = db.get(Contract, contract_id)
    if c is None or c.deleted:
        raise HTTPException(status_code=404, detail="合同不存在")
    return c


@router.get("/api/contracts/{contract_id}/body", summary="合同正文与签署状态")
def get_body(contract_id: int, _user: User = Depends(require_perm("contract.view")),
             db: Session = Depends(get_db)):
    return _contract_fmt(_get_contract(db, contract_id))


@router.put("/api/contracts/{contract_id}/body", summary="生成/更新合同正文（模板+字段快照）")
def save_body(contract_id: int, payload: dict = Body(...),
              user: User = Depends(require_perm("contract.edit")),
              db: Session = Depends(get_db)):
    c = _get_contract(db, contract_id)
    if (c.sign_status or "none") != "none":
        raise HTTPException(status_code=422, detail="合同已签署，正文只读；如需修改请先作废签署（暂不支持）")
    tpl_id = payload.get("template_id")
    if not tpl_id:
        raise HTTPException(status_code=422, detail="请选择合同模板")
    tpl = db.get(ContractTemplate, int(tpl_id))
    if tpl is None or not tpl.enabled:
        raise HTTPException(status_code=422, detail="模板不存在或已停用")
    values = payload.get("field_values") or {}
    if not isinstance(values, dict):
        raise HTTPException(status_code=422, detail="字段值格式错误")
    fields = _validate_fields(json.loads(tpl.fields_json or "[]"))
    body = _render(tpl.body_html, fields, values)
    c.template_id = tpl.id
    c.field_values = json.dumps(values, ensure_ascii=False)
    c.body_html = body
    c.body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    db.commit()
    audit_service.log(db, user, module="contract", action="body", object_type="contract",
                      object_id=c.id, object_no=c.contract_no,
                      detail=f"生成合同正文（模板：{tpl.name}）")
    db.commit()
    return _contract_fmt(c)


@router.post("/api/contracts/{contract_id}/sign", summary="我方在线签署")
def sign_contract(contract_id: int, user: User = Depends(require_perm("contract.edit")),
                  db: Session = Depends(get_db)):
    c = _get_contract(db, contract_id)
    if not (c.body_html or "").strip():
        raise HTTPException(status_code=422, detail="请先生成合同正文")
    if (c.sign_status or "none") == "completed":
        raise HTTPException(status_code=422, detail="合同已生效，不能重复签署")
    if not signature_service.has_signature(user.id):
        raise HTTPException(status_code=422, detail="当前账号未上传手写签名，请先到「个人签名」上传")
    c.sign_status = "our_signed"
    c.our_signed_by = user.id
    c.our_signed_name = user.real_name or user.username
    c.our_signed_at = datetime.now()
    c.body_hash = c.body_hash or hashlib.sha256((c.body_html or "").encode("utf-8")).hexdigest()
    db.commit()
    audit_service.log(db, user, module="contract", action="sign", object_type="contract",
                      object_id=c.id, object_no=c.contract_no,
                      detail=f"我方在线签署（正文哈希 {c.body_hash[:12]}…）")
    db.commit()
    return _contract_fmt(c)


@router.post("/api/contracts/{contract_id}/counterpart-scan", summary="上传对方签署扫描件（置生效）")
async def upload_counterpart_scan(contract_id: int, request: Request,
                                  file: UploadFile = File(...),
                                  user: User = Depends(require_perm("contract.edit")),
                                  db: Session = Depends(get_db)):
    c = _get_contract(db, contract_id)
    if (c.sign_status or "none") != "our_signed":
        raise HTTPException(status_code=422, detail="请先完成我方签署")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="文件为空")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件超过 {MAX_UPLOAD_MB}MB")
    suffix = (file.filename or "").rsplit(".", 1)[-1].lower()
    if suffix not in ("pdf", "png", "jpg", "jpeg"):
        raise HTTPException(status_code=422, detail="仅支持 PDF / PNG / JPG")
    key = f"contracts/{c.id}/counterpart-{uuid_hex()}.{suffix}"
    backend, key = storage_service.save_bytes(db, data, key)
    att = Attachment(contract_id=c.id, object_type="contract", object_id=c.id,
                     file_name=file.filename or f"counterpart.{suffix}",
                     stored_path=key, storage_backend=backend,
                     content_type=file.content_type, size_bytes=len(data))
    db.add(att)
    c.sign_status = "completed"
    c.effective_date = c.effective_date or datetime.now().date()
    db.commit()
    audit_service.log(db, user, module="contract", action="sign_scan", object_type="contract",
                      object_id=c.id, object_no=c.contract_no,
                      detail="上传对方签署扫描件，合同置生效", request=request)
    db.commit()
    return {**_contract_fmt(c), "attachment_id": att.id}


def uuid_hex() -> str:
    import uuid

    return uuid.uuid4().hex
