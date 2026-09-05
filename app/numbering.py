"""合同编号自动生成（MVP3）。

格式（紧凑式）：类型码 + 主体码 + 年份(4) + 月份(2) + 6位顺序号
例：PURZC202609000001
规则：序号按 「类型码+主体码+年份」 年度递增、次年重置；月份码取签订日期所在月。
实现：以库内已有编号尾部 6 位最大值推算（软删除占用不回用），避免预占导致跳号。
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy.orm import Session

from .models import Contract

_NO_RE = re.compile(r"^([A-Z]{3})([A-Z]{2})(\d{4})(\d{2})(\d{6})$")


def peek_seq(db: Session, type_code: str, subject_code: str, ref_date: date | None) -> int:
    """库内同 类型+主体+年份 的最大序号（不存在则 0）。"""
    year = (ref_date or date.today()).year
    prefix = f"{type_code.upper()}{subject_code.upper()}{year}"
    rows = (
        db.query(Contract.contract_no)
        .filter(Contract.contract_no.like(prefix + "%"))
        .all()
    )
    max_seq = 0
    for (no,) in rows:
        no = no or ""
        if not no.startswith(prefix):
            continue
        m = _NO_RE.match(no)
        if m and m.group(3) == str(year):
            seq = int(m.group(5))
            if seq > max_seq:
                max_seq = seq
    return max_seq


def next_number(db: Session, type_code: str, subject_code: str, ref_date: date | None) -> str:
    type_code = type_code.upper()
    subject_code = subject_code.upper()
    ref = ref_date or date.today()
    seq = peek_seq(db, type_code, subject_code, ref) + 1
    return f"{type_code}{subject_code}{ref.year}{ref.month:02d}{seq:06d}"
