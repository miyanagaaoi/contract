"""合同台账 API（T3，对应 AC-01/02/10/15；V2.0 接入权限与数据范围）。

接口与权限点（见 `12-erp-system-design.md` §6.1）：
- GET  /api/contracts/next-no           contract.create（编号预览，供新增表单）
- POST /api/contracts                   contract.create
- GET  /api/contracts                   contract.view（受数据范围过滤）
- GET  /api/contracts/{id}              contract.view
- PUT  /api/contracts/{id}              contract.edit
- DELETE /api/contracts/{id}            contract.delete（软删除 + 必填原因）
- PUT  /api/contracts/{id}/restore      contract.delete（30 天内可恢复）
- GET  /api/contracts/{id}/logs         contract.log.view

V2.0 变更：
- 每个端点显式声明按钮权限（**服务端强制**，前端隐藏不算边界，AC-V2-41）；
- 列表查询按登录用户的数据范围过滤（本人/本部门/本部门及下级/全部）；
- 新建合同时记录 `org_id`（归属组织快照）与 `created_by`（创建人）；
- 变更历史记录操作人（`operator_id` / `operator_name`），修订 01 BR12。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..dicts import get_enabled_subjects, type_code_of, type_label_of
from ..models import (
    FRAMEWORK_TAG,
    RESTORE_DAYS,
    STATUSES,
    Contract,
    ContractItem,
    Tag,
    compute_warranty_end,
    contract_tag,
)
from ..models_auth import User
from ..models_master import Customer, Supplier
from ..numbering import next_number
from ..services import audit_service, migrate_service
from ..services.permission_service import apply_data_scope, require_perm

router = APIRouter(prefix="/api/contracts", tags=["contracts"])

# 参与变更历史跟踪的字段（BR12；值变化即记录 时间/旧值/新值）
TRACKED_FIELDS = [
    "contract_no", "name", "type", "party_a", "party_b", "sign_date", "effective_date",
    "subject_matter", "amount", "currency", "subject_code", "paid_amount", "has_warranty",
    "warranty_amount", "warranty_rate", "warranty_start", "warranty_months",
    "warranty_end", "warranty_released", "warranty_release_date", "warranty_note",
    "is_framework", "parent_id", "arrival_status", "expected_arrival_date",
    "status", "owner_name", "remark",
    # ---- V2.0：往来单位档案（D6/D10）----
    "customer_id", "supplier_id",
]

_INT_FIELDS = {"warranty_months", "customer_id", "supplier_id"}
_BOOL_FIELDS = {"has_warranty", "warranty_released", "is_framework"}
_DECIMAL_FIELDS = {"amount", "paid_amount", "warranty_amount", "warranty_rate"}
_DATE_FIELDS = {
    "sign_date", "effective_date", "warranty_start", "warranty_end",
    "warranty_release_date", "expected_arrival_date",
}
# 允许显式置空（传 null）的字段；其余必填字段传 null 时忽略
_NULLABLE_FIELDS = {
    "sign_date", "effective_date", "parent_id", "expected_arrival_date", "subject_code",
    "warranty_amount", "warranty_rate", "warranty_start", "warranty_months",
    "warranty_end", "warranty_release_date", "warranty_note", "owner_name", "remark",
    "customer_id", "supplier_id",
}


def _log(db: Session, contract: Contract, field: str, old, new, note: str | None = None,
         source: str = "manual") -> None:
    """写变更历史：V2.0 起自动带上当前操作人（由 `get_current_user` 写入 `db.info`）。"""
    from ..models import ChangeLog

    user = (db.info or {}).get("user")
    db.add(ChangeLog(
        contract_id=contract.id, field_name=field,
        old_value=None if old is None else str(old),
        new_value=None if new is None else str(new),
        note=note, source=source,
        operator_id=getattr(user, "id", None),
        operator_name=getattr(user, "real_name", None),
        object_type="contract", object_id=contract.id,
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


def _apply_party_refs(db: Session, payload: dict) -> None:
    """往来单位档案化（T-V2-13 / AC-V2-33）。

    - `customer_id` 对应甲方（销售合同）、`supplier_id` 对应乙方（采购合同）；
    - 传了 id 但档案不存在 → 422（防止脏引用）；
    - 未显式提供对应文本时用**档案名回填文本快照**；其他类型合同可继续用纯文本（AC-V2-34）。
    """
    if payload.get("customer_id"):
        try:
            customer_id = int(payload["customer_id"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="客户档案 id 非法")
        customer = db.get(Customer, customer_id)
        if customer is None:
            raise HTTPException(status_code=422, detail="客户档案不存在")
        payload["customer_id"] = customer.id
        if not str(payload.get("party_a") or "").strip():
            payload["party_a"] = customer.name
    if payload.get("supplier_id"):
        try:
            supplier_id = int(payload["supplier_id"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="供应商档案 id 非法")
        supplier = db.get(Supplier, supplier_id)
        if supplier is None:
            raise HTTPException(status_code=422, detail="供应商档案不存在")
        payload["supplier_id"] = supplier.id
        if not str(payload.get("party_b") or "").strip():
            payload["party_b"] = supplier.name


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
    # V2.0：往来单位档案名称（T-V2-13，列表/详情显示档案名；未绑定时回落到文本快照）
    customer = db.get(Customer, c.customer_id) if (db is not None and c.customer_id) else None
    supplier = db.get(Supplier, c.supplier_id) if (db is not None and c.supplier_id) else None
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
        "subject_code": c.subject_code,
        "customer_id": c.customer_id,
        "customer_name": customer.name if customer else None,
        "customer_code": customer.code if customer else None,
        "supplier_id": c.supplier_id,
        "supplier_name": supplier.name if supplier else None,
        "supplier_code": supplier.code if supplier else None,
        "org_id": c.org_id,
        "created_by": c.created_by,
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


def subject_code_normalize(value: str, subjects: list[dict]) -> str:
    """主体值（码或名称）→ 标准主体码；缺省取第一个可用主体。"""
    v = (value or "").strip()
    if not v:
        if not subjects:
            raise HTTPException(status_code=422, detail="请先在系统设置中配置我方公司")
        return subjects[0]["code"]
    hit = next((s for s in subjects if v.upper() == s["code"] or v == s["name"]), None)
    if hit is None:
        raise HTTPException(status_code=422, detail=f"未知主体：{v}")
    return hit["code"]


def _get_contract(db: Session, contract_id: int) -> Contract:
    c = db.get(Contract, contract_id)
    if c is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    return c


# ---------- 自动标签（框架 MVP2 ④ / 类型 MVP3）：auto=True 可区分"自动附加" ----------

def _ensure_auto_tag(db: Session, contract: Contract, tag_name: str, color: str | None = None) -> None:
    """给合同附加自动标签并标记 auto（字典无则创建）。"""
    tag = db.query(Tag).filter(Tag.name == tag_name).first()
    if tag is None:
        tag = Tag(name=tag_name, color=color)
        db.add(tag)
        db.flush()
    if all(t.id != tag.id for t in contract.tags):
        contract.tags.append(tag)
        db.flush()
    db.execute(contract_tag.update().where(and_(
        contract_tag.c.contract_id == contract.id,
        contract_tag.c.tag_id == tag.id,
    )).values(auto=True))
    db.commit()


def _remove_auto_tag(db: Session, contract: Contract, tag_name: str) -> None:
    """移除合同上【自动附加】的指定标签（手动添加的 auto=False 保留）。"""
    sub = db.query(Tag.id).filter(Tag.name == tag_name)
    db.execute(contract_tag.delete().where(and_(
        contract_tag.c.contract_id == contract.id,
        contract_tag.c.tag_id.in_(sub),
        contract_tag.c.auto == True,  # noqa: E712
    )))
    db.commit()
    db.expire_all()


def _sync_type_tag(db: Session, contract: Contract, old_type_label: str) -> None:
    """合同类型 → 自动"类型名"标签（MVP3）：类型变化时移除旧自动标签、附加新类型名标签。"""
    new_label = contract.type or ""
    if old_type_label and old_type_label != new_label:
        _remove_auto_tag(db, contract, old_type_label)
    code = type_code_of(db, new_label)
    if code and code != "OTH":
        _ensure_auto_tag(db, contract, type_label_of(db, code), color="#67c23a")


def _finalize_framework(db: Session, contract: Contract) -> None:
    """在字段/手工标签落库后统一处理框架标签（确保顺序：tags 已替换完再调用）。"""
    is_fw = bool(contract.is_framework) and contract.parent_id is None
    if is_fw:
        _ensure_auto_tag(db, contract, FRAMEWORK_TAG, color="#409eff")
    else:
        _remove_auto_tag(db, contract, FRAMEWORK_TAG)
        if contract.parent_id is not None and not contract.is_framework:
            # 子合同继承【框架合同】标识
            _ensure_auto_tag(db, contract, FRAMEWORK_TAG, color="#409eff")


def _assert_parent_allowed(db: Session, is_framework: bool, parent_id) -> None:
    """在改动落库前校验绑定关系（BR6/MVP2）：框架不能挂框架；只能挂到框架下。"""
    if parent_id is None:
        return
    if is_framework:
        raise HTTPException(status_code=422, detail="框架合同不能再挂到其他框架下")
    parent = db.get(Contract, parent_id)
    if parent is None or parent.deleted:
        raise HTTPException(status_code=422, detail="所属框架不存在或已停用")
    if not parent.is_framework:
        raise HTTPException(status_code=422, detail="只能挂到框架合同（is_framework=是）下")


@router.get("/next-no", tags=["contracts"])
def preview_number(
    type_label_or_code: str = Query("", alias="type", description="合同类型 label 或 code"),
    subject: str = Query("", description="主体码(如 ZC)或主体名称"),
    sign_date: str | None = Query(None, description="签订日期 YYYY-MM-DD(缺省=今天)"),
    _user: User = Depends(require_perm("contract.create")),
    db: Session = Depends(get_db),
):
    """自动编号预览（不占号）。"""
    from datetime import date

    code = type_code_of(db, type_label_or_code)
    if not code or code == "OTH":
        raise HTTPException(status_code=422, detail="该类型暂不支持自动编号")
    subjects = get_enabled_subjects(db)
    sub = next((s for s in subjects if subject.upper() == s["code"] or subject == s["name"]), None)
    if sub is None:
        raise HTTPException(status_code=422, detail="请选择有效主体（我方公司）")
    ref = None
    if sign_date:
        try:
            ref = date.fromisoformat(sign_date[:10])
        except ValueError:
            ref = None
    no = next_number(db, code, sub["code"], ref)
    return {"contract_no": no, "type_code": code, "subject_code": sub["code"], "preview": True}


@router.post("")
def create_contract(request: Request, payload: dict = Body(...),
                    user: User = Depends(require_perm("contract.create")),
                    db: Session = Depends(get_db)):
    payload = dict(payload)
    # MVP3：类型规范化（旧标签/代码 → 标准类型 label）
    tcode = type_code_of(db, payload.get("type") or "")
    if tcode:
        payload["type"] = type_label_of(db, tcode)
    # BR1：编号必填且唯一；未填编号时按规则自动生成
    contract_no = (payload.get("contract_no") or "").strip()
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="合同名称必填")
    if not contract_no:
        if not tcode or tcode == "OTH":
            raise HTTPException(status_code=422, detail="该类型暂不支持自动编号，请选择其他类型")
        subjects = get_enabled_subjects(db)
        sc = subject_code_normalize(payload.get("subject_code") or "", subjects)
        from datetime import date

        ref = None
        if payload.get("sign_date"):
            try:
                ref = date.fromisoformat(str(payload["sign_date"])[:10])
            except ValueError:
                ref = None
        contract_no = next_number(db, tcode, sc, ref)
        payload["contract_no"] = contract_no
        payload["subject_code"] = sc
    if not contract_no:
        raise HTTPException(status_code=422, detail="合同编号不能为空")
    exists = db.query(Contract).filter(Contract.contract_no == contract_no).first()
    if exists:
        raise HTTPException(status_code=409, detail="合同编号已存在（自动编号被占用，请重新生成）")
    _assert_parent_allowed(db, bool(payload.get("is_framework")), payload.get("parent_id"))
    _apply_party_refs(db, payload)
    from ..models import DEFAULT_STATUS

    # V2.0：记录归属组织（数据范围快照）与创建人（审计）
    c = Contract(contract_no=contract_no, name=name, status=DEFAULT_STATUS,
                 org_id=getattr(user, "org_id", None), created_by=getattr(user, "id", None))
    db.add(c)
    db.flush()
    _apply_updates(db, c, payload, note="新增合同")
    _apply_items(db, c, payload.get("items"))
    if "tags" in payload:
        _sync_tags(db, c, payload.get("tags") or [])
    _finalize_framework(db, c)
    _sync_type_tag(db, c, "")
    audit_service.log(db, user, module="contract", action="create",
                      object_type="contract", object_id=c.id, object_no=c.contract_no,
                      detail=f"新增合同：{c.name}", request=request)
    db.commit()
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
    user: User | None = None,
):
    """列表与导出共用的筛选查询（单一数据源，R7）。

    `user` 非空时按数据范围过滤（V2.0，BR-V2-08）。
    """
    from datetime import date

    q = db.query(Contract)
    if user is not None:
        q = apply_data_scope(q, Contract, user, db)
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
    tree: bool = Query(False, description="框架树视图：忽略分页，输出 框架行+子行+独立合同 扁平列表"),
    user: User = Depends(require_perm("contract.view")),
    db: Session = Depends(get_db),
):
    q = _filtered_query(db, include_deleted=include_deleted, keyword=keyword, owner=owner,
                        status=status, contract_type=contract_type, is_framework=is_framework,
                        sign_from=sign_from, sign_to=sign_to, tags=tags, user=user)
    if tree:
        from collections import defaultdict

        matched = q.order_by(Contract.id.asc()).all()
        fw_ids = {c.id for c in matched if c.is_framework}
        for c in matched:
            if c.parent_id:
                fw_ids.add(c.parent_id)
        fws = (db.query(Contract)
               .filter(Contract.deleted == False,  # noqa: E712
                       Contract.id.in_(fw_ids or {-1}))
               .order_by(Contract.id).all())
        fids = [f.id for f in fws]
        children: dict[int, list[Contract]] = defaultdict(list)
        if fids:
            for ch in (db.query(Contract)
                       .filter(Contract.deleted == False,  # noqa: E712
                               Contract.parent_id.in_(fids))
                       .order_by(Contract.id).all()):
                children[ch.parent_id].append(ch)
        out: list[dict] = []
        shown: set[int] = set()
        for f in fws:
            row = _fmt(f, db)
            row["tree"] = "f"  # 框架行
            row["children_count"] = len(children.get(f.id, []))
            out.append(row)
            shown.add(f.id)
            for ch in children.get(f.id, []):
                r = _fmt(ch, db)
                r["tree"] = "c"  # 子行
                out.append(r)
                shown.add(ch.id)
        stand = [c for c in matched if c.parent_id is None and not c.is_framework and c.id not in shown]
        for c in sorted(stand, key=lambda x: x.id, reverse=True):
            r = _fmt(c, db)
            r["tree"] = "s"  # 独立合同
            out.append(r)
        return {"items": out, "total": len(fws) + len(stand), "tree": True, "page": 1, "page_size": len(out)}
    total = q.count()
    items = q.order_by(Contract.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_fmt(c, db) for c in items], "total": total, "page": page, "page_size": page_size}


# ==================== 历史甲乙方档案迁移（T-V2-14 / AC-V2-34、35） ====================
# 注意：以下静态路径必须定义在 `/{contract_id}` 之前，否则会被路径参数捕获。

def _migrate_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/migrate-parties", tags=["contracts"])
def migrate_parties(request: Request,
                    user: User = Depends(require_perm("contract.edit")),
                    db: Session = Depends(get_db)):
    """一次性扫描历史合同的甲乙方文本，生成"待认领"迁移草案（幂等，可重复执行）。"""
    result = _migrate_call(migrate_service.scan_party_drafts, db)
    audit_service.log(db, user, module="contract", action="migrate_scan",
                      object_type="party_draft",
                      detail=f"扫描历史甲乙方文本：新增草案 {result['created']} 条，"
                             f"刷新 {result['refreshed']} 条，待认领 {result['pending']} 条",
                      request=request)
    db.commit()
    return result


@router.get("/party-drafts", tags=["contracts"])
def party_drafts(status: str = Query("pending", description="pending / claimed / ignored / all"),
                 _user: User = Depends(require_perm("contract.edit")),
                 db: Session = Depends(get_db)):
    """迁移草案列表（认领页数据，含同名档案候选）。"""
    return migrate_service.list_party_drafts(db, status)


@router.post("/party-drafts/{draft_id}/claim", tags=["contracts"])
def claim_party_draft(draft_id: int, request: Request, payload: dict = Body(default={}),
                      user: User = Depends(require_perm("contract.edit")),
                      db: Session = Depends(get_db)):
    """认领草案：新建档案（同名直接绑定）或绑定已有档案，并批量绑定历史合同。"""
    draft = _migrate_call(migrate_service.get_draft, db, draft_id)
    result = _migrate_call(migrate_service.claim_party_draft, db, draft, payload or {}, user)
    audit_service.log(db, user, module="contract", action="migrate_claim",
                      object_type="party_draft", object_id=draft_id,
                      object_no=result["archive"]["code"],
                      detail=f"认领草案「{result['draft']['raw_name']}」→ {result['archive']['name']}，"
                             f"绑定合同 {result['bound']} 张",
                      request=request)
    db.commit()
    return result


@router.post("/party-drafts/{draft_id}/ignore", tags=["contracts"])
def ignore_party_draft(draft_id: int, request: Request, payload: dict = Body(default={}),
                       user: User = Depends(require_perm("contract.edit")),
                       db: Session = Depends(get_db)):
    """忽略草案（视为无需建档的历史文本，保留合同文本兜底）。"""
    draft = _migrate_call(migrate_service.get_draft, db, draft_id)
    data = _migrate_call(migrate_service.ignore_party_draft, db, draft,
                         (payload or {}).get("reason"))
    audit_service.log(db, user, module="contract", action="migrate_ignore",
                      object_type="party_draft", object_id=draft_id,
                      detail=f"忽略迁移草案「{draft.raw_name}」", request=request)
    db.commit()
    return data


@router.get("/{contract_id}")
def get_contract(contract_id: int,
                 user: User = Depends(require_perm("contract.view")),
                 db: Session = Depends(get_db)):
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
def update_contract(contract_id: int, request: Request, payload: dict = Body(...),
                    user: User = Depends(require_perm("contract.edit")),
                    db: Session = Depends(get_db)):
    c = _get_contract(db, contract_id)
    if c.deleted:
        raise HTTPException(status_code=400, detail="合同已停用，请先恢复")
    new_no = payload.get("contract_no")
    if new_no:
        dup = db.query(Contract).filter(Contract.contract_no == new_no, Contract.id != contract_id).first()
        if dup:
            raise HTTPException(status_code=409, detail="合同编号已存在")
    if "parent_id" in payload:
        _assert_parent_allowed(db, bool(payload.get("is_framework", c.is_framework)), payload["parent_id"])
    elif bool(payload.get("is_framework", c.is_framework)) and c.parent_id is not None:
        raise HTTPException(status_code=422, detail="请先解除与上级框架的绑定，再标记为框架合同")
    if payload.get("is_framework") is False and c.is_framework:
        has_children = db.query(Contract.id).filter(
            Contract.parent_id == c.id, Contract.deleted == False  # noqa: E712
        ).first()
        if has_children:
            raise HTTPException(status_code=422, detail="框架下仍有子合同，请先解除子合同")
    if payload.get("status") is not None and payload["status"] not in STATUSES:
        raise HTTPException(status_code=422, detail=f"无效状态: {payload['status']}")
    # MVP3：类型规范化（保存时旧标签/代码统一为当前字典的标准类型名）
    old_type_label = c.type or ""
    if payload.get("type"):
        tcode = type_code_of(db, payload["type"])
        if tcode:
            payload["type"] = type_label_of(db, tcode)
    if payload.get("subject_code") is not None:
        payload["subject_code"] = subject_code_normalize(
            payload["subject_code"], get_enabled_subjects(db))
    _apply_party_refs(db, payload)
    _apply_updates(db, c, payload)
    note = (payload.get("note") or "").strip()
    if note:
        _log(db, c, "备注", None, note)
        db.commit()
    _apply_items(db, c, payload.get("items"))
    if "tags" in payload:
        _sync_tags(db, c, payload.get("tags") or [])
    _finalize_framework(db, c)
    _sync_type_tag(db, c, old_type_label)
    audit_service.log(db, user, module="contract", action="edit",
                      object_type="contract", object_id=c.id, object_no=c.contract_no,
                      request=request)
    db.commit()
    return _fmt(c, db)


@router.delete("/{contract_id}")
def delete_contract(contract_id: int, request: Request,
                    reason: str = Query(..., min_length=1, description="停用原因（必填，BR10）"),
                    user: User = Depends(require_perm("contract.delete")),
                    db: Session = Depends(get_db)):
    c = _get_contract(db, contract_id)
    if c.deleted:
        raise HTTPException(status_code=400, detail="该合同已停用")
    c.deleted = True
    c.deleted_at = datetime.now()
    c.deleted_reason = reason
    _log(db, c, "deleted", False, True, note=reason)
    audit_service.log(db, user, module="contract", action="disable",
                      object_type="contract", object_id=c.id, object_no=c.contract_no,
                      detail=reason, request=request)
    db.commit()
    return {"ok": True, "id": c.id}


@router.put("/{contract_id}/restore")
def restore_contract(contract_id: int, request: Request,
                     user: User = Depends(require_perm("contract.delete")),
                     db: Session = Depends(get_db)):
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
    audit_service.log(db, user, module="contract", action="restore",
                      object_type="contract", object_id=c.id, object_no=c.contract_no,
                      request=request)
    db.commit()
    return {"ok": True, "id": c.id}


@router.get("/{contract_id}/logs")
def contract_logs(contract_id: int,
                  _user: User = Depends(require_perm("contract.log.view")),
                  db: Session = Depends(get_db)):
    from ..models import ChangeLog

    _get_contract(db, contract_id)
    logs = db.query(ChangeLog).filter(ChangeLog.contract_id == contract_id).order_by(ChangeLog.id.desc()).all()
    return [
        {"id": lg.id, "field_name": lg.field_name, "old_value": lg.old_value,
         "new_value": lg.new_value, "note": lg.note, "source": lg.source,
         "operator_id": lg.operator_id, "operator_name": lg.operator_name,
         "created_at": lg.created_at.isoformat() if lg.created_at else None}
        for lg in logs
    ]
