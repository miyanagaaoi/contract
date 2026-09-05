"""合同批量导入 API（MVP2 需求②：按系统模板新建导入）。

- GET  /api/import/template.xlsx            下载系统导入模板
- POST /api/import/contracts                上传填写好的模板，仅新建；错误行整条跳过并返回报告
"""
from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Contract
from .contracts import create_contract

router = APIRouter(prefix="/api/import", tags=["import"])

MAIN_HEAD = ["合同编号", "合同名称", "类型", "甲方", "乙方", "签订日期", "金额",
             "已付金额", "经办人", "状态", "所属框架编号", "是否框架", "标签(逗号分隔)", "备注",
             "质保金额", "质保比例%", "质保生效日期", "质保期限(月)"]
ITEMS_HEAD = ["合同编号(对应主档)", "序号", "类型", "名称", "规格型号", "数量", "单价", "备注"]

MAIN_SAMPLE = [
    ["CG-2026-101", "示例：新购设备合同", "采购", "本公司（甲方示例）", "XX 供应商", "2026-09-01", None, 0, "张三", "内部审批中", None, "否", "采购,项目A", "", 6600, 5, "2026-09-01", 12],
    ["XS-2026-201", "示例：产品销售", "销售", "客户 M 公司", "本公司（乙方示例）", "2026-09-05", None, 6000, "李四", "到货", None, "否", "销售", "", 300, 5, "2026-09-05", 12],
]
ITEMS_SAMPLE = [
    ["CG-2026-101", 1, "采购", "X 系列设备", "X-2000", 10, 12000, "含安装调试"],
    ["CG-2026-101", 2, "采购", "配套耗材", "HC-02", 2, 6000, ""],
    ["XS-2026-201", 1, "销售", "X 设备(整机)", "X-2000", 1, 6000, "已收款"],
]

LIMIT_MAIN = 2000


def _style(ws, headers):
    ws.append(headers)
    from openpyxl.styles import Font, PatternFill

    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
    ws.freeze_panes = "A2"


def build_template_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "合同(主档)"
    _style(ws, MAIN_HEAD)
    for row in MAIN_SAMPLE:
        ws.append(row)
    ws2 = wb.create_sheet("行项明细")
    _style(ws2, ITEMS_HEAD)
    for row in ITEMS_SAMPLE:
        ws2.append(row)
    note = wb.create_sheet("填写说明")
    tips = [
        "填写说明：",
        "1. 必填：合同编号（唯一，不可与库内重复）、合同名称；类型/甲方/乙方/签订日期 建议都填。",
        "2. 两个工作表都要填：『合同(主档)』每行一个合同；『行项明细』按合同编号挂行（同一合同序号连续）。",
        "3. 金额/数量/单价/比例只填数字；日期填 YYYY-MM-DD。",
        "4. 金额留空 = 由行项合计自动计算（推荐）；若合同没有行项，金额必须手填。",
        "5. 标签列多个标签用英文逗号分隔；系统不存在的标签会自动创建。",
        "6. 状态可选：内部审批中/集团审批中/已签订/付款中/发货/到货/已终止（留空默认内部审批中）。",
        "7. 是否框架：是/否；所属框架编号填已存在框架合同的编号（子合同可挂到框架下）。",
        "8. 同一合同编号只出现一次：文件内重复、与库内重复、必填缺失、格式错误的行会整条跳过并写入错误报告。",
        "9. 示例行请整行删除后再填写；上线前先用真实数据试 3~5 条。",
    ]
    for t in tips:
        note.append([t])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _clean(s) -> str:
    return "" if s is None else str(s).strip()


def _to_date(v):
    if v is None or _clean(v) == "":
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = _clean(v)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"日期格式应为 YYYY-MM-DD：{s}")


def _to_dec(v, field: str, allow_none: bool = False) -> Decimal | None:
    if v is None or _clean(v) == "":
        if allow_none:
            return None
        raise ValueError(f"字段 {field} 必填")
    try:
        return Decimal(str(v).replace(",", "").strip())
    except InvalidOperation:
        raise ValueError(f"字段 {field} 应为数字：{v}")


def _read_rows(sheet):
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return [], []
    headers = [_clean(h) for h in rows[0]]
    data = []
    for idx, row in enumerate(rows[1:], start=2):
        if all((v is None or _clean(v) == "") for v in row):
            continue
        data.append((idx, {headers[j]: row[j] for j in range(min(len(headers), len(row)))}))
    return headers, data


def _parse_main(row: dict) -> dict:
    contract_no = _clean(row.get("合同编号"))
    name = _clean(row.get("合同名称"))
    if not contract_no or not name:
        raise ValueError("合同编号与合同名称必填")
    status = _clean(row.get("状态")) or "内部审批中"
    amount = _to_dec(row.get("金额"), "金额", allow_none=True)
    payload: dict = {
        "contract_no": contract_no,
        "name": name,
        "type": _clean(row.get("类型")) or "采购",
        "party_a": _clean(row.get("甲方")),
        "party_b": _clean(row.get("乙方")),
        "sign_date": _to_date(row.get("签订日期")),
        "paid_amount": _to_dec(row.get("已付金额"), "已付金额", allow_none=True) or Decimal("0"),
        "owner_name": _clean(row.get("经办人")) or None,
        "status": status,
        "remark": _clean(row.get("备注")) or None,
        "is_framework": _clean(row.get("是否框架")).startswith("是"),
    }
    tag_txt = _clean(row.get("标签(逗号分隔)"))
    payload["tags"] = [t.strip() for t in tag_txt.split(",") if t.strip()] if tag_txt else []
    w_amount = _to_dec(row.get("质保金额"), "质保金额", allow_none=True)
    w_rate = _to_dec(row.get("质保比例%"), "质保比例%", allow_none=True)
    w_start = _to_date(row.get("质保生效日期"))
    w_months = row.get("质保期限(月)")
    if w_amount or w_rate or w_start or w_months not in (None, ""):
        payload["has_warranty"] = True
        payload["warranty_amount"] = float(w_amount) if w_amount is not None else None
        payload["warranty_rate"] = float(w_rate) if w_rate is not None else None
        payload["warranty_start"] = w_start
        try:
            payload["warranty_months"] = int(w_months) if w_months not in (None, "") else None
        except (ValueError, TypeError):
            raise ValueError(f"质保期限(月)应为整数：{w_months}")
    else:
        payload["has_warranty"] = False
    # 所属框架（按编号查询）
    parent_no = _clean(row.get("所属框架编号"))
    payload["_parent_no"] = parent_no
    payload["_amount_or_items"] = amount  # items 为空时使用
    return payload


def _parse_items(db: Session, sheet_rows) -> dict[str, list[dict]]:
    grouped: dict[str, list] = {}
    for _, row in sheet_rows:
        no = _clean(row.get("合同编号(对应主档)") or row.get("合同编号"))
        if not no:
            continue
        qty = _to_dec(row.get("数量"), "数量", allow_none=True)
        price = _to_dec(row.get("单价"), "单价", allow_none=True)
        name = _clean(row.get("名称"))
        item = {
            "item_type": _clean(row.get("类型")) or "采购",
            "name": name,
            "spec": _clean(row.get("规格型号")),
            "qty": float(qty) if qty is not None else 0,
            "unit_price": float(price) if price is not None else 0,
            "remark": _clean(row.get("备注")) or None,
        }
        if not name and not item["qty"] and not item["unit_price"] and not item["spec"]:
            continue
        grouped.setdefault(no, []).append(item)
    return grouped


@router.get("/template.xlsx")
def download_template():
    buf = io.BytesIO(build_template_bytes())
    filename = "合同导入模板.xlsx"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers=headers)


@router.post("/contracts")
async def import_contracts(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    try:
        wb = load_workbook(io.BytesIO(content), data_only=True)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="无法解析文件，请使用系统模板（.xlsx）")

    sheet_names = {n: n for n in wb.sheetnames}
    main_name = next((n for n in wb.sheetnames if n.startswith("合同")), None)
    items_name = next((n for n in wb.sheetnames if n.startswith("行项")), None)
    if main_name is None:
        raise HTTPException(status_code=422, detail="模板缺少『合同(主档)』工作表")

    _, main_rows = _read_rows(wb[main_name])
    items_grouped = _parse_items(db, _read_rows(wb[items_name])[1] if items_name else [])
    if len(main_rows) > LIMIT_MAIN:
        raise HTTPException(status_code=422, detail=f"单次最多导入 {LIMIT_MAIN} 条合同")

    errors: list[dict] = []
    success = 0
    seen: set[str] = set()

    for sheet_row, row in main_rows:
        no = _clean(row.get("合同编号"))
        try:
            if not no:
                raise ValueError("合同编号必填")
            payload = _parse_main(row)
            if payload["contract_no"] in seen:
                raise ValueError("文件内合同编号重复")
            if db.query(Contract).filter(Contract.contract_no == no).first():
                raise ValueError("合同编号与库内已有合同重复")

            # 行项 & 金额口径：有行项→Σ自动；无行项→金额必填（可手填）
            items = items_grouped.get(no, [])
            if items:
                payload["items"] = items
            else:
                amount = payload.pop("_amount_or_items")
                if amount is None or amount <= 0:
                    raise ValueError("该合同没有行项，金额必须填写")
                payload["amount"] = float(amount)

            parent_no = payload.pop("_parent_no", "") or ""
            if parent_no:
                parent = db.query(Contract).filter(Contract.contract_no == parent_no).first()
                if parent is None or parent.deleted or not parent.is_framework:
                    raise ValueError(f"所属框架编号不存在或不是框架合同：{parent_no}")
                payload["parent_id"] = parent.id

            if payload["is_framework"] and payload.get("parent_id"):
                raise ValueError("框架合同不能同时挂到其他框架下")
            if payload.get("status") not in [
                "内部审批中", "集团审批中", "已签订", "付款中", "发货", "到货", "已终止",
            ]:
                raise ValueError(f"无效状态：{payload['status']}")

            create_contract(payload=payload, db=db)  # 复用校验/行项/标签/框架标签逻辑
            seen.add(no)
            success += 1
        except HTTPException as e:
            errors.append({"row": sheet_row, "contract_no": no, "reason": e.detail})
        except ValueError as e:
            errors.append({"row": sheet_row, "contract_no": no, "reason": str(e)})

    return {"success": success, "fail": len(errors), "errors": errors}
