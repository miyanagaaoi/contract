"""单据打印服务（T-V2-37，对应 `12-erp-system-design.md` §6.3 与 BR-V2-16）。

产出**可直接打印的 A4 HTML**（内联 CSS，无外部依赖）：
- 表头：单据类型、单号、日期、状态、往来单位/仓库、关联合同、经办人、来源单据；
- 行项：序号/物料编码/物料名称/规格型号/单位/数量/单价/金额/备注 + 合计；
- 审批与签字：创建人、提交/审核时间、作废原因（如有）、制单/审核/仓管/领料签字栏；
- 页面顶部提供"打印"按钮（`window.print()`），打印时自动隐藏按钮与页面底色。

浏览器侧由前端以 blob 方式打开本 HTML（避免把令牌放进 URL）。

V2.2（BR-V2.2-02）：版面不再硬编码，改由**打印模板**（`print_template_service`，
管理员在「系统管理 → 打印模板」维护）驱动 —— 标题/副标题/页脚文字、区块顺序、
表头字段与行项列的显隐·顺序·标签、签字栏文字都可配置。数据库里没有模板时
使用出厂默认值，渲染结果与改造前逐项一致。
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from sqlalchemy.orm import Session

from ..models_doc import DOC_STATUS
from . import doc_service, print_template_service

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
  .gap { height: 8px; }
  @media print { body { background: #fff; padding: 0; } .sheet { box-shadow: none; padding: 0; }
                 .toolbar { display: none; } }
"""

#: 数值右对齐的列
_NUM_COLUMNS = {"qty", "unit_price", "amount", "book_qty", "actual_qty", "diff_qty"}
#: 居中的列
_CENTER_COLUMNS = {"seq", "uom_name"}


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


def _ymd(value) -> str:
    if value in (None, ""):
        return "—"
    return value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else str(value)


def _party_of(doc) -> str:
    return (getattr(doc, "supplier_name", None) or getattr(doc, "customer_name", None)
            or getattr(doc, "customer_name_text", None) or "")


def doc_kind_of(doc) -> str:
    """单据类型（`purchase_order` 等），取自模型类上的 `doc_type`。"""
    return str(getattr(type(doc), "doc_type", "") or "")


def doc_label_of(doc) -> str:
    return str(getattr(type(doc), "label", None) or "单据")


def is_take_doc(doc) -> bool:
    return doc_kind_of(doc) == "stock_take"


# ==================== 取值 ====================


_CN_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_CN_UNITS = ["", "拾", "佰", "仟"]
_CN_GROUPS = ["", "万", "亿"]


def amount_cn(amount) -> str:
    """金额大写（《付款申请单》的「金额（大写）人民币」）；支持到亿，保留角分。"""
    from decimal import Decimal

    value = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
    if value == 0:
        return "零元整"
    sign = "负" if value < 0 else ""
    value = abs(value)
    yuan = int(value)
    cents = int((value - yuan) * 100)
    if yuan == 0:
        head = ""
    else:
        groups: list[str] = []
        n = yuan
        while n > 0:
            groups.append(n % 10000)
            n //= 10000
        parts: list[str] = []
        for idx in range(len(groups) - 1, -1, -1):
            g = groups[idx]
            if g == 0:
                if parts and not parts[-1].endswith("零"):
                    parts.append("零")
                continue
            seg = ""
            zero_pending = False
            for pos in range(3, -1, -1):
                digit = (g // (10 ** pos)) % 10
                if digit == 0:
                    zero_pending = bool(seg)
                    continue
                if zero_pending:
                    seg += "零"
                    zero_pending = False
                seg += _CN_DIGITS[digit] + _CN_UNITS[pos]
            parts.append(seg + _CN_GROUPS[idx])
        head = "".join(parts).rstrip("零") + "元"
    if cents == 0:
        return f"{sign}{head}整"
    jiao, fen = divmod(cents, 10)
    tail = ""
    if jiao:
        tail += _CN_DIGITS[jiao] + "角"
    elif head:
        tail += "零"
    if fen:
        tail += _CN_DIGITS[fen] + "分"
    return f"{sign}{head}{tail}"


def _head_value_html(doc, key: str) -> str | None:
    """表头字段的单元格 HTML；**返回 None 表示该单据没有这个字段**（整项跳过）。

    与旧版硬编码版面保持一致：可选字段（仓库/往来单位/类型/日期/生成单号）只在
    模型上真的存在时渲染，避免给所有单据印一行"—"。
    """
    if key == "doc_no":
        return _e(getattr(doc, "doc_no", None))
    if key == "doc_date":
        return _ymd(getattr(doc, "doc_date", None))
    if key == "status":
        status = getattr(doc, "status", None)
        label = DOC_STATUS.get(status, status)
        cls = "void" if status == "voided" else ""
        return f'<span class="{cls}">{_e(label)}</span>'
    if key == "warehouse":
        if not hasattr(doc, "warehouse_name"):
            return None
        return _e(getattr(doc, "warehouse_name", None))
    if key == "subject":
        # V2.3（N2）：签约公司（我方公司名称快照）；未启用/未填写的单据不印
        value = getattr(doc, "subject_name", None) or getattr(doc, "subject_code", None)
        return _e(value) if value else None
    if key in ("from_subject", "to_subject"):
        # V2.3（N4）：调拨单调出/调入单位（由两端仓库所属公司自动带出）
        attr = f"{key.split('_')[0]}_subject_name"
        value = getattr(doc, attr, None) or getattr(doc, attr.replace("_name", "_code"), None)
        return _e(value) if value else None
    # ---- V2.5：付款申请单版式字段（其它单据没有这些属性 → 返回 None 自动跳过） ----
    if key == "amount_cn":
        if not hasattr(doc, "total_amount"):
            return None
        return _e(amount_cn(getattr(doc, "total_amount", 0)))
    if key == "payee":
        return _e(getattr(doc, "supplier_name", None))
    if key == "payer":
        return _e(getattr(doc, "subject_name", None) or getattr(doc, "subject_code", None))
    if key in ("payee_bank", "payee_account", "payer_bank", "category_l1", "category_l2",
               "belong_period", "bank_purpose", "pay_reason", "plan_type"):
        if not hasattr(doc, key):
            return None
        return _e(getattr(doc, key, None))
    if key == "supplier":
        if not hasattr(doc, "supplier_name"):
            return None
        return _e(getattr(doc, "supplier_name", None))
    if key == "customer":
        if not (hasattr(doc, "customer_name") or hasattr(doc, "customer_name_text")):
            return None
        return _e(getattr(doc, "customer_name", None) or getattr(doc, "customer_name_text", None))
    if key in ("from_warehouse", "to_warehouse"):
        attr = f"{key}_name"
        if not hasattr(doc, attr):
            return None
        return _e(getattr(doc, attr, None))
    if key in ("in_type", "out_type"):
        if not hasattr(doc, key):
            return None
        return _e(getattr(doc, key, None))
    if key == "take_type":
        if not hasattr(doc, "take_type"):
            return None
        return "全盘" if getattr(doc, "take_type", "") == "full" else "抽盘"
    if key in ("expected_arrival_date", "delivery_date"):
        if not hasattr(doc, key):
            return None
        return _ymd(getattr(doc, key, None))
    if key == "contract_no":
        return _e(getattr(doc, "contract_no", None))
    if key == "handler":
        return _e(getattr(doc, "created_by_name", None))
    if key == "source_doc_no":
        return _e(getattr(doc, "source_doc_no", None))
    if key in ("generated_in_no", "generated_out_no"):
        if not hasattr(doc, key):
            return None
        value = getattr(doc, key, None)
        # 与旧版一致：没有生成过上下游单据时**不印**这一格
        return _e(value) if value else None
    return None


def _item_cell_html(item, key: str) -> str:
    if key == "seq":
        return f'<td class="center">{item.seq}</td>'
    if key in ("qty", "book_qty", "actual_qty", "diff_qty"):
        return f'<td class="num">{_num(getattr(item, key, None))}</td>'
    if key in ("unit_price", "amount"):
        return f'<td class="num">{_money(getattr(item, key, None))}</td>'
    if key == "uom_name":
        return f'<td class="center">{_e(getattr(item, "uom_name", None))}</td>'
    return f'<td>{_e(getattr(item, key, None))}</td>'


# ==================== 版面渲染 ====================


def _render_title(cfg: dict) -> str:
    printed_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    subtitle = cfg["subtitle"]
    if cfg.get("show_printed_at"):
        stamp = f"打印时间 {printed_at}"
        subtitle = f"{subtitle}（{stamp}）" if subtitle else stamp
    sub_html = f'<div class="sub">{escape(subtitle)}</div>' if subtitle else ""
    return f"<h1>{escape(cfg['title'])}</h1>{sub_html}"


def _render_head(doc, cfg: dict) -> str:
    """表头信息表：支持每行 N 个字段（`head_columns`）与字段独占整行（`full`）。"""
    entries: list[tuple[str, str, bool]] = []
    for field in cfg["head_fields"]:
        if not field.get("enabled"):
            continue
        value = _head_value_html(doc, field["key"])
        if value is None:
            continue
        entries.append((str(field["label"]), value, bool(field.get("full"))))
    if not entries:
        return ""
    per_row = cfg["head_columns"]
    html = ""
    buffer: list[tuple[str, str, int]] = []
    used = 0

    def flush() -> None:
        nonlocal html, buffer, used
        if not buffer:
            return
        cells = ""
        for label, value, span in buffer:
            cells += f'<td class="k">{escape(label)}</td><td colspan="{span * 2 - 1}">{value}</td>'
        remain = per_row - used
        if remain > 0:
            cells += '<td class="k"></td><td></td>' * remain
        html += f"<tr>{cells}</tr>"
        buffer = []
        used = 0

    for label, value, full in entries:
        span = per_row if full else 1
        if used + span > per_row:
            flush()
        buffer.append((label, value, span))
        used += span
        if used >= per_row:
            flush()
    flush()
    return f'<table class="head">{html}</table>'


def _render_items(doc, cfg: dict) -> str:
    columns = [col for col in cfg["item_columns"] if col.get("enabled")]
    if not columns:
        return ""
    head_html = "".join(f"<th>{escape(str(col['label']))}</th>" for col in columns)
    body = ""
    for item in (getattr(doc, "items", None) or []):
        body += "<tr>" + "".join(_item_cell_html(item, col["key"]) for col in columns) + "</tr>"
    if not body:
        body = f'<tr><td colspan="{len(columns)}" class="center">（无行项）</td></tr>'

    total_html = ""
    amount_idx = next((i for i, col in enumerate(columns) if col["key"] == "amount"), None)
    if amount_idx is not None:
        # 合计行：把"合计"标签放在金额列前，金额列显示总额，其余列留空
        total = getattr(doc, "total_amount", None)
        if total is None:
            total = doc_service.total_amount_of(doc)
        cells = ['<td></td>'] * len(columns)
        cells[amount_idx] = f'<td class="num">{_money(total)}</td>'
        if amount_idx > 0:
            cells[amount_idx - 1] = '<td class="num">合计</td>'
        tail = "".join('<td></td>' for _ in columns[amount_idx + 1:])
        head_part = "".join(cells[:amount_idx + 1])
        total_html = f'<tr class="total">{head_part}{tail}</tr>'
    return (f'<table class="items"><thead><tr>{head_html}</tr></thead>'
            f"<tbody>{body}{total_html}</tbody></table>")


def _render_sign(doc, cfg: dict) -> str:
    parts: list[str] = []
    if cfg.get("show_approval", True):
        approval = (
            f"<p>制单：{_e(getattr(doc, 'created_by_name', None))}　"
            f"提交时间：{_dt(getattr(doc, 'submitted_at', None))}　"
            f"审核时间：{_dt(getattr(doc, 'approved_at', None))}"
            + ("　（已过账）" if getattr(doc, "posted", False) else "")
            + "</p>"
        )
        parts.append(approval)
    if cfg.get("show_remarks", True) and getattr(doc, "remark", None):
        parts.append(f"<p>备注：{_e(doc.remark)}</p>")
    if cfg.get("show_void_note", True) and getattr(doc, "status", None) == "voided":
        parts.append(f'<p class="void">作废原因：{_e(getattr(doc, "void_reason", None))}'
                     f"（{_dt(getattr(doc, 'voided_at', None))}）</p>")
    labels = cfg.get("signature_labels") or print_template_service.DEFAULT_SIGN_LABELS
    sign_html = "".join(f"<td>{escape(str(name))}：</td>" for name in labels)
    parts.append(f'<table class="sign"><tr>{sign_html}</tr></table>')
    return f'<div class="sign">{"".join(parts)}</div>'


# ==================== 《付款申请单》专用版式（对齐纸质模板） ====================
#
# 几何量直接取自参考文件 `docs/.参考文档/合同请示审批单模版.xlsx` 的「付款单 (新)」工作表：
#   列宽 A6.375 B5.125 C7.375 D24 E9.875 F12.375 G27.75（Excel 字符宽）
#   行高 标题33 / 日期21 / 明细行24.95×7 / 备注35.1 / 签字27×2（磅）
#   字体 标题16磅宋体加粗、日期12、正文11、签字10；纸张 A4 **横向**，页边距 上19 右17.8 下19 左35mm
# 表头字段仍受打印模板配置控制（标题/签字栏可改），但**行列结构与尺寸不随配置漂移**。

_PAY_COL_WIDTHS = [6.375, 5.125, 7.375, 24.0, 9.875, 12.375, 27.75]   # A~G
_PAY_ROW_HEIGHTS = [33, 21, 24.95, 24.95, 24.95, 24.95, 24.95, 24.95, 24.95, 35.1, 27, 27]
_PAY_CATEGORIES = ["经营", "经济", "行政", "人力", "投资", "往来"]

_PAYMENT_CSS = """
@page { size: A4 landscape; margin: 19mm 17.8mm 19mm 35mm; }
body { background: #fff; }
.sheet { width: 100%; box-shadow: none; padding: 0; }
table.pay { width: 100%; table-layout: fixed; border-collapse: collapse; font-family: SimSun, "宋体", serif; }
table.pay td { border: 1px solid #000; font-size: 11pt; padding: 2px 4px; vertical-align: middle;
               word-break: break-all; }
table.pay td.k { text-align: center; font-size: 11pt; }
table.pay tr.title td { border: none; font-size: 16pt; font-weight: 700; text-align: center;
                        letter-spacing: 6px; }
table.pay tr.sub td { border: none; font-size: 12pt; }
table.pay tr.sub td.right { text-align: right; }
table.pay tr.sign td { border: none; font-size: 10pt; padding-top: 8px; }
table.pay tr.remark td.k { }
"""


def _pay_checkbox(selected: str, options: list[str]) -> str:
    """勾选串：`经营√经济□…`（纸质模板的勾选样式）。"""
    picked = (selected or "").strip()
    return "".join(f"{opt}{'√' if picked == opt else '□'}" for opt in options)


def _pay_settle(settle_type: str | None) -> str:
    """结算方式勾选串：银行√/现金□（纸质模板只区分这两种）。"""
    value = (settle_type or "")
    return f"银行{'√' if '银行' in value or '转账' in value else '□'}　现金{'√' if '现金' in value else '□'}"


def _pay_value(value) -> str:
    """付款申请单的空值保留空格（纸质表格不能因为没填就把格子去掉）。"""
    text = "" if value is None else str(value)
    return f'<span class="v">{_e(text)}</span>' if text else "&nbsp;"


def _render_payment_application(doc, cfg: dict) -> str:
    """《付款申请单》12 行 × 7 列（A~G）固定网格；行列与尺寸不随模板配置漂移。"""
    widths = _PAY_COL_WIDTHS
    total = sum(widths)
    colgroup = "".join(f'<col style="width:{w / total * 100:.3f}%" />' for w in widths)
    heights = _PAY_ROW_HEIGHTS

    def row(idx: int, cells: str, cls: str = "") -> str:
        style = f' style="height:{heights[idx]}pt"'
        return f'<tr class="{cls}"{style}>{cells}</tr>'

    def k(text: str, colspan: int = 1) -> str:
        return f'<td class="k" colspan="{colspan}">{escape(text)}</td>'

    def v(value, colspan: int = 1, cls: str = "") -> str:
        extra = f' class="{cls}"' if cls else ""
        return f'<td{extra} colspan="{colspan}">{_pay_value(value)}</td>'

    date_text = _ymd(getattr(doc, "doc_date", None))
    plan = _pay_checkbox(getattr(doc, "plan_type", None), ["计划内", "计划外"])
    category = _pay_checkbox(getattr(doc, "category_l1", None), _PAY_CATEGORIES)
    total_amount = getattr(doc, "total_amount", None) or 0
    labels = cfg.get("signature_labels") or print_template_service.PAYMENT_SIGN_LABELS
    labels = list(labels) + ["", "", ""]
    sign_rows = ""
    for start in (0, 3):
        cells = ""
        spans = [(3, "k"), (3, "k"), (1, "k")]
        for offset, (span, cls) in enumerate(spans):
            name = labels[start + offset] if start + offset < len(labels) else ""
            text = f"{escape(str(name))}："
            cells += f'<td class="{cls}" colspan="{span}">{text}</td>' if start == 0 and offset == 0                 else f'<td colspan="{span}" style="text-align:center">{text}</td>'
        sign_rows += row(10 + start // 3, cells, "sign")

    body = (
        row(0, f'<td class="title" colspan="7">{escape(str(cfg.get("title") or "付款申请单"))}</td>', "title")
        + row(1, f'<td colspan="4" style="text-align:right">{date_text}</td>'
                  f'<td colspan="3" style="text-align:left;padding-left:12px">{plan}</td>', "sub")
        + row(2, k("收款<br/>信息", 1).replace('colspan="1"',
              'rowspan="2" style="width:6.86%"') + k("收款单位名称", 2)
              + v(getattr(doc, "supplier_name", None), 4))
        + row(3, k("开户银行", 2) + v(getattr(doc, "payee_bank", None))
                  + k("账号") + v(getattr(doc, "payee_account", None), 2))
        + row(4, k("付款<br/>信息").replace('colspan="1"',
              'rowspan="5" style="width:6.86%"') + k("付款单位名称", 2)
              + v(getattr(doc, "subject_name", None) or getattr(doc, "subject_code", None))
              + k("开户行") + v(getattr(doc, "payer_bank", None), 2))
        + row(5, k("一级分类", 2) + v(category, 2) + k("付款归属期")
                  + v(getattr(doc, "belong_period", None)))
        + row(6, k("二级分类", 2) + v(getattr(doc, "category_l2", None))
                  + k("回单") + k("银行付款用途") + v(getattr(doc, "bank_purpose", None)))
        + row(7, k("结算方式", 2) + v(_pay_settle(getattr(doc, "settle_type", None)), 2)
                  + k("付款事由") + v(getattr(doc, "pay_reason", None)))
        + row(8, k("金额", 2) + v(f"￥{_money(total_amount)}")
                  + k("金额（大写）人民币") + v(amount_cn(total_amount)))
        + row(9, k("备注", 3) + v(getattr(doc, "remark", None), 4))
        + sign_rows
    )
    grid = f'<table class="pay"><colgroup>{colgroup}</colgroup><tbody>{body}</tbody></table>'

    # 模板上没有、但管理员在「打印模板」页显式打开的项目 → 印在网格之后（默认全关，故默认输出＝纯模板）
    extra_entries = []
    for field in cfg.get("head_fields", []):
        if not field.get("enabled") or field.get("key") in print_template_service.PAYMENT_TEMPLATE_KEYS:
            continue
        value = _head_value_html(doc, field["key"])
        if value is None:
            continue
        extra_entries.append(f'<td class="k">{escape(str(field["label"]))}</td><td>{value}</td>')
    if not extra_entries:
        return grid
    extra = ("<table class=\"pay extra\"><tbody><tr>"
             + "".join(extra_entries) + "</tr></tbody></table>")
    return grid + extra


def build_doc_print_html(db: Session, doc, config: dict | None = None) -> str:
    """生成单据 A4 打印 HTML（纯字符串，无模板引擎依赖）。

    `config` 可显式传入模板（预览用）；缺省时按单据类型读取已保存模板。
    """
    kind = doc_kind_of(doc)
    if config is None and kind in print_template_service.KIND_LABELS:
        cfg = print_template_service.get_config(db, kind)
    else:
        cfg = print_template_service.normalize_config(kind, config)
    label = doc_label_of(doc)

    renderers = {
        "title": lambda: _render_title(cfg),
        "head": lambda: _render_head(doc, cfg),
        "items": lambda: _render_items(doc, cfg),
        "sign": lambda: _render_sign(doc, cfg),
    }
    sections = []
    for key in cfg["blocks"]:
        render = renderers.get(key)
        if render is None:
            continue
        html = render()
        if html:
            sections.append(html)
    if kind == "payment":
        # 《付款申请单》：整版固定网格（行列与尺寸对齐纸质模板），不走通用区块拼装
        body = _render_payment_application(doc, cfg)
    else:
        body = '<div class="gap"></div>'.join(sections)
    footer = (f'<div class="foot">{escape(cfg["footer"])}</div>' if cfg.get("footer") else "")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8" />
<title>{_e(label)} {_e(getattr(doc, "doc_no", ""))}</title>
<style>{_CSS}{_PAYMENT_CSS if kind == "payment" else ""}</style></head>
<body>
  <div class="toolbar"><button onclick="window.print()">打印 / 另存为 PDF</button></div>
  <div class="sheet">
    {body}
    {footer}
  </div>
</body></html>"""


# ==================== 预览样例 ====================


def sample_doc(kind: str):
    """构造一张内存样例单据，供模板预览使用（不写库、不依赖真实数据）。

    这样即使库里一张该类单据都没有，管理员也能立刻看到改模板的效果。
    """
    from types import SimpleNamespace

    label = print_template_service.KIND_LABELS.get(kind, "单据")
    cls = type(f"Sample_{kind or 'doc'}", (), {"doc_type": kind, "label": label})
    doc = cls()
    doc.doc_no = f"{kind[:2].upper() or 'DOC'}20250101001"
    doc.doc_date = _today()
    doc.status = "approved"
    doc.remark = "样例备注：本页为打印模板预览，数据仅供排版参考。"
    doc.contract_no = "HT20250101001"
    doc.created_by_name = "张样例"
    doc.submitted_at = datetime.now()
    doc.approved_at = datetime.now()
    doc.voided_at = None
    doc.void_reason = None
    doc.posted = kind in ("stock_in", "stock_out", "stock_transfer")
    doc.source_doc_no = "SQ20250101001"
    doc.total_amount = 12_345.67

    if kind in ("stock_in", "stock_out", "stock_take", "stock_transfer"):
        doc.warehouse_id, doc.warehouse_name = 1, "主仓库"
    if kind in ("purchase_request", "purchase_order", "stock_in"):
        doc.supplier_id, doc.supplier_name = 1, "样例供货商"
    if kind in ("sales_request", "sales_order", "stock_out"):
        doc.customer_id, doc.customer_name = 1, "样例客户"
    if kind == "purchase_order":
        doc.expected_arrival_date = _today()
        doc.settle_type = "月结"
    if kind == "sales_order":
        doc.delivery_date = _today()
    if kind == "stock_in":
        doc.in_type = "采购入库"
    if kind == "stock_out":
        doc.out_type = "销售出库"
    if kind == "stock_take":
        doc.take_type = "full"
        doc.generated_in_no = "RK20250101009"
    if kind == "stock_transfer":
        doc.from_warehouse_id, doc.from_warehouse_name = 1, "主仓库"
        doc.to_warehouse_id, doc.to_warehouse_name = 2, "车间仓"

    # V2.5：财务域（表头型单据：往来单位 + 金额 + 发票票面）
    if kind in ("payment", "invoice"):
        doc.supplier_id, doc.supplier_name = 1, "样例供货商"
        doc.party_id, doc.party_name = 1, "样例供货商"
    if kind == "receipt":
        doc.customer_id, doc.customer_name = 1, "样例客户"
        doc.party_id, doc.party_name = 1, "样例客户"
    if kind == "payment":
        doc.settle_type, doc.pay_account = "银行转账", "工行基本户 6222"
    if kind == "receipt":
        doc.settle_type, doc.recv_account = "银行转账", "工行基本户 6222"
    if kind == "invoice":
        doc.invoice_direction, doc.invoice_no = "in", "04400190011123456789"
        doc.invoice_code, doc.invoice_type = "044001900111", "增值税专用发票"
        doc.invoice_date = _today()
        doc.amount, doc.tax_amount = 10925.37, 1420.30
        doc.auth_status = "pending"

    rows = [
        ("CL001", "钢材", "Q235 10mm", "吨", 12.5),
        ("CL002", "不锈钢板", "304 2mm", "张", 30),
        ("WJ001", "六角螺栓", "M12×60", "盒", 8),
    ]
    items = []
    for idx, (code, name, spec, uom, qty) in enumerate(rows, start=1):
        item = SimpleNamespace(
            seq=idx, product_id=idx, product_code=code, product_name=name, spec=spec,
            uom_name=uom, uom_decimals=2, qty=qty, unit_price=100.5 * idx,
            amount=round(qty * 100.5 * idx, 2), remark="" if idx % 2 else "示例备注",
            book_qty=qty, actual_qty=qty + idx, diff_qty=idx, diff_reason="盘盈（样例）",
        )
        items.append(item)
    doc.items = items
    return doc


def _today():
    from datetime import date

    return date.today()
