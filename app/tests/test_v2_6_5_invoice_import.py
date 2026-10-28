"""CR-026 回归：发票上传识别（单张 PDF / ZIP）→ 建单 + 挂附件。

覆盖：
1. PDF 文本规则解析（发票号码/日期/金额/税额/购销方/税率）；
2. 文件名兜底发票号（无文本层时）；
3. ZIP 导入：新建发票并挂附件；**重复上传只补挂附件**（幂等）；
4. 无法识别票号的文件进入 failed 清单（不再静默丢弃）。
"""
from __future__ import annotations

import io
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Attachment
from app.models_doc import Invoice
from app.services import invoice_import_service as svc

SAMPLE_TEXT = """电子发票（增值税专用发票）
发票号码：26142000001496803711
开票日期：2026年10月09日
购买方信息 名称：云羲（山西）数字科技有限公司 统一社会信用代码/纳税人识别号：91149900MAECLDF33U
销售方信息 名称：山西伟业房地产开发有限公司 统一社会信用代码/纳税人识别号：9114090277516473XM
项目名称 金额 税率 税额
*信息技术服务*服务费 28814.16 13% 3745.84
合 计 ¥28814.16 ¥3745.84
价税合计（大写）叁万贰仟伍佰陆拾元整 （小写）¥32560.00
"""


def test_parse_invoice_text_fields():
    r = svc.parse_invoice_text(SAMPLE_TEXT)
    assert r["invoice_no"] == "26142000001496803711"
    assert str(r["invoice_date"]) == "2026-10-09"
    assert r["amount"] == 28814.16 or float(r["amount"]) == 28814.16
    assert float(r["tax_amount"]) == 3745.84
    assert float(r["total_amount"]) == 32560.00
    assert r["tax_rate"] == 13
    assert "伟业" in r["seller_name"] and r["seller_tax_no"].startswith("9114")
    assert r["buyer_tax_no"] == "91149900MAECLDF33U"


def test_filename_fallback_invoice_no():
    r = svc.parse_invoice_text("", "dzfp_26147000000357453326_山西顺丰_20261014.pdf")
    assert r["invoice_no"] == "26147000000357453326"


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_zip_import_create_then_attach_only():
    no1, no2 = "26142000009999000001", "26142000009999000002"
    data = _zip({
        f"dzfp_{no1}_甲公司.pdf": b"%PDF-1.4 fake",
        f"dzfp_{no2}_乙公司.pdf": b"%PDF-1.4 fake",
        "说明.txt": b"no invoice number here",
    })
    entries = svc.expand_upload("invoices.zip", data)
    assert len(entries) == 3

    with SessionLocal() as db:
        first = svc.import_files(db, entries)
    assert len(first["created"]) == 2
    assert len(first["failed"]) == 1
    assert "说明.txt" in first["failed"][0]["file"]

    # 列表可见 + 已挂附件 + 标记为上传来源
    with SessionLocal() as db:
        rows = db.execute(select(Invoice).where(
            Invoice.invoice_no.in_([no1, no2]))).scalars().all()
        assert len(rows) == 2
        for inv in rows:
            assert inv.auth_status == "authenticated"
            assert inv.bind_status == "unbound"
            assert inv.sync_source == "upload"
            assert db.execute(select(Attachment).where(
                Attachment.object_type == "invoice",
                Attachment.object_id == inv.id)).scalars().first() is not None

    # 二次上传 → 只补挂附件，不重复建单
    with SessionLocal() as db:
        second = svc.import_files(db, entries)
    assert len(second["created"]) == 0 and len(second["attached"]) == 2

    # 清理（避免污染共享测试库）
    with SessionLocal() as db:
        for inv in db.execute(select(Invoice).where(
                Invoice.invoice_no.in_([no1, no2]))).scalars().all():
            db.query(Attachment).filter(Attachment.object_type == "invoice",
                                        Attachment.object_id == inv.id).delete()
            db.delete(inv)
        db.commit()
