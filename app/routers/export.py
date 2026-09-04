"""Excel 台账导出 API（T10，对应 AC-11）。

GET /api/export/contracts.xlsx?<与列表一致的筛选参数>
复用 _filtered_query（单一数据源），导出当前筛选的全部结果。
"""
from __future__ import annotations

import io
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from ..database import get_db
from ..models import Contract
from .contracts import _filtered_query

router = APIRouter(prefix="/api/export", tags=["export"])

HEADERS = [
    "合同编号", "合同名称", "类型", "甲方", "乙方", "签订日期", "标的物",
    "合同金额", "币种", "累计已付", "付款比例%", "状态", "经办人",
    "到货状态", "预计到货日期", "是否框架", "所属框架编号",
    "质保金金额", "质保金比例%", "质保生效日期", "质保期限(月)", "质保到期日",
    "质保状态", "标签",
]


def _cell(c: Contract, col: int):
    mapping = [
        lambda: c.contract_no,
        lambda: c.name,
        lambda: c.type,
        lambda: c.party_a,
        lambda: c.party_b,
        lambda: c.sign_date.isoformat() if c.sign_date else "",
        lambda: c.subject_matter,
        lambda: float(c.amount) if c.amount is not None else "",
        lambda: c.currency,
        lambda: float(c.paid_amount) if c.paid_amount is not None else "",
        lambda: round(float(c.payment_ratio), 2) if c.payment_ratio is not None else "",
        lambda: c.status,
        lambda: c.owner_name or "",
        lambda: c.arrival_status,
        lambda: c.expected_arrival_date.isoformat() if c.expected_arrival_date else "",
        lambda: "是" if c.is_framework else "否",
        lambda: _parent_no(c),
        lambda: float(c.warranty_amount) if c.warranty_amount is not None else "",
        lambda: float(c.warranty_rate) if c.warranty_rate is not None else "",
        lambda: c.warranty_start.isoformat() if c.warranty_start else "",
        lambda: c.warranty_months or "",
        lambda: c.warranty_end.isoformat() if c.warranty_end else "",
        lambda: "已释放" if c.warranty_released else ("未处理" if c.has_warranty else ""),
        lambda: ",".join(t.name for t in c.tags),
    ]
    return mapping[col]()


@router.get("/contracts.xlsx")
def export_contracts(
    keyword: str | None = Query(None),
    status: str | None = Query(None),
    contract_type: str | None = Query(None, alias="type"),
    is_framework: bool | None = Query(None),
    include_deleted: bool = Query(False),
    owner: str | None = Query(None),
    tags: str | None = Query(None),
    sign_from: str | None = Query(None),
    sign_to: str | None = Query(None),
    db: Session = Depends(get_db),
):
    q = _filtered_query(db, include_deleted=include_deleted, keyword=keyword, owner=owner,
                        status=status, contract_type=contract_type, is_framework=is_framework,
                        sign_from=sign_from, sign_to=sign_to, tags=tags)
    contracts = q.order_by(Contract.id.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "合同台账"
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
    for c in contracts:
        ws.append([_cell(c, i) for i in range(len(HEADERS))])
    # 列宽
    widths = [14, 24, 8, 18, 18, 12, 22, 12, 8, 12, 10, 12, 10, 10, 13, 8, 16,
              12, 10, 13, 10, 12, 10, 18]
    for idx, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = w
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"合同台账_{date.today().isoformat()}.xlsx"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers=headers)


def _parent_no(c: Contract) -> str:
    # 延迟查询父合同编号（导出行数一般不大）
    if not c.parent_id:
        return ""
    if c.parent:
        return c.parent.contract_no
    return ""
