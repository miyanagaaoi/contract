"""单据打印服务（T-V2-37，对应 `12-erp-system-design.md` §6.3 与 BR-V2-16）。

产出**可直接打印的 A4 HTML**（内联 CSS，无外部依赖）：
- 表头：单据类型、单号、日期、状态、往来单位/仓库、关联合同、经办人、来源单据；
- 行项：序号/物料编码/物料名称/规格型号/单位/数量/单价/金额/备注 + 合计；
- 审批与签字：创建人、提交/审核时间、作废原因（如有）、制单/审核/仓管/领料签字栏；
- 页面顶部提供"打印"按钮（`window.print()`），打印时自动隐藏按钮与页面底色。

浏览器侧由前端以 blob 方式打开本 HTML（避免把令牌放进 URL）。
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from sqlalchemy.orm import Session

from ..models_doc import DOC_STATUS
from . import doc_service

_CSS = """
  @page { size: A4; margin: 14mm 12mm; }
  * { box-sizing: border-box; }
  body { font-family: "Microsoft YaHei", "SimSun", Arial, sans-serif; color: #000;
         font-size: 12px; margin: 0; padding: 12px; background: #f5f7fa; }
  .sheet { background: #fff; padding: 14mm 10mm; max-width: 210mm; margin: 0 auto;
           box-shadow: 0 0 6px rgba(0,0,0,.12); }
  h1 { font-size: 18px; text-align: center; margin: 0 0 4px; letter-spacing: 2px; }
  .sub { text-align: center; color: #555; font-size: 11px; margin-bottom: 10px; }
  table { width: 100%; border-collapse: collapse; }
  .head td { border: 1px solid #333; padding: 4px 6px; font-size: 11.5px; }
  .head .k { background: #f2f2f2; width: 76px; white-space: nowrap; }
  .items { margin-top: 8px; }
  .items th, .items td { border: 1px solid #333; padding: 4px 6px; font-size: 11.5px; }
  .items th { background: #f2f2f2; font-weight: 600; white-space: nowrap; }
  .num { text-align: right; }
  .center { text-align: center; }
  .total td { font-weight: 700; background: #fafafa; }
  .sign { margin-top: 14px; font-size: 11.5px; }
  .sign td { border: 1px solid #333; padding: 14px 6px 6px; }
  .foot { margin-top: 10px; color: #666; font-size: 10.5px; text-align: right; }
  .toolbar { text-align: right; max-width: 210mm; margin: 0 auto 8px; }
  .toolbar button { padding: 6px 14px; font-size: 13px; cursor: pointer; }
  .void { color: #c00; font-weight: 700; }
  @media print { body { background: #fff; padding: 0; } .sheet { box-shadow: none; padding: 0; }
                 .toolbar { display: none; } }
"""


def _e(value) -> str:
    return escape(str(value)) if value not in (None, "") else "—"


def _num(value) -> str:
    if value is None:
        return "—"
    number = float(value)
    text = f"{number:,.3f}".rstrip("0").rstrip(".") if number % 1 else f"{number:,.0f}"
    return text


def _money(value) -> str:
    return "—" if value is None else f"{float(value):,.2f}"


def _dt(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if isinstance(value, datetime) else "—"


def _party_of(doc) -> str:
    return (getattr(doc, "supplier_name", None) or getattr(doc, "customer_name", None)
            or getattr(doc, "customer_name_text", None) or "")


def build_doc_print_html(db: Session, doc) -> str:
    """生成单据 A4 打印 HTML（纯字符串，无模板引擎依赖）。"""
    label = getattr(type(doc), "label", "单据")
    status = DOC_STATUS.get(doc.status, doc.status)
    total = getattr(doc, "total_amount", None)
    if total is None:
        total = doc_service.total_amount_of(doc)

    head_rows: list[tuple[str, str]] = [
        ("单据编号", _e(doc.doc_no)),
        ("单据日期", doc.doc_date.strftime("%Y-%m-%d") if doc.doc_date else "—"),
        ("状态", f'<span class="{ "void" if doc.status == "voided" else "" }">{_e(status)}</span>'),
    ]
    if hasattr(doc, "warehouse_name"):
        head_rows.append(("仓库", _e(getattr(doc, "warehouse_name", None))))
    if _party_of(doc):
        key = "供应商" if getattr(doc, "supplier_name", None) else "客户"
        head_rows.append((key, _e(_party_of(doc))))
    if hasattr(doc, "in_type"):
        head_rows.append(("入库类型", _e(getattr(doc, "in_type", None))))
    if hasattr(doc, "out_type"):
        head_rows.append(("出库类型", _e(getattr(doc, "out_type", None))))
    if hasattr(doc, "take_type"):
        head_rows.append(("盘点方式", "全盘" if getattr(doc, "take_type", "") == "full" else "抽盘"))
    if hasattr(doc, "expected_arrival_date"):
        head_rows.append(("预计到货", _e(getattr(doc, "expected_arrival_date", None))))
    if hasattr(doc, "delivery_date"):
        head_rows.append(("交货日期", _e(getattr(doc, "delivery_date", None))))
    head_rows += [
        ("关联合同", _e(doc.contract_no)),
        ("经办人", _e(doc.created_by_name)),
        ("来源单据", _e(doc.source_doc_no)),
    ]
    if hasattr(doc, "generated_in_no") and getattr(doc, "generated_in_no", None):
        head_rows.append(("盘盈入库单", _e(doc.generated_in_no)))
    if hasattr(doc, "generated_out_no") and getattr(doc, "generated_out_no", None):
        head_rows.append(("盘亏出库单", _e(doc.generated_out_no)))

    # 表头两列一行
    head_html = ""
    for idx in range(0, len(head_rows), 2):
        pair = head_rows[idx:idx + 2]
        cells = "".join(f'<td class="k">{k}</td><td>{v}</td>' for k, v in pair)
        if len(pair) == 1:
            cells += '<td class="k"></td><td></td>'
        head_html += f"<tr>{cells}</tr>"

    item_rows = ""
    is_take = hasattr(doc, "take_type")
    for item in (doc.items or []):
        if is_take:
            extra = (f'<td class="num">{_num(item.book_qty)}</td>'
                     f'<td class="num">{_num(item.actual_qty)}</td>'
                     f'<td class="num">{_num(item.diff_qty)}</td>'
                     f'<td>{_e(item.diff_reason)}</td>')
        else:
            extra = (f'<td class="num">{_money(item.unit_price)}</td>'
                     f'<td class="num">{_money(item.amount)}</td>'
                     f'<td>{_e(item.remark)}</td>')
        item_rows += (
            f"<tr><td class='center'>{item.seq}</td><td>{_e(item.product_code)}</td>"
            f"<td>{_e(item.product_name)}</td><td>{_e(item.spec)}</td>"
            f"<td class='center'>{_e(item.uom_name)}</td>"
            f"<td class='num'>{_num(item.qty)}</td>{extra}</tr>"
        )
    if not item_rows:
        item_rows = (f'<tr><td colspan="{9 if not is_take else 10}" class="center">（无行项）</td></tr>')

    if is_take:
        head_cols = ("序号", "物料编码", "物料名称", "规格型号", "单位", "数量", "账面数量", "实盘数量",
                     "差异", "差异说明")
        total_html = ""
    else:
        head_cols = ("序号", "物料编码", "物料名称", "规格型号", "单位", "数量", "单价", "金额", "备注")
        total_html = (f'<tr class="total"><td colspan="7" class="num">合计</td>'
                      f'<td class="num">{_money(total)}</td><td></td></tr>')

    remarks = f'<p>备注：{_e(doc.remark)}</p>' if doc.remark else ""
    void_note = (f'<p class="void">作废原因：{_e(doc.void_reason)}（{_dt(doc.voided_at)}）</p>'
                 if doc.status == "voided" else "")
    approval = (
        f"<p>制单：{_e(doc.created_by_name)}　提交时间：{_dt(doc.submitted_at)}　"
        f"审核时间：{_dt(doc.approved_at)}"
        + ("　（已过账）" if getattr(doc, "posted", False) else "")
        + "</p>"
    )
    sign_labels = ["制单", "审核", "仓管", "领料/收货"] if not is_take else ["制单", "盘点人", "审核", "仓管"]
    sign_html = "".join(f'<td>{name}：</td>' for name in sign_labels)

    printed_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8" />
<title>{_e(label)} {_e(doc.doc_no)}</title>
<style>{_CSS}</style></head>
<body>
  <div class="toolbar"><button onclick="window.print()">打印 / 另存为 PDF</button></div>
  <div class="sheet">
    <h1>{_e(label)}</h1>
    <div class="sub">CTMS · ERP 进销存（打印时间 {printed_at}）</div>
    <table class="head">{head_html}</table>
    <table class="items">
      <thead><tr>{"".join(f"<th>{c}</th>" for c in head_cols)}</tr></thead>
      <tbody>{item_rows}{total_html}</tbody>
    </table>
    <div class="sign">{approval}{remarks}{void_note}</div>
    <table class="sign"><tr>{sign_html}</tr></table>
    <div class="foot">本单据由系统生成，签字后作为业务凭证留存。</div>
  </div>
</body></html>"""
