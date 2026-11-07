"""询价报价 API（CR-044，部门内部版）。

权限：沿用 `purchase.view` / `purchase.create`（不新增权限点）；
数据：询价行自由文本；供应商来自系统「供应商档案」；一家供应商一张单最多一份报价（可改）。
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models_auth import User
from ..models_master import Supplier
from ..models_rfq import QUOTE_CHANNELS, RFQ_STATUS, Rfq, RfqLine, RfqQuote, RfqQuoteItem
from ..models import KVSetting
from ..services import audit_service, numbering_service
from ..services.permission_service import require_perm
from .export import DOC_EXPORT_LIMIT, build_xlsx_response

router = APIRouter(prefix="/api/rfq", tags=["rfq"])

ZERO = Decimal("0")

PRINT_KEY = "rfq_print_template"
DEFAULT_PRINT_TEMPLATE: dict = {
    "title": "比 价 单",
    "orientation": "portrait",   # 默认一页竖向
    "sections": {"budget": True, "conditions": True, "scores": True,
                 "reason": True, "conclusion": True},
    "extra_rows": [{"label": "备注", "value": ""}],
    "signatures": ["制表人", "部门负责人", "单位负责人", "日期"],
    "footer_note": "",
}


def _load_print_template(db: Session) -> dict:
    row = db.get(KVSetting, PRINT_KEY)
    data = {**DEFAULT_PRINT_TEMPLATE, "sections": dict(DEFAULT_PRINT_TEMPLATE["sections"]),
            "extra_rows": [dict(r) for r in DEFAULT_PRINT_TEMPLATE["extra_rows"]],
            "signatures": list(DEFAULT_PRINT_TEMPLATE["signatures"])}
    if row is not None:
        try:
            stored = json.loads(row.value)
            if isinstance(stored, dict):
                data.update({k: v for k, v in stored.items() if k in data})
                if isinstance(stored.get("sections"), dict):
                    data["sections"] = {**data["sections"], **{
                        k: bool(v) for k, v in stored["sections"].items()
                        if k in data["sections"]}}
                if isinstance(stored.get("extra_rows"), list):
                    data["extra_rows"] = stored["extra_rows"]
                if isinstance(stored.get("signatures"), list):
                    data["signatures"] = [str(s) for s in stored["signatures"]]
        except (json.JSONDecodeError, TypeError):
            pass
    return data


def _validate_print_template(payload: dict) -> dict:
    data = _load_print_template_payload(payload)
    return data


def _load_print_template_payload(payload: dict) -> dict:
    base = dict(DEFAULT_PRINT_TEMPLATE)
    title = str(payload.get("title") or base["title"]).strip() or base["title"]
    if len(title) > 50:
        raise HTTPException(status_code=422, detail="标题不能超过 50 字")
    orientation = str(payload.get("orientation") or "portrait")
    if orientation not in ("portrait", "landscape"):
        raise HTTPException(status_code=422, detail="纸张方向只能是纵向/横向")
    sections = {}
    raw_sections = payload.get("sections") or {}
    for key in base["sections"]:
        sections[key] = bool(raw_sections.get(key, True))
    rows = []
    for i, row in enumerate(payload.get("extra_rows") or [], 1):
        if not isinstance(row, dict):
            raise HTTPException(status_code=422, detail=f"第 {i} 个自定义行格式错误")
        label = str(row.get("label") or "").strip()
        value = str(row.get("value") or "").strip()
        if not label and not value:
            continue
        if len(label) > 30 or len(value) > 300:
            raise HTTPException(status_code=422, detail=f"第 {i} 行文字过长")
        rows.append({"label": label, "value": value})
    if len(rows) > 20:
        raise HTTPException(status_code=422, detail="自定义行最多 20 行")
    footer = str(payload.get("footer_note") or "").strip()
    if len(footer) > 200:
        raise HTTPException(status_code=422, detail="页脚说明不能超过 200 字")
    # 签字栏：可自定义行数与文字（如增加“财务负责人”“见证人”）
    signatures = []
    raw_sigs = payload.get("signatures")
    if raw_sigs is None:
        signatures = list(DEFAULT_PRINT_TEMPLATE["signatures"])
    else:
        if not isinstance(raw_sigs, list):
            raise HTTPException(status_code=422, detail="签字栏格式错误")
        for i, item in enumerate(raw_sigs, 1):
            label = str(item or "").strip()
            if not label:
                continue
            if len(label) > 20:
                raise HTTPException(status_code=422, detail=f"签字栏第 {i} 项文字过长")
            signatures.append(label)
        if len(signatures) > 8:
            raise HTTPException(status_code=422, detail="签字栏最多 8 项")
    return {"title": title, "orientation": orientation, "sections": sections,
            "extra_rows": rows, "signatures": signatures, "footer_note": footer}


def _dec(value, field: str) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"{field}格式错误")


def _opt_dec(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="预算金额格式错误")


def _opt_score(value, field: str):
    if value in (None, ""):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{field}格式错误")
    if score < 0 or score > 10:
        raise HTTPException(status_code=422, detail=f"{field}应在 0~10 之间")
    return Decimal(str(score))


def _score_avg(quote) -> float | None:
    parts = [quote.price_score, quote.quality_score, quote.service_score]
    vals = [float(x) for x in parts if x is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace(" ", "T"))
    except ValueError:
        raise HTTPException(status_code=422, detail="日期时间格式错误（应为 YYYY-MM-DDTHH:MM）")


def _date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式错误（应为 YYYY-MM-DD）")


def _get(db: Session, rfq_id: int) -> Rfq:
    rfq = db.get(Rfq, rfq_id)
    if rfq is None:
        raise HTTPException(status_code=404, detail="询价单不存在")
    return rfq


def _fmt_header(rfq: Rfq) -> dict:
    return {
        "id": rfq.id, "doc_no": rfq.doc_no, "title": rfq.title, "project": rfq.project,
        "deadline": rfq.deadline.isoformat(sep=" ", timespec="minutes") if rfq.deadline else None,
        "status": rfq.status, "status_label": RFQ_STATUS.get(rfq.status, rfq.status),
        "remark": rfq.remark,
        "responsibility_dept": rfq.responsibility_dept,
        "budget_amount": float(rfq.budget_amount) if rfq.budget_amount is not None else None,
        "award_supplier_id": rfq.award_supplier_id,
        "award_supplier_name": rfq.award_supplier_name,
        "award_reason": rfq.award_reason,
        "award_conclusion": rfq.award_conclusion,
        "awarded_by_name": rfq.awarded_by_name,
        "awarded_at": rfq.awarded_at.isoformat(sep=" ", timespec="minutes") if rfq.awarded_at else None,
        "created_by_name": rfq.created_by_name,
        "published_at": rfq.published_at.isoformat(sep=" ", timespec="minutes") if rfq.published_at else None,
        "closed_at": rfq.closed_at.isoformat(sep=" ", timespec="minutes") if rfq.closed_at else None,
        "created_at": rfq.created_at.isoformat(sep=" ", timespec="minutes") if rfq.created_at else None,
        "line_count": len(rfq.lines or []),
        "quote_count": len(rfq.quotes or []),
    }


def _fmt_line(line: RfqLine) -> dict:
    return {"id": line.id, "seq": line.seq, "material_name": line.material_name,
            "spec": line.spec, "unit": line.unit, "qty": float(line.qty or 0),
            "need_date": line.need_date.isoformat() if line.need_date else None,
            "remark": line.remark}


def _fmt_quote(quote: RfqQuote) -> dict:
    return {"id": quote.id, "supplier_id": quote.supplier_id,
            "supplier_name": quote.supplier_name,
            "quote_date": quote.quote_date.isoformat() if quote.quote_date else None,
            "contact_name": quote.contact_name, "contact_phone": quote.contact_phone,
            "channel": quote.channel, "remark": quote.remark,
            "delivery_period": quote.delivery_period,
            "payment_terms": quote.payment_terms,
            "after_sales": quote.after_sales,
            "price_score": float(quote.price_score) if quote.price_score is not None else None,
            "quality_score": float(quote.quality_score) if quote.quality_score is not None else None,
            "service_score": float(quote.service_score) if quote.service_score is not None else None,
            "score_avg": _score_avg(quote),
            "items": [{"line_id": it.line_id, "unit_price": float(it.unit_price or 0),
                       "tax_rate": float(it.tax_rate or 0),
                       "moq": float(it.moq) if it.moq is not None else None,
                       "lead_days": it.lead_days, "remark": it.remark}
                      for it in (quote.items or [])]}


def _fmt_detail(rfq: Rfq) -> dict:
    return {**_fmt_header(rfq),
            "lines": [_fmt_line(x) for x in (rfq.lines or [])],
            "quotes": [_fmt_quote(q) for q in (rfq.quotes or [])]}


@router.get("", summary="询价单列表")
def list_rfqs(keyword: str | None = Query(None), status: str | None = Query(None),
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
              _user: User = Depends(require_perm("purchase.order.view")),
              db: Session = Depends(get_db)):
    q = db.query(Rfq)
    if status:
        q = q.filter(Rfq.status == status)
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        q = q.filter((Rfq.doc_no.like(like)) | (Rfq.title.like(like)) | (Rfq.project.like(like)))
    total = int(q.count() or 0)
    rows = q.order_by(Rfq.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_fmt_header(r) for r in rows], "total": total, "page": page,
            "page_size": page_size,
            "statuses": [{"code": k, "label": v} for k, v in RFQ_STATUS.items()]}


@router.post("", summary="新建询价单（草稿）")
def create_rfq(request: Request, payload: dict = Body(...),
               user: User = Depends(require_perm("purchase.order.create")),
               db: Session = Depends(get_db)):
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="询价单标题必填")
    rfq = Rfq(doc_no=numbering_service.next_doc_no(db, "rfq", date.today()),
              title=title, project=(str(payload.get("project") or "").strip() or None),
              responsibility_dept=(str(payload.get("responsibility_dept") or "").strip() or None),
              budget_amount=_opt_dec(payload.get("budget_amount")),
              deadline=_dt(payload.get("deadline")), remark=payload.get("remark"),
              status="draft", org_id=getattr(user, "org_id", None),
              created_by=getattr(user, "id", None),
              created_by_name=getattr(user, "real_name", None))
    rfq.lines = [_build_line(i, row) for i, row in enumerate(payload.get("lines") or [], 1)]
    db.add(rfq)
    db.commit()
    audit_service.log(db, user, module="purchase", action="create", object_type="rfq",
                      object_id=rfq.id, object_no=rfq.doc_no,
                      detail=f"新建询价单（{len(rfq.lines)} 行）", request=request)
    db.commit()
    return _fmt_detail(rfq)


def _build_line(seq: int, row: dict) -> RfqLine:
    name = str(row.get("material_name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail=f"第 {seq} 行：物料名称必填")
    qty = _dec(row.get("qty"), "数量")
    if qty <= 0:
        raise HTTPException(status_code=422, detail=f"第 {seq} 行：数量必须大于 0")
    return RfqLine(seq=seq, material_name=name,
                   spec=(str(row.get("spec") or "").strip() or None),
                   unit=(str(row.get("unit") or "").strip() or None),
                   qty=qty, need_date=_date(row.get("need_date")),
                   remark=(str(row.get("remark") or "").strip() or None))


@router.get("/export.xlsx", summary="询价单导出（当前筛选）")
def export_rfqs(keyword: str | None = Query(None), status: str | None = Query(None),
                _user: User = Depends(require_perm("purchase.order.view")),
                db: Session = Depends(get_db)):
    q = db.query(Rfq)
    if status:
        q = q.filter(Rfq.status == status)
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        q = q.filter((Rfq.doc_no.like(like)) | (Rfq.title.like(like)) | (Rfq.project.like(like)))
    rows = q.order_by(Rfq.id.desc()).limit(DOC_EXPORT_LIMIT).all()
    columns = [("单号", 18), ("标题", 28), ("项目", 20), ("截止时间", 20), ("状态", 10),
               ("行数", 8), ("报价家数", 10), ("创建人", 12), ("创建时间", 20)]
    data = [[r.doc_no, r.title, r.project or "",
             r.deadline.isoformat(sep=" ", timespec="minutes") if r.deadline else "",
             RFQ_STATUS.get(r.status, r.status), len(r.lines or []), len(r.quotes or []),
             r.created_by_name or "",
             r.created_at.isoformat(sep=" ", timespec="minutes") if r.created_at else ""]
            for r in rows]
    return build_xlsx_response("询价单", columns, data, "询价单")


@router.get("/print-template", summary="比价单打印模板（系统管理 · 打印模板）")
def get_print_template(_user: User = Depends(require_perm("purchase.order.view")),
                       db: Session = Depends(get_db)):
    return _load_print_template(db)


@router.put("/print-template", summary="保存比价单打印模板")
def save_print_template(payload: dict = Body(...),
                        _user: User = Depends(require_perm("purchase.order.create")),
                        db: Session = Depends(get_db)):
    data = _load_print_template_payload(payload)
    raw = json.dumps(data, ensure_ascii=False)
    row = db.get(KVSetting, PRINT_KEY)
    if row is None:
        db.add(KVSetting(key=PRINT_KEY, value=raw))
    else:
        row.value = raw
    db.commit()
    return _load_print_template(db)


@router.get("/{rfq_id}", summary="询价单详情（含各家报价）")
def get_rfq(rfq_id: int, _user: User = Depends(require_perm("purchase.order.view")),
            db: Session = Depends(get_db)):
    return _fmt_detail(_get(db, rfq_id))


@router.put("/{rfq_id}", summary="修改询价单（仅草稿）")
def update_rfq(rfq_id: int, request: Request, payload: dict = Body(...),
               user: User = Depends(require_perm("purchase.order.create")),
               db: Session = Depends(get_db)):
    rfq = _get(db, rfq_id)
    if rfq.status != "draft":
        raise HTTPException(status_code=422, detail="仅草稿可修改")
    if "title" in payload:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=422, detail="询价单标题必填")
        rfq.title = title
    if "project" in payload:
        rfq.project = str(payload.get("project") or "").strip() or None
    if "deadline" in payload:
        rfq.deadline = _dt(payload.get("deadline"))
    if "remark" in payload:
        rfq.remark = payload.get("remark")
    if "responsibility_dept" in payload:
        rfq.responsibility_dept = str(payload.get("responsibility_dept") or "").strip() or None
    if "budget_amount" in payload:
        rfq.budget_amount = _opt_dec(payload.get("budget_amount"))
    if "lines" in payload:
        rfq.lines = [_build_line(i, row) for i, row in enumerate(payload.get("lines") or [], 1)]
    db.commit()
    audit_service.log(db, user, module="purchase", action="edit", object_type="rfq",
                      object_id=rfq.id, object_no=rfq.doc_no, detail="修改询价单", request=request)
    db.commit()
    return _fmt_detail(rfq)


@router.delete("/{rfq_id}", summary="删除询价单（仅草稿）")
def delete_rfq(rfq_id: int, _user: User = Depends(require_perm("purchase.order.create")),
               db: Session = Depends(get_db)):
    rfq = _get(db, rfq_id)
    if rfq.status != "draft":
        raise HTTPException(status_code=422, detail="仅草稿可删除")
    db.delete(rfq)
    db.commit()
    return {"ok": True}


@router.post("/{rfq_id}/publish", summary="发布询价单（草稿→询价中）")
def publish_rfq(rfq_id: int, user: User = Depends(require_perm("purchase.order.create")),
                db: Session = Depends(get_db)):
    rfq = _get(db, rfq_id)
    if rfq.status != "draft":
        raise HTTPException(status_code=422, detail="仅草稿可发布")
    if not rfq.lines:
        raise HTTPException(status_code=422, detail="至少需要一行询价明细")
    rfq.status, rfq.published_at = "open", datetime.now()
    db.commit()
    return _fmt_header(rfq)


@router.post("/{rfq_id}/close", summary="截止询价单（询价中→已截止）")
def close_rfq(rfq_id: int, user: User = Depends(require_perm("purchase.order.create")),
              db: Session = Depends(get_db)):
    rfq = _get(db, rfq_id)
    if rfq.status != "open":
        raise HTTPException(status_code=422, detail="仅询价中可截止")
    rfq.status, rfq.closed_at = "closed", datetime.now()
    db.commit()
    return _fmt_header(rfq)


@router.put("/{rfq_id}/quotes/{supplier_id}", summary="录入/修改某供应商报价")
def upsert_quote(rfq_id: int, supplier_id: int, request: Request, payload: dict = Body(...),
                 user: User = Depends(require_perm("purchase.order.create")),
                 db: Session = Depends(get_db)):
    rfq = _get(db, rfq_id)
    if rfq.status == "draft":
        raise HTTPException(status_code=422, detail="询价单发布后才能录入报价")
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=422, detail="供应商不存在")
    channel = str(payload.get("channel") or "").strip() or None
    if channel and channel not in QUOTE_CHANNELS:
        raise HTTPException(status_code=422, detail="报价渠道不合法")

    quote = next((q for q in rfq.quotes if q.supplier_id == supplier_id), None)
    if quote is None:
        quote = RfqQuote(rfq_id=rfq.id, supplier_id=supplier_id,
                         supplier_name=supplier.name,
                         created_by=getattr(user, "id", None),
                         created_by_name=getattr(user, "real_name", None))
        db.add(quote)
    quote.supplier_name = supplier.name
    quote.quote_date = _date(payload.get("quote_date")) or date.today()
    quote.contact_name = (str(payload.get("contact_name") or "").strip() or None)
    quote.contact_phone = (str(payload.get("contact_phone") or "").strip() or None)
    quote.channel = channel
    quote.remark = payload.get("remark")
    quote.delivery_period = (str(payload.get("delivery_period") or "").strip() or None)
    quote.payment_terms = (str(payload.get("payment_terms") or "").strip() or None)
    quote.after_sales = (str(payload.get("after_sales") or "").strip() or None)
    quote.price_score = _opt_score(payload.get("price_score"), "价格评分")
    quote.quality_score = _opt_score(payload.get("quality_score"), "质量/技术评分")
    quote.service_score = _opt_score(payload.get("service_score"), "服务/货期评分")

    line_ids = {line.id for line in rfq.lines}
    existing = {it.line_id: it for it in (quote.items or [])}
    new_items: list[RfqQuoteItem] = []
    for row in payload.get("items") or []:
        try:
            line_id = int(row.get("line_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="报价行缺少 line_id")
        if line_id not in line_ids:
            raise HTTPException(status_code=422, detail=f"报价行不属于该询价单：{line_id}")
        price = _dec(row.get("unit_price"), "含税单价")
        if price < 0:
            raise HTTPException(status_code=422, detail="含税单价不能为负")
        item = existing.pop(line_id, None) or RfqQuoteItem(quote=quote, line_id=line_id)
        item.unit_price = price
        item.tax_rate = _dec(row.get("tax_rate", 13), "税率")
        moq = row.get("moq")
        item.moq = _dec(moq, "MOQ") if moq not in (None, "") else None
        lead = row.get("lead_days")
        item.lead_days = int(lead) if lead not in (None, "") else None
        item.remark = (str(row.get("remark") or "").strip() or None)
        new_items.append(item)
    quote.items = new_items
    db.commit()
    audit_service.log(db, user, module="purchase", action="quote", object_type="rfq",
                      object_id=rfq.id, object_no=rfq.doc_no,
                      detail=f"录入报价：{supplier.name}（{len(new_items)} 行）", request=request)
    db.commit()
    return _fmt_quote(quote)


@router.delete("/{rfq_id}/quotes/{quote_id}", summary="删除某供应商报价")
def delete_quote(rfq_id: int, quote_id: int,
                 _user: User = Depends(require_perm("purchase.order.create")),
                 db: Session = Depends(get_db)):
    rfq = _get(db, rfq_id)
    quote = next((q for q in rfq.quotes if q.id == quote_id), None)
    if quote is None:
        raise HTTPException(status_code=404, detail="报价不存在")
    db.delete(quote)
    db.commit()
    return {"ok": True}


@router.post("/{rfq_id}/award", summary="比价确认（定标）")
def award_rfq(rfq_id: int, payload: dict = Body(...),
              user: User = Depends(require_perm("purchase.order.create")),
              db: Session = Depends(get_db)):
    """我方确认中选供应商，填写推荐理由与结论；供打印比价单。"""
    rfq = _get(db, rfq_id)
    if rfq.status == "draft":
        raise HTTPException(status_code=422, detail="询价单发布后才能定标")
    supplier_id = payload.get("supplier_id")
    if supplier_id in (None, ""):
        # 取消定标
        rfq.award_supplier_id = None
        rfq.award_supplier_name = None
        rfq.award_reason = None
        rfq.award_conclusion = None
        rfq.awarded_by_name = None
        rfq.awarded_at = None
        db.commit()
        return _fmt_header(rfq)
    quote = next((q for q in (rfq.quotes or []) if q.supplier_id == int(supplier_id)), None)
    if quote is None:
        raise HTTPException(status_code=422, detail="该供应商尚未报价，不能定标")
    rfq.award_supplier_id = quote.supplier_id
    rfq.award_supplier_name = quote.supplier_name
    rfq.award_reason = (str(payload.get("reason") or "").strip() or None)
    rfq.award_conclusion = (str(payload.get("conclusion") or "").strip() or None)
    rfq.awarded_by_name = user.real_name or user.username
    rfq.awarded_at = datetime.now()
    db.commit()
    audit_service.log(db, user, module="purchase", action="award", object_type="rfq",
                      object_id=rfq.id, object_no=rfq.doc_no,
                      detail=f"比价定标：{quote.supplier_name}")
    db.commit()
    return _fmt_header(rfq)


@router.get("/{rfq_id}/compare", summary="比价报表（各行最低/次低/差额）")
def compare_rfq(rfq_id: int, _user: User = Depends(require_perm("purchase.order.view")),
                db: Session = Depends(get_db)):
    rfq = _get(db, rfq_id)
    quotes = rfq.quotes or []
    rows = []
    totals: dict[str, Decimal] = {}
    for line in rfq.lines or []:
        offers = []
        for q in quotes:
            hit = next((it for it in (q.items or []) if it.line_id == line.id), None)
            if hit is None or float(hit.unit_price or 0) <= 0:
                continue
            offers.append({"quote_id": q.id, "supplier_id": q.supplier_id,
                           "supplier_name": q.supplier_name,
                           "contact_phone": q.contact_phone,
                           "delivery_period": q.delivery_period,
                           "payment_terms": q.payment_terms,
                           "after_sales": q.after_sales,
                           "price_score": float(q.price_score) if q.price_score is not None else None,
                           "quality_score": float(q.quality_score) if q.quality_score is not None else None,
                           "service_score": float(q.service_score) if q.service_score is not None else None,
                           "score_avg": _score_avg(q),
                           "unit_price": float(hit.unit_price), "tax_rate": float(hit.tax_rate or 0),
                           "moq": float(hit.moq) if hit.moq is not None else None,
                           "lead_days": hit.lead_days,
                           "amount": float(_dec(hit.unit_price, "x") * (line.qty or 0))})
        offers.sort(key=lambda x: x["unit_price"])
        low = offers[0] if offers else None
        second = offers[1] if len(offers) > 1 else None
        diff = (second["unit_price"] - low["unit_price"]) if low and second else None
        diff_pct = (diff / low["unit_price"] * 100) if low and low["unit_price"] else None
        for offer in offers:
            totals[offer["supplier_name"]] = totals.get(offer["supplier_name"], ZERO) + \
                _dec(offer["amount"], "x")
        rows.append({**_fmt_line(line), "offers": offers,
                     "lowest": low, "second": second,
                     "diff": diff, "diff_pct": diff_pct})
    return {**_fmt_header(rfq), "rows": rows,
            "supplier_totals": [{"supplier_name": k, "amount": float(v)}
                                for k, v in sorted(totals.items(), key=lambda kv: kv[1])]}


