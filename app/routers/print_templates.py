"""打印模板 API（V2.2，BR-V2.2-02）。

「系统管理 → 打印模板」的后端：管理员可视化调整各类单据的打印版面。

接口清单：
- `GET    /api/system/print-templates`               全部单据类型的模板 + 编辑界面元数据
- `GET    /api/system/print-templates/{kind}`        单个单据类型的模板（含出厂默认值对照）
- `PUT    /api/system/print-templates/{kind}`        保存模板（整表替换）
- `POST   /api/system/print-templates/{kind}/reset`  恢复出厂模板
- `POST   /api/system/print-templates/{kind}/preview` 用**提交的配置**渲染预览 HTML

预览走 POST 而不是 GET：一是配置是结构化 JSON（塞进 query 会超长且难编码），
二是要能预览"还没保存"的改动。前端拿到 HTML 文本后写进 iframe 的 `srcdoc`，
因此不需要为预览单独开一个带令牌的 URL。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models_auth import User
from ..services import audit_service, print_service, print_template_service
from ..services.permission_service import require_perm

router = APIRouter(prefix="/api/system/print-templates", tags=["print-templates"])


def _run(fn, *args, **kwargs):
    """服务层 ValueError → 422（与 system.py 的处理方式一致）。"""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _payload_config(payload: dict) -> dict:
    """接受 `{config: {...}}` 与直接传配置体两种写法。"""
    if isinstance(payload, dict) and isinstance(payload.get("config"), dict):
        return payload["config"]
    return payload if isinstance(payload, dict) else {}


@router.get("", summary="打印模板列表")
def list_templates(_user: User = Depends(require_perm("system.print.view")),
                   db: Session = Depends(get_db)):
    """八类单据的模板概览 + 区块/字段/列目录（前端不重复硬编码这些清单）。"""
    return {
        "items": print_template_service.list_templates(db),
        "meta": print_template_service.template_meta(),
    }


@router.get("/{kind}", summary="单个单据类型的打印模板")
def get_template(kind: str,
                 _user: User = Depends(require_perm("system.print.view")),
                 db: Session = Depends(get_db)):
    if kind not in print_template_service.KIND_LABELS:
        raise HTTPException(status_code=404, detail=f"未知单据类型：{kind}")
    return {**_run(print_template_service.get_template_detail, db, kind),
            "meta": print_template_service.template_meta()}


@router.put("/{kind}", summary="保存打印模板")
def save_template(kind: str, request: Request, payload: dict = Body(...),
                  user: User = Depends(require_perm("system.print.edit")),
                  db: Session = Depends(get_db)):
    config = _payload_config(payload)
    saved = _run(print_template_service.save_config, db, kind, config, user)
    audit_service.log(db, user, module="system", action="edit", object_type="print_template",
                      object_no=kind,
                      detail=f"修改打印模板：{print_template_service.KIND_LABELS.get(kind, kind)}",
                      request=request)
    db.commit()
    return {"ok": True, "kind": kind, "config": saved}


@router.post("/{kind}/reset", summary="恢复出厂打印模板")
def reset_template(kind: str, request: Request,
                   user: User = Depends(require_perm("system.print.edit")),
                   db: Session = Depends(get_db)):
    config = _run(print_template_service.reset_config, db, kind)
    audit_service.log(db, user, module="system", action="edit", object_type="print_template",
                      object_no=kind,
                      detail=f"恢复出厂打印模板：{print_template_service.KIND_LABELS.get(kind, kind)}",
                      request=request)
    db.commit()
    return {"ok": True, "kind": kind, "config": config}


@router.post("/{kind}/preview", response_class=HTMLResponse, summary="打印模板预览")
def preview_template(kind: str, payload: dict = Body(default={}),
                     _user: User = Depends(require_perm("system.print.view")),
                     db: Session = Depends(get_db)):
    """用提交的配置渲染**样例单据**的打印 HTML（不落库、不读业务数据）。"""
    if kind not in print_template_service.KIND_LABELS:
        raise HTTPException(status_code=404, detail=f"未知单据类型：{kind}")
    config = _payload_config(payload or {})
    if not config:
        config = _run(print_template_service.get_config, db, kind)
    doc = print_service.sample_doc(kind)
    return HTMLResponse(content=print_service.build_doc_print_html(db, doc, config))
