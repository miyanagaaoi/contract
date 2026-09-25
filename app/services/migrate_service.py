"""历史合同甲乙方文本 → 档案的迁移服务（T-V2-14 / AC-V2-34、35）。

背景（`11-erp-requirements.md` O14）：V1.0 合同的甲乙方是**纯文本**，V2.0 改为引用
客户/供应商档案。迁移**不强制**，采用"扫描生成草案 → 管理员认领 → 批量绑定"三步：

1. `scan_party_drafts`  扫描未绑定档案的合同，按（方向 + 文本）聚合生成 `party_drafts`；
2. `list_party_drafts`  认领页数据（含同名档案候选，便于"直接绑定已有档案"）；
3. `claim_party_draft`  认领：建立新档案（或绑定已有档案）并把匹配的历史合同批量写入 `customer_id`/`supplier_id`，
   同时为每张合同写一条变更历史（带操作人）。

未认领的合同继续使用文本字段（AC-V2-34：文本兜底，列表/详情/导出均正常）。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..dicts import type_code_of
from ..models import ChangeLog, Contract
from ..models_master import Customer, PartyDraft, Supplier
from . import master_service

# 类型码 → (档案方向, 合同文本字段)：采购合同乙方=供应商；销售合同甲方=客户
PARTY_RULES: dict[str, tuple[str, str]] = {
    "PUR": ("supplier", "party_b"),
    "SAL": ("customer", "party_a"),
}

_MODELS = {"customer": Customer, "supplier": Supplier}
_ID_FIELDS = {"customer": "customer_id", "supplier": "supplier_id"}
_LABELS = {"customer": "客户", "supplier": "供应商"}


def _direction_of(db: Session, contract: Contract) -> tuple[str, str] | None:
    """合同的档案方向（按标准类型码判定；"其他"类合同不参与迁移）。"""
    return PARTY_RULES.get(type_code_of(db, contract.type) or "")


def _iter_unbound(db: Session, kind: str, text_field: str):
    """产出（合同, 文本）——仅未绑定档案且文本非空、方向匹配的记录。"""
    id_field = _ID_FIELDS[kind]
    rows = db.query(Contract).filter(Contract.deleted == False).all()  # noqa: E712
    for contract in rows:
        if getattr(contract, id_field):
            continue
        rule = _direction_of(db, contract)
        if rule is None or rule[0] != kind:
            continue
        text = (getattr(contract, text_field) or "").strip()
        if text:
            yield contract, text


def scan_party_drafts(db: Session) -> dict:
    """扫描历史合同文本，生成/刷新迁移草案（幂等）。"""
    buckets: dict[tuple[str, str], int] = {}
    for kind, text_field in (("customer", "party_a"), ("supplier", "party_b")):
        for _contract, text in _iter_unbound(db, kind, text_field):
            buckets[(kind, text)] = buckets.get((kind, text), 0) + 1

    created = refreshed = 0
    for (kind, text), count in buckets.items():
        draft = (db.query(PartyDraft)
                 .filter(PartyDraft.party_type == kind, PartyDraft.raw_name == text)
                 .first())
        if draft is None:
            db.add(PartyDraft(party_type=kind, raw_name=text, contract_count=count,
                              status="pending"))
            created += 1
            continue
        draft.contract_count = count
        if draft.status == "claimed":
            # 已认领后又有合同使用同一文本 → 重新待认领
            draft.status = "pending"
            draft.matched_id = None
        refreshed += 1
    db.commit()
    return {
        "created": created,
        "refreshed": refreshed,
        "scanned": sum(buckets.values()),
        "pending": int(db.query(PartyDraft).filter(PartyDraft.status == "pending").count() or 0),
    }


def _fmt_draft(db: Session, draft: PartyDraft) -> dict:
    model = _MODELS[draft.party_type]
    matches = db.query(model).filter(model.name == draft.raw_name).all()
    return {
        "id": draft.id,
        "party_type": draft.party_type,
        "party_label": _LABELS[draft.party_type],
        "raw_name": draft.raw_name,
        "contract_count": draft.contract_count,
        "status": draft.status,
        "matched_id": draft.matched_id,
        "remark": draft.remark,
        "created_at": draft.created_at.isoformat(timespec="seconds") if draft.created_at else None,
        "candidates": [{"id": m.id, "code": m.code, "name": m.name, "status": m.status}
                       for m in matches],
    }


def list_party_drafts(db: Session, status: str = "pending") -> dict:
    query = db.query(PartyDraft)
    if status and status != "all":
        query = query.filter(PartyDraft.status == status)
    rows = query.order_by(PartyDraft.contract_count.desc(), PartyDraft.id.asc()).all()
    counts = {
        "pending": int(db.query(PartyDraft).filter(PartyDraft.status == "pending").count() or 0),
        "claimed": int(db.query(PartyDraft).filter(PartyDraft.status == "claimed").count() or 0),
        "ignored": int(db.query(PartyDraft).filter(PartyDraft.status == "ignored").count() or 0),
    }
    return {"items": [_fmt_draft(db, d) for d in rows], "total": len(rows), "counts": counts}


def _bind_contracts(db: Session, draft: PartyDraft, obj, user=None) -> int:
    """把匹配的历史合同批量绑定到档案，并逐张写变更历史。"""
    kind = draft.party_type
    id_field = _ID_FIELDS[kind]
    text_field = "party_b" if kind == "supplier" else "party_a"
    operator_id = getattr(user, "id", None)
    operator_name = getattr(user, "real_name", None)
    bound = 0
    for contract, text in list(_iter_unbound(db, kind, text_field)):
        if text != draft.raw_name:
            continue
        setattr(contract, id_field, obj.id)
        db.add(ChangeLog(
            contract_id=contract.id, field_name=id_field, old_value=None,
            new_value=f"{obj.name}（{obj.code}）", note="历史档案迁移认领",
            source="auto", operator_id=operator_id, operator_name=operator_name,
            object_type="contract", object_id=contract.id,
        ))
        bound += 1
    return bound


def claim_party_draft(db: Session, draft: PartyDraft, payload: dict, user=None) -> dict:
    """认领草案：`action=create` 新建档案（同名则直接绑定）或 `action=link` 绑定已有档案。"""
    if draft.status == "claimed":
        raise ValueError("该草案已认领")
    kind = draft.party_type
    model = _MODELS[kind]
    action = str(payload.get("action") or "create").strip().lower()

    if action == "link":
        try:
            target_id = int(payload.get("target_id") or 0)
        except (TypeError, ValueError):
            raise ValueError("目标档案 id 非法")
        obj = db.get(model, target_id)
        if obj is None:
            raise ValueError(f"{_LABELS[kind]}档案不存在")
    else:
        name = str(payload.get("name") or draft.raw_name).strip()
        if not name:
            raise ValueError("档案名称不能为空")
        obj = db.query(model).filter(model.name == name).first()
        if obj is None:
            extra = {"code": payload.get("code"), "contact_name": payload.get("contact_name"),
                     "contact_phone": payload.get("contact_phone")}
            obj = master_service.create_party(db, kind, {"name": name, **extra}, user)

    bound = _bind_contracts(db, draft, obj, user)
    draft.status = "claimed"
    draft.matched_id = obj.id
    draft.remark = f"已绑定 {bound} 张合同"
    db.commit()
    return {"draft": _fmt_draft(db, draft),
            "archive": master_service.fmt_party(kind, obj),
            "bound": bound}


def ignore_party_draft(db: Session, draft: PartyDraft, reason: str | None = None) -> dict:
    if draft.status == "claimed":
        raise ValueError("已认领的草案不能忽略")
    draft.status = "ignored"
    if reason:
        draft.remark = reason
    db.commit()
    return _fmt_draft(db, draft)


def get_draft(db: Session, draft_id: int) -> PartyDraft:
    draft = db.get(PartyDraft, draft_id)
    if draft is None:
        raise ValueError("迁移草案不存在")
    return draft
