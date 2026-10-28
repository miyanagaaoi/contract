"""发票文件导入与识别（CR-026）：单张 PDF / ZIP 发票包 → 解析 → 建单 + 挂附件。

口径（2026-10-28 业务确认）：
- 只保留「上传识别」通道：不再依赖 Playwright/浏览器插件；
- 支持 **单张 PDF** 与 **ZIP 发票包**（zip 内 PDF/XML/OFD 混合）；
- PDF 识别用**文本层 + 规则解析**（不引入 OCR）：发票号码、开票日期、金额/税额/价税合计、
  销售方/购买方名称与税号、税率；
- 识别成功 → **创建发票**（进项、已认证、未确认、`sync_source=upload`）并挂原始文件；
  发票号已存在 → 只补挂附件（幂等），不重复建单；
- 文件名可兜底发票号（`dzfp_<20位票号>_...pdf`）；无票号且内容解析不出的文件 → 只挂到
  "未匹配"清单返回给用户，不再静默丢弃（前端会列出原因）。
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.orm import Session

from .. import config, dicts
from ..models import Attachment
from ..models_doc import INVOICE_IN, Invoice
from . import numbering_service

ZERO = Decimal("0")

# ---------- PDF 文本解析规则（数电票/电子发票共用） ----------
_PATTERNS = {
    "invoice_no": [r"发票号码[：:]\s*([0-9]{8,20})", r"数电发票号码[：:]\s*([0-9]{8,20})"],
    "invoice_date": [r"开票日期[：:]\s*(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})"],
    "total_amount": [r"价税合计.{0,30}?[（(]小写[）)]\s*[¥￥]?\s*([\d,]+\.?\d*)"],
    "amount": [r"合\s*计\s*[¥￥]?\s*([\d,]+\.\d{2})"],
    "tax_amount": [r"合\s*计\s*[¥￥]?\s*[\d,]+\.\d{2}\s*[¥￥]?\s*([\d,]+\.\d{2})"],
    "tax_rate": [r"(\d{1,2})%"],
    "seller_name": [r"销\s*售\s*方.{0,40}?名\s*称[：:]\s*([^\s：:]{2,40})"],
    "seller_tax_no": [r"销\s*售\s*方.{0,60}?纳税人识别号[：:]\s*([0-9A-Z]{15,20})"],
    "buyer_name": [r"购\s*买\s*方.{0,40}?名\s*称[：:]\s*([^\s：:]{2,40})"],
    "buyer_tax_no": [r"购\s*买\s*方.{0,60}?纳税人识别号[：:]\s*([0-9A-Z]{15,20})"],
}


def _pdf_text(data: bytes) -> str:
    """提取 PDF 文本层（失败返回空串：扫描件/加密件走文件名兜底）。"""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:5])
    except Exception:
        return ""


def _dec(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value.replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def parse_invoice_text(text: str, file_name: str = "") -> dict:
    """从发票 PDF 文本中解析票面字段（缺失的留空，不臆造）。"""
    text = text or ""
    out: dict = {}

    for key in ("invoice_no", "seller_name", "seller_tax_no", "buyer_name", "buyer_tax_no"):
        for pat in _PATTERNS[key]:
            m = re.search(pat, text)
            if m:
                out[key] = m.group(1).strip()
                break

    for pat in _PATTERNS["invoice_date"]:
        m = re.search(pat, text)
        if m:
            try:
                out["invoice_date"] = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
            break

    for key in ("total_amount", "amount", "tax_amount"):
        for pat in _PATTERNS[key]:
            m = re.search(pat, text)
            if m:
                val = _dec(m.group(1))
                if val is not None:
                    out[key] = val
                    break

    for pat in _PATTERNS["tax_rate"]:
        m = re.search(pat, text)
        if m:
            try:
                out["tax_rate"] = Decimal(m.group(1))
            except InvalidOperation:
                pass
            break

    # 金额口径补齐：价税合计 = 金额 + 税额
    if out.get("total_amount") is None and out.get("amount") is not None:
        out["total_amount"] = (out.get("amount") or ZERO) + (out.get("tax_amount") or ZERO)
    if out.get("tax_amount") is None and out.get("total_amount") is not None and out.get("amount"):
        out["tax_amount"] = out["total_amount"] - out["amount"]

    # 文件名兜底发票号：dzfp_<20位>_... 或纯数字
    if not out.get("invoice_no"):
        m = re.search(r"(\d{20})", Path(file_name).name)
        if m:
            out["invoice_no"] = m.group(1)
    return out


def _direction_of(inv: Invoice) -> str:
    return inv.invoice_direction or INVOICE_IN


def _attach(db: Session, inv: Invoice, file_name: str, data: bytes, dest_dir: Path) -> None:
    safe = f"{inv.invoice_no}_{Path(file_name).name}"
    (dest_dir / safe).write_bytes(data)
    db.add(Attachment(
        file_name=Path(file_name).name,
        stored_path=f"invoices/{safe}",
        content_type=("application/pdf" if safe.lower().endswith(".pdf") else "application/xml"),
        size_bytes=len(data), object_type="invoice", object_id=inv.id,
    ))


def import_files(db: Session, files: list[tuple[str, bytes]]) -> dict:
    """导入一组文件（单 PDF 或 zip 解出的条目）→ 建单/挂附件，返回逐项结果。"""
    dest_dir = Path(config.UPLOAD_DIR) / "invoices"
    dest_dir.mkdir(parents=True, exist_ok=True)
    subjects = {s["code"]: s for s in dicts.get_subjects(db)}
    by_tax = {str(s.get("tax_no") or "").strip(): s for s in subjects.values() if s.get("tax_no")}

    created, attached, failed = [], [], []
    for name, data in files:
        try:
            text = _pdf_text(data) if name.lower().endswith(".pdf") else ""
            parsed = parse_invoice_text(text, name)
            no = parsed.get("invoice_no")
            if not no:
                # 无票号：xml/ofd 之类只尝试按文件名匹配已有发票
                m = re.search(r"(\d{20})", Path(name).name)
                no = m.group(1) if m else None
            if not no:
                failed.append({"file": name, "reason": "无法识别发票号码（无文本层且文件名无票号）"})
                continue

            inv = (db.query(Invoice)
                   .filter(Invoice.invoice_direction == INVOICE_IN, Invoice.invoice_no == no)
                   .first())
            if inv is not None:
                _attach(db, inv, name, data, dest_dir)
                db.commit()
                attached.append({"file": name, "invoice_no": no, "invoice_id": inv.id})
                continue

            # 新建发票（识别字段；缺失的保持为空，金额缺省 0）
            day = parsed.get("invoice_date") or date.today()
            subject = by_tax.get(str(parsed.get("buyer_tax_no") or "").strip())
            inv = Invoice(
                doc_no=numbering_service.next_doc_no(db, "invoice", day),
                doc_date=day, status="draft",
                invoice_direction=INVOICE_IN, invoice_no=no,
                invoice_type=None,
                invoice_date=day,
                tax_rate=parsed.get("tax_rate"),
                amount=parsed.get("amount") or ZERO,
                tax_amount=parsed.get("tax_amount") or ZERO,
                total_amount=parsed.get("total_amount") or ZERO,
                auth_status="authenticated", bind_status="unbound",
                sync_source="upload", synced_at=datetime.now(),
                seller_name=parsed.get("seller_name"),
                seller_tax_no=parsed.get("seller_tax_no"),
                buyer_name=parsed.get("buyer_name"),
                buyer_tax_no=parsed.get("buyer_tax_no"),
                our_company_code=(subject or {}).get("code"),
                our_company_name=(subject or {}).get("name"),
                subject_code=(subject or {}).get("code"),
                subject_name=(subject or {}).get("name"),
                party_name=parsed.get("seller_name"),
                remark=f"上传识别导入（{date.today().isoformat()}）",
            )
            db.add(inv)
            db.flush()
            _attach(db, inv, name, data, dest_dir)
            db.commit()
            created.append({"file": name, "invoice_no": no, "invoice_id": inv.id,
                            "amount": float(inv.total_amount or 0),
                            "parsed_fields": sorted(k for k, v in parsed.items() if v is not None)})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed.append({"file": name, "reason": f"{type(exc).__name__}: {exc}"[:300]})
    return {"created": created, "attached": attached, "failed": failed,
            "total_files": len(files)}


def expand_upload(file_name: str, data: bytes) -> list[tuple[str, bytes]]:
    """把上传内容展开成 (文件名, 字节)：zip 解包，PDF 原样。"""
    if file_name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return [(n, zf.read(n)) for n in zf.namelist() if not n.endswith("/")]
    return [(file_name, data)]
