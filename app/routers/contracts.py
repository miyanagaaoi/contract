"""合同台账 API（T3，对应 AC-01/02/10/15）。

- POST /api/contracts            新增（编号唯一校验 AC-02）
- GET  /api/contracts            分页列表（基础筛选；完整组合筛选在 T5）
- GET  /api/contracts/{id}       详情（含子合同汇总/变更历史由 T6 细化）
- PUT  /api/contracts/{id}       修改（关键字段自动写 ChangeLog）
- DELETE /api/contracts/{id}     软删除（必填原因，AC-10）
- PUT  /api/contracts/{id}/restore  恢复（30 天内，AC-15）
- GET  /api/contracts/{id}/logs  变更历史
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    RESTORE_DAYS,
    STATUSES,
    Contract,
    ContractItem,
    Tag,
    compute_warranty_end,
    contract_tag,
)

router = APIRouter(prefix="/api/contracts", tags=["contracts"])

# 参与变更历史跟踪的字段（BR12；值变化即记录 时间/旧值/新值）
TRACKED_FIELDS = [
    "contract_no", "name", "type", "party_a", "party_b", "sign_date", "effective_date",
    "subject_matter", "amount", "currency", "paid_amount", "has_warranty",
    "warranty_amount", "warranty_rate", "warranty_start", "warranty_months",
    "warranty_end", "warranty_released", "warranty_release_date", "warranty_note",
    "is_framework", "parent_id", "arrival_status", "expected_arrival_date",
    "status", "owner_name", "remark",
]

_INT_FIELDS = {"warranty_months"}
_BOOL_FIELDS = {"has_warranty", "warranty_released", "is_framework"}
_DECIMAL_FIELDS = {"amount", "paid_amount", "warranty_amount", "warranty_rate"}
_DATE_FIELDS = {
    "sign_date", "effective_date", "warranty_start", "warranty_end",
    "warranty_release_date", "expected_arrival_date",
}
# 允许显式置空（传 null）的字段；其余必填字段传 null 时忽略
_NULLABLE_FIELDS = {
    "sign_date", "effective_date", "parent_id", "expected_arrival_date",
    "warranty_amount", "warranty_rate", "warranty_start", "warranty_months",
    "warranty_end", "warranty_release_date", "warranty_note", "owner_name", "remark",
}


def _log(db: Session, contract: Contract, field: str, old, new, note: str | None = None,
         source: str = "manual") -> None:
    from ..models import ChangeLog

    db.add(ChangeLog(
        contract_id=contract.id, field_name=field,
        old_value=None if old is None else str(old),
        new_value=None if new is None else str(new),
        note=note, source=source,
    ))


def _norm(value, field: str):
    """把前端传入值按字段类型归一化，便于比较与入库。"""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None  # 空字符串按 null 处理（修复：空日期/空值导致 500）
    if field in _BOOL_FIELDS:
        return bool(value)
    if field in _INT_FIELDS:
        return int(value)
    if field in _DECIMAL_FIELDS:
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise HTTPException(status_code=422, detail=f"字段 {field} 必须是数字")
    if field in _DATE_FIELDS:
        if isinstance(value, str):
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        return value
    if field in {"amount", "paid_amount"}:
        pass
    return value


def _apply_updates(db: Session, contract: Contract, payload: dict, note: str | None = None) -> list[str]:
    """应用变更并写变更历史，返回发生变更的字段列表。"""
    changed: list[str] = []
    for field in TRACKED_FIELDS:
        if field not in payload:
            continue
        new_raw = _norm(payload[field], field)
        if new_raw is None and field not in _NULLABLE_FIELDS:
            continue  # 非空字段不接受 null
        if field == "has_warranty" and not new_raw:
            # 关闭质保时清空相关字段
            for wf in ("warranty_amount", "warranty_rate", "warranty_start",
                       "warranty_months", "warranty_end", "warranty_release_date", "warranty_note"):
                if getattr(contract, wf) is not None:
                    _log(db, contract, wf, getattr(contract, wf), None)
                    setattr(contract, wf, None)
        old = getattr(contract, field)
        if str(old) == str(new_raw):
            continue
        _log(db, contract, field, old, new_raw)
        setattr(contract, field, new_raw)
        changed.append(field)

    # 质保联动：按 Q2 计算到期日（BR5）
    if contract.has_warranty and contract.warranty_start and contract.warranty_months:
        computed = compute_warranty_end(contract.warranty_start, contract.warranty_months)
        if contract.warranty_end != computed:
            _log(db, contract, "warranty_end", contract.warranty_end, computed, source="auto")
            contract.warranty_end = computed
    # 金额/比例换算：录比例补金额，录金额补比例（BR5）
    if contract.has_warranty and contract.amount:
        if contract.warranty_rate is not None and contract.warranty_amount is None:
            contract.warranty_amount = (contract.amount * contract.warranty_rate / Decimal("100")).quantize(Decimal("0.01"))
        elif contract.warranty_amount is not None and contract.warranty_rate is None:
            contract.warranty_rate = (contract.warranty_amount / contract.amount * Decimal("100")).quantize(Decimal("0.0001"))

    if changed or note:
        _log(db, contract, "_summary", None, ",".join(changed) or None, note=note)
    db.commit()
    db.refresh(contract)
    return changed


def _fmt(c: Contract, db: Session | None = None) -> dict:
    from ..models import ChangeLog

    parent_no = None
    if c.parent_id:
        parent = db.get(Contract, c.parent_id) if db else None
        parent_no = parent.contract_no if parent else None
    ratio = c.payment_ratio
    return {
        "id": c.id,
        "contract_no": c.contract_no,
        "name": c.name,
        "type": c.type,
        "party_a": c.party_a,
        "party_b": c.party_b,
        "sign_date": c.sign_date.isoformat() if c.sign_date else None,
        "effective_date": c.effective_date.isoformat() if c.effective_date else None,
        "subject_matter": c.subject_matter,
        "amount": float(c.amount) if c.amount is not None else None,
        "currency": c.currency,
        "paid_amount": float(c.paid_amount) if c.paid_amount is not None else None,
        "payment_ratio": float(ratio) if ratio is not None else None,
        "has_warranty": c.has_warranty,
        "warranty_amount": float(c.warranty_amount) if c.warranty_amount is not None else None,
        "warranty_rate": float(c.warranty_rate) if c.warranty_rate is not None else None,
        "warranty_start": c.warranty_start.isoformat() if c.warranty_start else None,
        "warranty_months": c.warranty_months,
        "warranty_end": c.warranty_end.isoformat() if c.warranty_end else None,
        "warranty_released": c.warranty_released,
        "warranty_release_date": c.warranty_release_date.isoformat() if c.warranty_release_date else None,
        "is_framework": c.is_framework,
        "parent_id": c.parent_id,
        "parent_no": parent_no,
        "arrival_status": c.arrival_status,
        "expected_arrival_date": c.expected_arrival_date.isoformat() if c.expected_arrival_date else None,
        "status": c.status,
        "owner_name": c.owner_name,
        "remark": c.remark,
        "deleted": c.deleted,
        "deleted_at": c.deleted_at.isoformat() if c.deleted_at else None,
        "deleted_reason": c.deleted_reason,
        "tags": [t.name for t in c.tags],
        "items": [
            {"seq": it.seq, "item_type": it.item_type, "name": it.name, "spec": it.spec,
             "qty": float(it.qty) if it.qty is not None else None,
             "unit_price": float(it.unit_price) if it.unit_price is not None else None,
             "total": float(it.total) if it.total is not None else None,
             "remark": it.remark}
            for it in (c.items or [])
        ],
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _summary_text(items: list) -> str:
    """由行项生成"标的物"摘要：名称(规格)×数量 用分号连接。"""
    parts = []
    for it in items:
        name = it.name or "未命名项"
        if it.spec:
            name = f"{name}({it.spec})"
        qty = it.qty
        q = f"{qty:f}".rstrip("0").rstrip(".") if qty == int(qty) else f"{qty:f}".rstrip("0").rstrip(".")
        parts.append(f"{name}×{q}")
    return "；".join(parts)


def _apply_items(db: Session, contract: Contract, rows_raw) -> None:
    """行项明细整体替换（MVP2 需求①）。

    规则：
    - 行项非空 → 金额=Σ行项总价（自动覆盖）、"标的物"=行项摘要（自动）；
    - 行项为空 [] → 清空行项，金额/标的物不动（允许无行项合同手工维护金额）。
    """
    if rows_raw is None:
        return
    rows = [r for r in rows_raw if isinstance(r, dict)]
    new_items: list[ContractItem] = []
    for i, r in enumerate(rows, start=1):
        name = str(r.get("name") or "").strip()
        spec = str(r.get("spec") or "").strip()
        qty_raw = str(r.get("qty") or "").strip()
        price_raw = str(r.get("unit_price") or "").strip()
        if not name and not spec and not qty_raw and not price_raw and not (r.get("remark") or "").strip():
            continue  # 全空行忽略
        if not name:
            raise HTTPException(status_code=422, detail=f"行项第 {i} 行缺少名称")
        try:
            qty = Decimal(qty_raw or "0")
            price = Decimal(price_raw or "0")
        except InvalidOperation:
            raise HTTPException(status_code=422, detail=f"行项第 {i} 行数量/单价不是数字")
        if qty < 0 or price < 0:
            raise HTTPException(status_code=422, detail=f"行项第 {i} 行数量/单价不能为负")
        total = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        new_items.append(ContractItem(
            seq=i,
            item_type=str(r.get("item_type") or "").strip() or "采购",
            name=name, spec=spec, qty=qty, unit_price=price, total=total,
            remark=(str(r.get("remark") or "")).strip() or None,
        ))

    def _sig(it: ContractItem) -> tuple:
        return (it.seq, it.item_type, it.name, it.spec, str(it.qty), str(it.unit_price), str(it.total), it.remark)

    old_sig = [_sig(x) for x in (contract.items or [])]
    new_sig = [_sig(x) for x in new_items]
    if old_sig == new_sig:
        return
    _log(db, contract, "_items", str(len(old_sig)), str(len(new_sig)), source="manual")
    contract.items = new_items
    db.flush()
    if new_items:
        total_sum = (sum((x.total or 0) for x in new_items)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if contract.amount != total_sum:
            _log(db, contract, "amount", contract.amount, total_sum, source="auto")
            contract.amount = total_sum
        summary = _summary_text(new_items)
        if contract.subject_matter != summary:
            _log(db, contract, "subject_matter", contract.subject_matter, summary, source="auto")
            contract.subject_matter = summary
    db.commit()
    db.refresh(contract)


def _sync_tags(db: Session, contract: Contract, tag_names: list) -> None:
    """按名称整体替换合同标签（BR7）：不存在的名称自动新建。返回是否变化。"""
    names = []
    for n in tag_names or []:
        n = (n or "").strip()
        if n and n not in names:
            names.append(n)
    current = {t.name for t in contract.tags}
    if set(names) == current:
        return
    resolved: list[Tag] = []
    for name in names:
        tag = db.query(Tag).filter(Tag.name == name).first()
        if tag is None:
            count = db.query(Tag).count()
            tag = Tag(name=name, color=["#409eff", "#67c23a", "#e6a23c", "#f56c6c", "#909399"][count % 5])
            db.add(tag)
            db.flush()
        resolved.append(tag)
    contract.tags = resolved
    _log(db, contract, "_tags", ",".join(sorted(current)), ",".join(names), source="manual")
    db.commit()


def _get_contract(db: Session, contract_id: int) -> Contract:
    c = db.get(Contract, contract_id)
    if c is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    return c


@router.post("")
def create_contract(payload: dict = Body(...), db: Session = Depends(get_db)):
    # BR1/BR2：编号与名称必填且唯一
    contract_no = (payload.get("contract_no") or "").strip()
    name = (payload.get("name") or "").strip()
    if not contract_no:
        raise HTTPException(status_code=422, detail="合同编号必填")
    if not name:
        raise HTTPException(status_code=422, detail="合同名称必填")
    exists = db.query(Contract).filter(Contract.contract_no == contract_no).first()
    if exists:
        raise HTTPException(status_code=409, detail="合同编号已存在")
    from ..models import DEFAULT_STATUS

    c = Contract(contract_no=contract_no, name=name, status=DEFAULT_STATUS)
    db.add(c)
    db.flush()
    _apply_updates(db, c, payload, note="新增合同")
    _apply_items(db, c, payload.get("items"))
    if "tags" in payload:
        _sync_tags(db, c, payload.get("tags") or [])
    return _fmt(c, db)


def _filtered_query(
    db: Session,
    *,
    include_deleted: bool = False,
    keyword: str | None = None,
    owner: str | None = None,
    status: str | None = None,
    contract_type: str | None = None,
    is_framework: bool | None = None,
    sign_from: str | None = None,
    sign_to: str | None = None,
    tags: str | None = None,
):
    """列表与导出共用的筛选查询（单一数据源，R7）。"""
    from datetime import date

    q = db.query(Contract)
    if not include_deleted:
        q = q.filter(Contract.deleted == False)  # noqa: E712
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(Contract.contract_no.like(like), Contract.name.like(like),
                         Contract.party_a.like(like), Contract.party_b.like(like),
                         Contract.items.any(or_(ContractItem.name.like(like),
                                                ContractItem.spec.like(like)))))
    if owner:
        q = q.filter(Contract.owner_name.like(f"%{owner}%"))
    if status:
        q = q.filter(Contract.status == status)
    if contract_type:
        q = q.filter(Contract.type == contract_type)
    if is_framework is not None:
        q = q.filter(Contract.is_framework == is_framework)
    if sign_from or sign_to:
        cond = []
        if sign_from:
            cond.append(Contract.sign_date >= date.fromisoformat(sign_from))
        if sign_to:
            cond.append(Contract.sign_date <= date.fromisoformat(sign_to))
        q = q.filter(*cond)
    if tags:
        tag_ids = [int(x) for x in tags.split(",") if x.strip().isdigit()]
        if tag_ids:
            q = (q.join(contract_tag)
                 .filter(contract_tag.c.tag_id.in_(tag_ids))
                 .group_by(Contract.id)
                 .having(func.count(contract_tag.c.contract_id) == len(tag_ids)))
    return q


@router.get("")
def list_contracts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, description="关键词：编号/名称/甲方/乙方 模糊"),
    status: str | None = Query(None),
    contract_type: str | None = Query(None, alias="type"),
    is_framework: bool | None = Query(None),
    include_deleted: bool = Query(False, description="是否含已停用（AC-15）"),
    owner: str | None = Query(None, description="经办人模糊"),
    tags: str | None = Query(None, description="逗号分隔的标签ID，取交集(包含全部所选, BR8)"),
    sign_from: str | None = Query(None, alias="sign_from", description="签订日期起 YYYY-MM-DD"),
    sign_to: str | None = Query(None, alias="sign_to", description="签订日期止 YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    q = _filtered_query(db, include_deleted=include_deleted, keyword=keyword, owner=owner,
                        status=status, contract_type=contract_type, is_framework=is_framework,
                        sign_from=sign_from, sign_to=sign_to, tags=tags)
    total = q.count()
    items = q.order_by(Contract.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_fmt(c, db) for c in items], "total": total, "page": page, "page_size": page_size}


@router.get("/{contract_id}")
def get_contract(contract_id: int, db: Session = Depends(get_db)):
    c = _get_contract(db, contract_id)
    data = _fmt(c, db)
    if c.is_framework:
        children = db.query(Contract).filter(Contract.parent_id == c.id, Contract.deleted == False).all()  # noqa: E712
        data["children"] = [
            {"id": ch.id, "contract_no": ch.contract_no, "name": ch.name,
             "amount": float(ch.amount) if ch.amount is not None else None,
             "status": ch.status, "owner_name": ch.owner_name} for ch in children
        ]
        data["children_count"] = len(children)
        data["children_amount_sum"] = float(sum((ch.amount or 0) for ch in children))
    return data


@router.put("/{contract_id}")
def update_contract(contract_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    c = _get_contract(db, contract_id)
    if c.deleted:
        raise HTTPException(status_code=400, detail="合同已停用，请先恢复")
    new_no = payload.get("contract_no")
    if new_no:
        dup = db.query(Contract).filter(Contract.contract_no == new_no, Contract.id != contract_id).first()
        if dup:
            raise HTTPException(status_code=409, detail="合同编号已存在")
    if payload.get("status") is not None and payload["status"] not in STATUSES:
        raise HTTPException(status_code=422, detail=f"无效状态: {payload['status']}")
    _apply_updates(db, c, payload)
    note = (payload.get("note") or "").strip()
    if note:
        _log(db, c, "备注", None, note)
        db.commit()
    _apply_items(db, c, payload.get("items"))
    if "tags" in payload:
        _sync_tags(db, c, payload.get("tags") or [])
    return _fmt(c, db)


@router.delete("/{contract_id}")
def delete_contract(contract_id: int, reason: str = Query(..., min_length=1, description="停用原因（必填，BR10）"),
                    db: Session = Depends(get_db)):
    c = _get_contract(db, contract_id)
    if c.deleted:
        raise HTTPException(status_code=400, detail="该合同已停用")
    c.deleted = True
    c.deleted_at = datetime.now()
    c.deleted_reason = reason
    _log(db, c, "deleted", False, True, note=reason)
    db.commit()
    return {"ok": True, "id": c.id}


@router.put("/{contract_id}/restore")
def restore_contract(contract_id: int, db: Session = Depends(get_db)):
    """恢复停用合同；超过 30 天保留期不可恢复（BR10/Q7，AC-15）。"""
    c = _get_contract(db, contract_id)
    if not c.deleted:
        return {"ok": True, "id": c.id, "message": "该合同未停用"}
    if c.deleted_at is None or (datetime.now() - c.deleted_at).days > RESTORE_DAYS:
        raise HTTPException(status_code=400, detail=f"已超过 {RESTORE_DAYS} 天保留期，无法恢复")
    c.deleted = False
    c.deleted_at = None
    c.deleted_reason = None
    _log(db, c, "deleted", True, False, note="恢复")
    db.commit()
    return {"ok": True, "id": c.id}


@router.get("/{contract_id}/logs")
def contract_logs(contract_id: int, db: Session = Depends(get_db)):
    from ..models import ChangeLog

    _get_contract(db, contract_id)
    logs = db.query(ChangeLog).filter(ChangeLog.contract_id == contract_id).order_by(ChangeLog.id.desc()).all()
    return [
        {"id": lg.id, "field_name": lg.field_name, "old_value": lg.old_value,
         "new_value": lg.new_value, "note": lg.note, "source": lg.source,
         "created_at": lg.created_at.isoformat() if lg.created_at else None}
        for lg in logs
    ]
