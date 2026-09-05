"""BR 单元测试（P3 正式版：自动化测试基础）。

覆盖：编号格式（MVP3）、质保到期算法（BR5/Q2）、编号正则。纯函数为主，无外部依赖。
运行：app\\.venv\\Scripts\\python -m pytest app\\tests -q
"""
import re
from datetime import date

from app.models import compute_warranty_end
from app.numbering import _NO_RE, format_number


class TestWarrantyEnd:
    def test_example_from_spec(self):
        # BR5/Q2：2025-06-01 起 12 个月 → 2026-05-31（取到期当月最后一天）
        assert compute_warranty_end(date(2025, 6, 1), 12) == date(2026, 5, 31)

    def test_one_month(self):
        assert compute_warranty_end(date(2025, 6, 1), 1) == date(2025, 6, 30)

    def test_cross_year(self):
        assert compute_warranty_end(date(2025, 11, 15), 3) == date(2026, 1, 31)

    def test_min_months(self):
        # 至少按 1 个月处理
        assert compute_warranty_end(date(2025, 1, 10), 0) == date(2025, 1, 31)

    def test_leap_feb(self):
        assert compute_warranty_end(date(2024, 2, 1), 1) == date(2024, 2, 29)


class TestNumbering:
    def test_format(self):
        assert format_number("pur", "zc", 2026, 9, 1) == "PURZC202609000001"

    def test_format_seq_pad(self):
        assert format_number("SAL", "YX", 2026, 12, 123456).endswith("123456")

    def test_regex_match(self):
        no = format_number("PUR", "ZC", 2026, 9, 7)
        m = _NO_RE.fullmatch(no)
        assert m is not None
        assert m.groups() == ("PUR", "ZC", "2026", "09", "000007")

    def test_regex_rejects_others(self):
        assert _NO_RE.fullmatch("CG-2025-001") is None
        assert re.fullmatch(r"(?:SAL|PUR|COO|LAB|FIN|NDA)ZC\d{12}", format_number("PUR", "ZC", 2026, 1, 1)) is not None
