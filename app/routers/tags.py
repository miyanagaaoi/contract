"""标签字典 API（T4，对应 AC-05/13）。

- GET    /api/tags              标签列表（含使用次数）
- POST   /api/tags              新增标签（全局去重 BR7）
- PUT    /api/tags/{tag_id}     改名（挂该标签的合同展示同步更新）
- DELETE /api/tags/{tag_id}     删除（从字典移除并解除关联）
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Tag, contract_tag

router = APIRouter(prefix="/api/tags", tags=["tags"])

# 标签展示色轮换
_COLORS = ["#409eff", "#67c23a", "#e6a23c", "#f56c6c", "#909399", "#b88230"]


def _get_tag(db: Session, tag_id: int) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    return tag


@router.get("")
def list_tags(db: Session = Depends(get_db)):
    usage = (
        select(contract_tag.c.tag_id, func.count(contract_tag.c.contract_id))
        .group_by(contract_tag.c.tag_id)
    )
    usage_map = dict(db.execute(usage).all())
    tags = db.query(Tag).order_by(Tag.id).all()
    return [
        {"id": t.id, "name": t.name, "color": t.color, "builtin": t.builtin,
         "usage_count": usage_map.get(t.id, 0)}
        for t in tags
    ]


@router.post("")
def create_tag(payload: dict = Body(...), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="标签名称必填")
    if db.query(Tag).filter(Tag.name == name).first():
        raise HTTPException(status_code=409, detail="标签已存在")
    count = db.query(Tag).count()
    tag = Tag(name=name, color=_COLORS[count % len(_COLORS)])
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return {"id": tag.id, "name": tag.name, "color": tag.color, "builtin": tag.builtin, "usage_count": 0}


@router.put("/{tag_id}")
def rename_tag(tag_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="标签名称必填")
    tag = _get_tag(db, tag_id)
    dup = db.query(Tag).filter(Tag.name == name, Tag.id != tag_id).first()
    if dup:
        raise HTTPException(status_code=409, detail="标签已存在")
    old = tag.name
    tag.name = name
    db.commit()
    return {"ok": True, "id": tag.id, "name": tag.name, "renamed_from": old}


@router.delete("/{tag_id}")
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    tag = _get_tag(db, tag_id)
    db.execute(contract_tag.delete().where(contract_tag.c.tag_id == tag_id))
    db.delete(tag)
    db.commit()
    return {"ok": True}
