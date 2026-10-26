"""V2.6 发票同步服务（docs/38 §4）：通过电子发票服务平台拉取进项发票。

路线 A（内嵌浏览器自动化）：
- Playwright Chromium（headless 默认开，`CTMS_TAX_SYNC_HEADLESS=0` 可视化便于排查）；
- 登录：账号/密码从配置读取（`CTMS_TAX_SYNC_USERNAME/PASSWORD`），平台下发短信验证码时
  线程置 `waiting_sms` 并阻塞等待用户通过 `submit_sms()` 输入；
- 会话保活：登录成功后 storage_state 落盘（`app/data/tax_session/`），TTL 1 小时
  （`CTMS_TAX_SYNC_SESSION_TTL`），窗口内再次同步免登录；
- 抓取：进入「全量发票查询」，查询类型=取得发票、状态=正常、按开票日期区间查询；
  优先拦截平台查询接口的 JSON 响应，表格 DOM 解析兜底；逐页翻页直至末页；
- 入库：按 `invoice_direction + invoice_no` 幂等 upsert，新增发票
  `auth_status=authenticated / bind_status=unbound / sync_source=tax_platform`。

⚠️ 平台前端改版风险：登录与抓取的**选择器/接口特征**全部集中在文件顶部常量区，
首跑或改版后只需校准常量，不动流程代码。
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.orm import Session

from .. import config
from ..database import SessionLocal
from ..models_doc import Invoice, InvoiceSyncLog, INVOICE_IN

# ══════════════ 平台特征常量（改版后在此校准） ══════════════

# 查询页（全量发票查询；SPA 内路由，直接 goto 通常会被路由接管）
QUERY_URL = "/invoice-query/invoice-query"
# 登录表单字段（全国统一规范电子税务局「企业业务」页签，2026-10-17 实测截图校准）：
#   ① 统一社会信用代码/纳税人识别号 ← CTMS_TAX_SYNC_<主体码>_TAX_NO
#   ② 手机号码/用户名               ← _USERNAME
#   ③ 个人用户密码                  ← _PASSWORD
_LOGIN_TAX_PLACEHOLDER = "统一社会信用代码"
_LOGIN_TAB_TEXTS = ["企业业务"]
_LOGIN_HINTS = ["统一登录", "请登录", "账号登录", "用户登录", "会话已失效", "需刷新重新操作"]
# ⚠️ 平台首页（/）是一个 SPA：未登录时先弹「会话已失效」 toast 再重定向到登录表单，
# 所以登录入口从**查询页**进入（未登录会被重定向到 login），并按输入框占位符识别表单。
# 账号登录表单（按优先级尝试的占位/标签文本）
_USER_PLACEHOLDERS = ["统一身份认证账号", "用户名", "账号", "手机号码", "身份证件号码"]
_PASS_PLACEHOLDERS = ["密码"]
_SMS_PLACEHOLDERS = ["验证码", "短信验证码", "手机验证码"]
_LOGIN_BUTTON_TEXTS = ["登录", "登 录"]
# 触发平台下发短信的按钮（部分平台需要先点「获取验证码」才真正发送）
_SEND_SMS_BUTTON_TEXTS = ["获取验证码", "发送验证码", "点击获取", "免费获取", "获取短信验证码"]
# 登录后的人工校验特征（2026-10-17 实测：点「登录」先弹「请依次点击」点字验证码，
# 通过后才可能再弹短信验证码——均需**人工**在可见浏览器窗口中完成）
_CAPTCHA_HINTS = ["请依次点击", "拖动滑块", "滑块验证"]
# XHR 接口特征：响应 JSON 含这些字段组合视为发票列表数据
_XHR_URL_HINTS = ["invoice", "fpgl", "queryInvoice", "fpQuery"]
# JSON 行字段候选键（数电票常用驼峰/拼音缩写都覆盖）
_KEY_INVOICE_NO = ["fphm", "invoiceNumber", "fphmValue", "digitalFphm"]
_KEY_INVOICE_TYPE = ["fplxDmc", "invoiceTypeCn", "fplxMc", "invoiceTypeName"]
_KEY_INVOICE_DATE = ["kprq", "invoiceDate", "kpDate"]
_KEY_AMOUNT = ["je", "hjje", "amount", "kjje", "amountWithoutTax"]
_KEY_TAX = ["se", "hjse", "taxAmount", "tax"]
_KEY_TOTAL = ["jshj", "totalAmount", "priceTaxTotal", "amountWithTax"]
_KEY_SELLER_NAME = ["xfmc", "sellerName", "xsfMc"]
_KEY_SELLER_TAX = ["xfnsrsbh", "sellerTaxNo", "xsfNsrsbh"]
_KEY_BUYER_NAME = ["gfmc", "buyerName", "gmfMc"]
_KEY_BUYER_TAX = ["gfnsrsbh", "buyerTaxNo", "gmfNsrsbh"]
_KEY_STATUS = ["fpztDmc", "invoiceStatusCn", "ztMc", "statusName"]
_KEY_TAX_RATE = ["sl", "slv", "taxRate"]
# DOM 表格列头（与 browser-sessions 导出样例一致）
_DOM_HEADERS = {
    "invoice_no": "数电发票号码",
    "invoice_type": "票种",
    "invoice_date": "开票日期",
    "amount": "金额",
    "tax": "税额",
    "total": "价税合计",
    "party": "购/销方名称",
    "party_tax": "购/销方识别号",
    "status": "发票状态",
}
_QUERY_BUTTON_TEXTS = ["查 询", "查询"]
_NEXT_BUTTON_TEXTS = ["下一页", "下页"]
# 查询类型（2026-10-17 用户截图反馈：需选「取得发票」才是进项票列表）
_QUERY_TYPE_TEXT = "取得发票"

# ══════════════ 任务注册表（内存） ══════════════

_LOCK = threading.Lock()                 # 全局串行：同一时刻只允许一个同步任务
_TASKS: dict[int, dict] = {}             # sync_log_id -> {"sms_event": Event, "sms_code": str}
_TASK_TTL = 3600.0


def _task(log_id: int) -> dict:
    with _LOCK:
        task = _TASKS.get(log_id)
        if task is None:
            task = {"sms_event": threading.Event(), "sms_code": "", "cancelled": False}
            _TASKS[log_id] = task
        # 清理过期任务
        for k in [k for k in _TASKS if k != log_id]:
            del _TASKS[k]
        return task


def submit_sms(log_id: int, code: str) -> bool:
    """用户输入验证码后由路由调用；返回是否成功唤醒等待中的同步线程。"""
    with _LOCK:
        task = _TASKS.get(log_id)
    if task is None:
        return False
    task["sms_code"] = (code or "").strip()
    task["sms_event"].set()
    return True


def cancel(log_id: int) -> None:
    with _LOCK:
        task = _TASKS.get(log_id)
    if task:
        task["cancelled"] = True
        task["sms_event"].set()


# ══════════════ 会话保活 ══════════════

def _storage_file(subject_code: str) -> Path:
    """按主体码隔离登录会话（两家公司各有一个平台账号，storage_state 互不覆盖）。"""
    config.TAX_SYNC_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return config.TAX_SYNC_STORAGE_DIR / f"state_{(subject_code or 'DEFAULT').upper()}.json"


def session_fresh(subject_code: str) -> bool:
    """登录会话是否仍在保活窗口内（1 小时）。"""
    f = _storage_file(subject_code)
    if not f.is_file():
        return False
    age = time.time() - f.stat().st_mtime
    return age < config.TAX_SYNC_SESSION_TTL


def list_companies(db: Session) -> list[dict]:
    """同步公司选项：以**系统设置「我方公司」字典为准**列出全部主体码。

    每个主体码用 code 去匹配 `.env` 凭据（`CTMS_TAX_SYNC_<主体码>_*`）：
    - `configured=False`（未配凭据）：前端禁选并提示；
    - `session_fresh`：该主体码的登录会话是否在保活窗口内（选中后展示连接状态）。
    """
    from .. import dicts

    out: list[dict] = []
    for subject in dicts.get_subjects(db):
        code = subject.get("code") or ""
        cred = config.tax_sync_company(code)
        configured = bool(cred and cred.get("username") and cred.get("password"))
        out.append({
            "code": code,
            "name": subject.get("name") or "",
            "tax_no": subject.get("tax_no") or (cred or {}).get("tax_no") or "",
            "configured": configured,
            "session_fresh": session_fresh(code),
        })
    return sorted(out, key=lambda c: c["code"])


def last_sync_info(db: Session) -> dict:
    """上次同步概要 + 已配置公司列表（发票列表页提示条与同步向导下拉用）。"""
    log = db.query(InvoiceSyncLog).order_by(InvoiceSyncLog.id.desc()).first()
    return {
        "has_history": log is not None,
        "headless": config.TAX_SYNC_HEADLESS,
        # 非 Windows 且无 DISPLAY/WAYLAND_DISPLAY ≈ 容器/无图形服务器，无法弹窗
        "has_display": bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                            or os.name == "nt"),
        "companies": list_companies(db),
        "last_at": log.finished_at.isoformat() if log and log.finished_at else None,
        "date_from": log.date_from.isoformat() if log and log.date_from else None,
        "date_to": log.date_to.isoformat() if log and log.date_to else None,
        "status": log.status if log else None,
        "fetched": log.fetched if log else 0,
        "inserted": log.inserted if log else 0,
        "skipped_duplicate": log.skipped_duplicate if log else 0,
        "message": log.message if log else None,
    }


# ══════════════ 解析与入库 ══════════════

def _dec(value) -> Decimal | None:
    if value in (None, "", "--"):
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("¥", "").replace("￥", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _pick(row: dict, keys: list[str]):
    for k in keys:
        if k in row and row[k] not in (None, "", "--"):
            return row[k]
    return None


def _norm_date(value) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:len(fmt) + 4 if "H" in fmt else 10], fmt).date()
        except ValueError:
            continue
    return None


def normalize_row(raw: dict, query_type: str = "取得发票") -> dict | None:
    """平台行（JSON 或 DOM 解析产物）→ 系统发票字段 dict；非进项/异常行返回 None。

    红字口径（2026-10-18 业务确认）：状态含「冲红」或价税合计为负 → `_red=True`
    照常入库并标记，不参与收票进度绑定；其余非「正常」状态（如作废）仍过滤。
    """
    invoice_no = str(_pick(raw, _KEY_INVOICE_NO) or "").strip()
    if not invoice_no or invoice_no == "--":
        return None
    status = str(_pick(raw, _KEY_STATUS) or "").strip()
    if status and status != "正常" and "冲红" not in status:
        return None                      # 只同步「正常」与「已冲红」状态
    amount = _dec(_pick(raw, _KEY_AMOUNT)) or Decimal("0")
    tax = _dec(_pick(raw, _KEY_TAX)) or Decimal("0")
    total = _dec(_pick(raw, _KEY_TOTAL))
    if total is None:
        total = amount + tax
    tax_rate = _dec(_pick(raw, _KEY_TAX_RATE))
    if tax_rate is None and amount:
        tax_rate = (tax / amount * Decimal("100")).quantize(Decimal("0.01"))
    # 红字标记：平台状态含"冲红"，或价税合计为负（红字发票的票面特征）
    is_red = ("冲红" in status) or total < 0
    # 购/销方向：查询类型=取得发票（进项）时，平台「购/销方」列是销方（开票单位）
    # 逻辑上：进项发票 seller=对方开票单位、buyer=我方；JSON 有明确 xf/gf 字段时以字段为准。
    seller_name = _pick(raw, _KEY_SELLER_NAME)
    seller_tax = _pick(raw, _KEY_SELLER_TAX)
    buyer_name = _pick(raw, _KEY_BUYER_NAME)
    buyer_tax = _pick(raw, _KEY_BUYER_TAX)
    dom_party = raw.get("_dom_party_name")
    dom_party_tax = raw.get("_dom_party_tax_no")
    if not seller_name and dom_party:
        seller_name, seller_tax = dom_party, dom_party_tax
    return {
        "invoice_direction": INVOICE_IN,
        "invoice_no": invoice_no,
        "invoice_code": None,
        "invoice_type": str(_pick(raw, _KEY_INVOICE_TYPE) or "").strip() or None,
        "invoice_date": _norm_date(_pick(raw, _KEY_INVOICE_DATE)),
        "amount": amount, "tax_amount": tax, "total_amount": total,
        "tax_rate": tax_rate,
        "seller_name": seller_name, "seller_tax_no": seller_tax,
        "buyer_name": buyer_name, "buyer_tax_no": buyer_tax,
        "_red": is_red,
    }


def upsert_invoices(db: Session, rows: list[dict], company: dict) -> dict:
    """幂等入库：按 (direction, invoice_no) 去重；新增发票标记同步来源与状态。

    `company` 是凭据字典（code/username/tax_no）；签约公司直接按主体码落 code/name
    （V2.6 多公司口径：同步哪家的账号，票就归哪家我方公司）。
    """
    from .. import dicts

    inserted = skipped = 0
    subject_code = (company.get("code") or "").upper()
    subjects = {s["code"]: s for s in dicts.get_subjects(db)}
    subject = subjects.get(subject_code)
    our_name = (subject or {}).get("name") or ""
    for row in rows:
        exists = (db.query(Invoice)
                  .filter(Invoice.invoice_direction == INVOICE_IN,
                          Invoice.invoice_no == row["invoice_no"])
                  .first())
        if exists is not None:
            skipped += 1
            continue
        inv = Invoice(
            doc_no=None,                 # 由下方 numbering 生成
            doc_date=row.get("invoice_date"),
            status="draft",
            invoice_direction=INVOICE_IN,
            invoice_no=row["invoice_no"],
            invoice_code=row.get("invoice_code"),
            invoice_type=row.get("invoice_type"),
            invoice_date=row.get("invoice_date"),
            tax_rate=row.get("tax_rate"),
            amount=row["amount"], tax_amount=row["tax_amount"], total_amount=row["total_amount"],
            auth_status="authenticated",          # 同步 = 已认证（需求口径，docs/38 §2.3）
            bind_status="unbound",
            sync_source="tax_platform",
            synced_at=datetime.now(),
            seller_name=row.get("seller_name"), seller_tax_no=row.get("seller_tax_no"),
            buyer_name=row.get("buyer_name"), buyer_tax_no=row.get("buyer_tax_no"),
            our_company_code=subject_code or None, our_company_name=our_name or None,
            subject_code=subject_code or None, subject_name=our_name or None,
            party_name=row.get("seller_name"),
            is_red=bool(row.get("_red")) or (row.get("total_amount") or 0) < 0,
            remark=("【红字】" if (row.get("_red") or (row.get("total_amount") or 0) < 0)
                    else "") + f"电子发票服务平台同步（{date.today().isoformat()}）",
        )
        from . import numbering_service

        inv.doc_no = numbering_service.next_doc_no(
            db, "invoice", row.get("invoice_date") or date.today())
        db.add(inv)
        db.flush()                       # 立即落库占号：同批多行同日才不会撞 doc_no
        inserted += 1
    db.commit()
    return {"inserted": inserted, "skipped_duplicate": skipped}


def import_platform_rows(db: Session, rows: list[dict], subject_code: str) -> dict:
    """桥接同步通道（开发环境）：导入从**用户浏览器**页面解析好的发票行。

    与 Playwright 通道共用 `upsert_invoices`（幂等 + 同步标记），差异：
    - 行由 DSH 浏览器扩展从用户已登录的查询页读出（字段已按 normalize_row 口径解析）；
    - **红字发票标记**：价税合计 < 0 的红字票照常入库并 `is_red=True`（2026-10-18
      业务确认：系统中标记为红冲，只做台账、不参与收票进度绑定）；
      平台状态"已冲红-全额"由 normalize_row 同样打标。
    """
    code = (subject_code or "").strip().upper()
    company = config.tax_sync_company(code) or {"code": code, "username": "", "password": "",
                                                "tax_no": ""}
    normalized: list[dict] = []
    skipped_red = 0
    for raw in rows:
        row = raw if "invoice_no" in raw else normalize_row(raw)
        if row is None:
            continue
        total = row.get("total_amount")
        try:
            if total is not None and Decimal(str(total)) < 0:
                row["_red"] = True
        except (TypeError, ValueError):
            pass
        if row.get("_red"):
            skipped_red += 1              # 红字票：入库但计数单独展示
        # 桥接行是 JSON 字典：日期可能是字符串，编号服务需要 date 对象
        row["invoice_date"] = _norm_date(row.get("invoice_date"))
        for key in ("amount", "tax_amount", "total_amount"):
            row[key] = _dec(row.get(key)) or Decimal("0")
        normalized.append(row)
    counts = upsert_invoices(db, normalized, company)
    return {"fetched": len(normalized),
            "inserted": counts["inserted"],
            "skipped_duplicate": counts["skipped_duplicate"],
            "skipped_red": skipped_red}


def import_package(db: Session, zip_bytes: bytes, subject_code: str) -> dict:
    """「下载发票包」导入（docs/38 桥接/人工流程的官方文件版）。

    用户在电子税务局查询页点「下载 → 全部下载」得到压缩包（内含每张票的
    PDF/OFD/XML，文件名含 20 位数电发票号码）。本函数：
    1. 解压（兼容 zip/tar，自动识别嵌套目录）；
    2. 从**文件名**提取 20 位数电票号匹配系统发票（进项优先，不看方向也接受）；
    3. 匹配成功 → 文件存 `uploads/invoices/`，挂 Attachment(object_type='invoice')；
    4. 返回 匹配/未匹配 清单（未匹配文件多半是系统尚未同步的票，提示先同步）。
    """
    import io
    import zipfile
    from ..models import Attachment
    from ..config import UPLOAD_DIR

    code = (subject_code or "").strip().upper()
    dest_dir = UPLOAD_DIR / "invoices"
    dest_dir.mkdir(parents=True, exist_ok=True)

    attached, unmatched, errors = [], [], []
    matched_ids: set[int] = set()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        for name in names:
            try:
                nos = set(re.findall(r"\d{20}", name))
                if not nos:
                    # 文件名没有票号 → 尝试从 XML 文本里找
                    data = zf.read(name)
                    if name.lower().endswith((".xml", ".txt")):
                        nos = set(re.findall(r"\d{20}", data[:65536].decode(
                            "utf-8", errors="ignore")))
                if not nos:
                    unmatched.append(name)
                    continue
                inv = (db.query(Invoice)
                       .filter(Invoice.invoice_no.in_(nos), Invoice.deleted.is_(False))
                       .first())
                if inv is None:
                    unmatched.append(name)
                    continue
                if inv.id in matched_ids:
                    continue                      # 同一张票多格式文件只挂第一个
                safe_name = f"{inv.invoice_no}_{Path(name).name}"
                data = zf.read(name)
                (dest_dir / safe_name).write_bytes(data)
                db.add(Attachment(
                    file_name=Path(name).name,
                    stored_path=f"invoices/{safe_name}",
                    content_type=("application/pdf" if safe_name.lower().endswith(".pdf")
                                  else "application/xml"),
                    size_bytes=len(data),
                    object_type="invoice", object_id=inv.id,
                ))
                matched_ids.add(inv.id)
                attached.append({"invoice_id": inv.id, "invoice_no": inv.invoice_no,
                                 "file": Path(name).name})
            except Exception as exc:  # noqa: BLE001
                errors.append({"file": name, "reason": str(exc)[:200]})
    db.commit()
    return {"attached": attached, "unmatched": unmatched, "errors": errors,
            "total_files": len(names)}


# ══════════════ Playwright 抓取 ══════════════

def _snap(page, name: str, *, retries: int = 3) -> None:
    """调试截图：存到 app/data/tax_session/debug/（首跑校准/排查用，不影响流程）。

    页面跳转中截图可能抛错，重试几次；仍失败则放弃（不阻塞流程）。
    """
    debug_dir = config.TAX_SYNC_STORAGE_DIR / "debug"
    for i in range(retries):
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(debug_dir / f"{name}.png"), full_page=False)
            return
        except Exception:
            page.wait_for_timeout(1500)
    # 末次忽略异常
    try:
        page.screenshot(path=str(debug_dir / f"{name}.png"), full_page=False)
    except Exception:
        pass


def _body_digest(page, limit: int = 300) -> str:
    """页面可见文字摘要（失败信息用，替代截图看不了的场景）。"""
    try:
        text = " ".join(page.inner_text("body", timeout=3000).split())
        return text[:limit]
    except Exception as exc:
        return f"<body 读取失败: {exc}>"


def _page_text_has(page, hints: list[str]) -> bool:
    try:
        text = page.inner_text("body", timeout=2000)
    except Exception:
        return False
    return any(h in text for h in hints)


def _fill_first(page, placeholders: list[str], value: str) -> bool:
    for ph in placeholders:
        for sel in (f'input[placeholder*="{ph}"]', f'input[title*="{ph}"]'):
            loc = page.locator(sel).first
            try:
                if loc.is_visible(timeout=1000):
                    loc.fill(value)
                    return True
            except Exception:
                continue
    return False


def _click_text(page, texts: list[str]) -> bool:
    for text in texts:
        loc = page.get_by_text(text, exact=True).first
        try:
            if loc.is_visible(timeout=1000):
                loc.click()
                return True
        except Exception:
            continue
    return False


def _wait_sms(page, task: dict, log_id: int) -> bool:  # noqa: ARG001 - 保留接口兼容
    """【已弃用】V2.6 人工接管模式下验证码由用户在可见窗口直接填写。

    保留函数体仅为兼容既有调用点检查；现行流程见 `_login` 的轮询段。
    """
    _set_status(log_id, "waiting_sms")
    got = task["sms_event"].wait(timeout=config.TAX_SYNC_SMS_TIMEOUT)
    task["sms_event"].clear()
    if not got or task["cancelled"]:
        return False
    code = task["sms_code"]
    return bool(code and _fill_first(page, _SMS_PLACEHOLDERS, code)
                and _click_text(page, ["确定", "确认", "提交", "登录"] + _LOGIN_BUTTON_TEXTS))


def _login_form_visible(page) -> bool:
    """登录表单是否在页面上（按真实表单的占位符特征识别）。"""
    for ph in (_LOGIN_TAX_PLACEHOLDER, "手机号", "密码"):
        try:
            if page.locator(f'input[placeholder*="{ph}"]').first.is_visible(timeout=800):
                return True
        except Exception:
            continue
    return False


def _login(page, log_id: int, company: dict) -> bool:
    """账号密码登录（含短信验证码）；成功后按主体码落盘 storage_state。

    入口策略：直接进**查询页**——未登录时平台会重定向到登录表单（首页只弹
    「会话已失效」toast，没有表单；2026-10-17 实测截图确认）。
    """
    code = (company.get("code") or "DEFAULT").upper()
    page.goto(config.TAX_SYNC_BASE_URL + QUERY_URL, timeout=60000,
              wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    _snap(page, "step1-login-page-open")

    # SPA 未登录时先弹 toast 再重定向到登录表单：多等 10s
    if not _login_form_visible(page):
        page.wait_for_timeout(10000)
        _snap(page, "step1b-login-redirect-wait")
    if not _login_form_visible(page):
        raise RuntimeError(
            "未找到登录表单（平台可能改版或为扫码/证书登录）。"
            "请查看 app/data/tax_session/debug/step1*.png 截图确认真实页面后校准常量。")

    # —— 按真实表单三字段填写（2026-10-17 截图校准），每项填完读回校验 ——
    _click_text(page, _LOGIN_TAB_TEXTS)               # 确保「企业业务」页签激活
    page.wait_for_timeout(1000)

    def _fill_and_check(placeholder_part: str, value: str, label: str) -> None:
        if not value:
            raise RuntimeError(f"登录缺少「{label}」：请补全 .env 里该公司对应的环境变量")
        loc = page.locator(f'input[placeholder*="{placeholder_part}"]').first
        try:
            if not loc.is_visible(timeout=3000):
                raise RuntimeError(f"登录页未找到「{label}」输入框（平台改版？请发 debug 截图）")
            loc.click()
            loc.fill("")
            loc.type(value, delay=30)                 # 逐键输入：部分框架对 fill 兼容差
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"填写「{label}」失败：{exc}")
        filled = (loc.input_value() or "").strip()
        if not filled:
            raise RuntimeError(f"「{label}」填写后为空（可能有多个同名输入框或框架拦截），"
                               f"请发 app/data/tax_session/debug/ 截图定位")

    _fill_and_check(_LOGIN_TAX_PLACEHOLDER, company.get("tax_no") or "",
                    "统一社会信用代码（CTMS_TAX_SYNC_<主体码>_TAX_NO）")
    _fill_and_check("手机号", company.get("username") or "", "手机号/用户名")
    _fill_and_check("密码", config.tax_sync_password_plain(company.get("password") or ""),
                    "个人用户密码")
    _snap(page, "step1c-credentials-filled")
    if not _click_text(page, _LOGIN_BUTTON_TEXTS):
        raise RuntimeError("登录页未找到登录按钮")

    # —— 人工接管等待（点字验证码 / 滑块 / 短信验证码都在**可见窗口**由用户完成）——
    # 轮询直至：登录表单与验证码都消失（=登录成功）或超时。
    # 短信验证码输入框出现时置 waiting_sms（前端弹等待提示）并自动点一次「获取验证码」；
    # 用户在窗口里填完验证码后，系统检测到已填 4 位以上会自动点「登录」提交。
    _set_status(log_id, "waiting_sms",
                message="请在弹出的浏览器窗口中完成人工验证（点选文字/滑块/短信验证码）")
    task = _TASKS.get(log_id) or {}
    sms_clicked_at = 0.0
    deadline = time.time() + config.TAX_SYNC_SMS_TIMEOUT
    while time.time() < deadline:
        if task.get("cancelled"):
            raise RuntimeError("同步已被取消")
        captcha_up = _page_text_has(page, _CAPTCHA_HINTS)
        sms_input = page.locator('input[placeholder*="验证码"]').first
        sms_up = False
        try:
            sms_up = sms_input.is_visible(timeout=800)
        except Exception:
            pass

        if sms_up:
            # 自动触发一次短信下发（平台有冷却，60s 后仍未收到可由用户在窗口里手动重发）
            if time.time() - sms_clicked_at > 60:
                _click_text(page, _SEND_SMS_BUTTON_TEXTS)
                sms_clicked_at = time.time()
            try:
                typed = (sms_input.input_value() or "").strip()
            except Exception:
                typed = ""
            if len(typed) >= 4:               # 用户已在窗口里填好验证码 → 自动提交
                _click_text(page, _LOGIN_BUTTON_TEXTS)

        if not _login_form_visible(page) and not captcha_up:
            break                             # 登录表单与验证码都消失 = 成功
        page.wait_for_timeout(3000)
    else:
        _snap(page, "step2-assist-timeout")
        raise RuntimeError("人工验证等待超时（10 分钟）：请在窗口里完成点字验证/短信验证码后重试。"
                           "页面摘要：" + _body_digest(page, 150))

    page.wait_for_timeout(6000)
    _snap(page, "step3-after-login")
    if _login_form_visible(page) or _page_text_has(page, _LOGIN_HINTS):
        digest = _body_digest(page)
        raise RuntimeError(f"登录未成功。登录后页面摘要：{digest}（完整截图 debug/step3-after-login.png）")
    try:
        page.context.storage_state(path=str(_storage_file(code)))
    except Exception:
        pass
    return True


def _set_status(log_id: int, status: str, message: str | None = None) -> None:
    with SessionLocal() as db:
        log = db.get(InvoiceSyncLog, log_id)
        if log is None:
            return
        log.status = status
        if message is not None:
            log.message = message[:2000]
        db.commit()


def _record_api_recon(endpoints: dict) -> None:
    """接口探测记录（docs/38 摸清接口）：XHR URL → 命中发票行数，落 json 供校准。"""
    if not endpoints:
        return
    try:
        path = config.TAX_SYNC_STORAGE_DIR / "api_recon.json"
        config.TAX_SYNC_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        seen = {}
        if path.is_file():
            seen = json.loads(path.read_text(encoding="utf-8"))
        for url, count in endpoints.items():
            seen[url] = seen.get(url, 0) + count
        path.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _collect_json_rows(page) -> list[dict]:
    """拦截查询接口的 JSON 响应，启发式解析出发票行；同时记录接口探测结果。"""
    rows: list[dict] = []
    records: list[dict] = []
    endpoints: dict = {}

    def _on_response(resp):
        try:
            if not any(h.lower() in resp.url.lower() for h in _XHR_URL_HINTS):
                return
            ctype = resp.headers.get("content-type", "")
            if "json" not in ctype:
                return
            data = resp.json()
        except Exception:
            return
        # 深度找"看起来像发票行"的 dict 列表：含发票号候选键
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if any(k in node for k in _KEY_INVOICE_NO):
                    records.append(node)
                else:
                    stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        endpoints[resp.url[:300]] = endpoints.get(resp.url[:300], 0) + 1

    page.on("response", _on_response)
    # 查询按钮由调用方（_scrape_all_pages）点击；此处只监听响应并等数据到达
    page.wait_for_timeout(6000)
    page.remove_listener("response", _on_response)
    _record_api_recon(endpoints)
    page.remove_listener("response", _on_response)
    for rec in records:
        row = normalize_row(rec)
        if row:
            rows.append(row)
    return rows


def _collect_dom_rows(page) -> list[dict]:
    """兜底：按表头文本解析渲染后的表格行。"""
    try:
        page.wait_for_selector("table", timeout=8000)
    except Exception:
        return []
    rows: list[dict] = []
    for table in page.locator("table").all():
        header_cells = [c.inner_text().strip() for c in table.locator("thead th").all()]
        if not header_cells or _DOM_HEADERS["invoice_no"] not in "".join(header_cells):
            continue
        col = {name: i for i, name in enumerate(header_cells)}
        for tr in table.locator("tbody tr").all():
            cells = [c.inner_text().strip() for c in tr.locator("td").all()]
            if len(cells) < len(header_cells):
                continue

            def _c(key):
                i = col.get(_DOM_HEADERS[key])
                return cells[i] if i is not None and i < len(cells) else None

            raw = {
                _DOM_HEADERS["invoice_no"]: _c("invoice_no"),
                _DOM_HEADERS["invoice_type"]: _c("invoice_type"),
                _DOM_HEADERS["invoice_date"]: _c("invoice_date"),
                _DOM_HEADERS["amount"]: _c("amount"),
                _DOM_HEADERS["tax"]: _c("tax"),
                _DOM_HEADERS["total"]: _c("total"),
                _DOM_HEADERS["status"]: _c("status"),
                "_dom_party_name": _c("party"),
                "_dom_party_tax_no": _c("party_tax"),
            }
            row = normalize_row(raw)
            if row:
                rows.append(row)
        break
    return rows


def _click_query_button(page) -> bool:
    """点「查询」按钮（button 元素优先，比 get_by_text 稳）。"""
    for sel in ("button:has-text('查 询')", "button:has-text('查询')"):
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1000):
                loc.click()
                return True
        except Exception:
            continue
    return _click_text(page, _QUERY_BUTTON_TEXTS)


def _set_query_type(page) -> bool:
    """把查询类型设为「取得发票」。

    兼容两种形态：① 页签/单选（直接可见文字，点即可）；② el-select 下拉
    （逐个展开下拉，在浮层里找「取得发票」选项）。
    """
    if _click_text(page, [_QUERY_TYPE_TEXT]):
        page.wait_for_timeout(500)
        return True
    try:
        selects = page.locator(".el-select")
        for i in range(min(selects.count(), 8)):
            try:
                selects.nth(i).click()
                page.wait_for_timeout(600)
                opt = page.locator(".el-select-dropdown:visible").locator(
                    f"text={_QUERY_TYPE_TEXT}").first
                if opt.is_visible(timeout=1000):
                    opt.click()
                    page.wait_for_timeout(500)
                    return True
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
            except Exception:
                continue
    except Exception:
        pass
    return False


def _goto_query_page(page, date_from: date, date_to: date) -> None:
    page.goto(config.TAX_SYNC_BASE_URL + QUERY_URL, timeout=60000,
              wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    _set_query_type(page)
    # 日期区间（优先 placeholder/type=date 的 input，策略宽松便于适配）
    date_inputs = page.locator('input[type="date"], input[placeholder*="开始"], input[placeholder*="日期"]')
    if date_inputs.count() >= 2:
        try:
            for idx, value in ((0, date_from.isoformat()), (1, date_to.isoformat())):
                date_inputs.nth(idx).click()
                date_inputs.nth(idx).fill(value)
                page.keyboard.press("Enter")     # element-plus 日期面板需回车确认
                page.wait_for_timeout(400)
        except Exception:
            pass
    _snap(page, "step2b-query-form-set")


def _scrape_all_pages(page, task: dict) -> list[dict]:
    """点查询 → 抓首页 → 翻页抓完（翻页时**不**再点查询，避免永远停在第 1 页）。"""
    if not _click_query_button(page):
        raise RuntimeError("查询页未找到「查询」按钮（平台改版？请发 debug 截图定位）")
    page.wait_for_timeout(6000)
    rows = _collect_json_rows(page) or _collect_dom_rows(page)
    for _ in range(50):
        if task.get("cancelled"):
            break
        if not _click_text(page, _NEXT_BUTTON_TEXTS):
            break
        page.wait_for_timeout(4000)
        rows += _collect_json_rows(page) or _collect_dom_rows(page)
    return rows


def run_sync(log_id: int, date_from: date, date_to: date, company: dict) -> None:
    """同步线程主体：登录（或复用会话）→ 抓取 → 入库 → 更新日志。"""
    # playwright 启动时要在临时目录 mkdtemp（playwright-artifacts-*）；部分环境
    # （受限令牌/杀软/沙箱宿主）对系统 %TEMP% 拒绝写入 → EPERM。统一改到应用
    # 数据目录下的自管 tmp（确保可写）；进程级变量，对本服务的浏览器实例生效。
    tmp_dir = config.TAX_SYNC_STORAGE_DIR / "tmp"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        os.environ["TMP"] = str(tmp_dir)
        os.environ["TEMP"] = str(tmp_dir)
    except OSError:
        pass                        # 保底：仍用系统 TEMP，失败信息会落日志
    task = _task(log_id)
    code = (company.get("code") or "DEFAULT").upper()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _finish(log_id, "failed", message="服务器未安装 playwright（requirements 缺失），无法同步")
        return

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=config.TAX_SYNC_HEADLESS)
            context = browser.new_context(
                storage_state=str(_storage_file(code)) if session_fresh(code) else None,
                ignore_https_errors=True,          # 平台证书链在内网环境偶发不完整
                locale="zh-CN",
            )
            page = context.new_page()
            rows: list[dict] = []
            if session_fresh(code):
                _goto_query_page(page, date_from, date_to)
                # 保活分支也要防"会话其实已失效"：既看提示文本，也看登录表单是否出现
                if not (_page_text_has(page, _LOGIN_HINTS) or _login_form_visible(page)):
                    rows = _scrape_all_pages(page, task)
            if not rows:
                _login(page, log_id, company)      # 含人工验证等待（可见窗口）
                _set_status(log_id, "running", message="登录成功，开始抓取")
                _goto_query_page(page, date_from, date_to)
                rows = _scrape_all_pages(page, task)

            # 去重（多页/双通道重复）
            seen, uniq = set(), []
            for r in rows:
                if r["invoice_no"] not in seen:
                    seen.add(r["invoice_no"])
                    uniq.append(r)
            if not uniq:
                # 抓 0 张几乎必然是"没真正登录/页面改版"，判失败防止假成功
                # （用户曾遇到"秒跳完成页"即此 bug，2026-10-17）
                _snap(page, "step4-empty-result")
                _finish(log_id, "failed", fetched=0, inserted=0, skipped=0,
                        message="未抓取到任何发票（很可能未真正登录或平台页面改版）。"
                                "请查看 app/data/tax_session/debug/ 下截图定位。")
                context.close()
                browser.close()
                return
            with SessionLocal() as db:
                counts = upsert_invoices(db, uniq, company)
            _finish(log_id, "success", fetched=len(uniq),
                    inserted=counts["inserted"], skipped=counts["skipped_duplicate"],
                    message=f"区间 {date_from}~{date_to}，主体 {code}"
                            f"（税号 {company.get('tax_no') or '-'}）")
            context.close()
            browser.close()
    except Exception as exc:  # noqa: BLE001 - 任何平台异常都落到日志
        _finish(log_id, "failed", message=f"{type(exc).__name__}: {exc}")


def _finish(log_id: int, status: str, *, fetched: int = 0, inserted: int = 0,
            skipped: int = 0, message: str | None = None) -> None:
    with SessionLocal() as db:
        log = db.get(InvoiceSyncLog, log_id)
        if log is not None:
            log.status = status
            log.finished_at = datetime.now()
            log.fetched = fetched
            log.inserted = inserted
            log.skipped_duplicate = skipped
            if message:
                log.message = message[:2000]
            db.commit()
    with _LOCK:
        _TASKS.pop(log_id, None)


def start_sync(date_from: date, date_to: date, subject_code: str) -> int:
    """发起同步（路由调用）：创建日志行并启动后台线程，返回 log_id。

    多公司口径：凭据按主体码预充（`CTMS_TAX_SYNC_<主体码>_USERNAME`），
    主体码必须是系统设置「我方公司」字典内的有效值；同一时刻只允许一个同步任务。
    """
    from .. import dicts

    code = (subject_code or "").strip().upper()
    company = config.tax_sync_company(code)
    if not config.TAX_SYNC_ENABLED:
        raise ValueError("发票同步未启用（CTMS_TAX_SYNC_ENABLED=0）")
    if company is None or not company.get("username") or not company.get("password"):
        raise ValueError(
            f"主体 {code or '(未选)'} 未配置同步凭据：请设置 "
            f"CTMS_TAX_SYNC_{code}_USERNAME / CTMS_TAX_SYNC_{code}_PASSWORD")
    with SessionLocal() as db:
        subjects = {s["code"] for s in dicts.get_subjects(db)}
        if code not in subjects:
            raise ValueError(f"主体码 {code} 不在系统设置「我方公司」字典中，请先维护")
    # 无头模式（容器/服务器）没有可见窗口，无法人工完成点字/滑块/短信验证：
    # 没有有效会话就直接拒绝，并给出可执行的两条路，避免用户对着"等待验证"干等。
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                       or os.name == "nt")
    if not session_fresh(code):
        if config.TAX_SYNC_HEADLESS:
            raise ValueError(
                "当前为无头模式（容器/服务器），无法弹出浏览器窗口完成人工验证。"
                "请任选其一：① 在办公机登录税局后把 "
                f"app/data/tax_session/state_{code}.json 复制到容器对应目录（1 小时内有效）；"
                "② 改用「上传发票包」或浏览器桥接通道同步。")
        if not has_display:
            raise ValueError(
                "未检测到图形界面（无 DISPLAY），浏览器无法弹出窗口。"
                "请设置 CTMS_TAX_SYNC_HEADLESS=1 并使用会话文件，"
                "或在有桌面的机器上运行同步。")
    with _LOCK:
        running = (SessionLocal()
                   .query(InvoiceSyncLog)
                   .filter(InvoiceSyncLog.status.in_(["running", "waiting_sms"]))
                   .first())
        if running is not None:
            raise ValueError("已有同步任务进行中，请等待完成后再发起")
    with SessionLocal() as db:
        log = InvoiceSyncLog(
            date_from=date_from, date_to=date_to, subject_code=code,
            tax_no=company.get("tax_no") or None, status="running",
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        log_id = log.id
    threading.Thread(target=run_sync, args=(log_id, date_from, date_to, company),
                     daemon=True).start()
    return log_id
