"""`.env` 加载测试（V2.4）：配置来源优先级、解析容错与测试隔离防线。

背景：项目不引入 python-dotenv，但需要支持"照 `.env.example` 填一个 `.env` 就生效"。
规则：**真实环境变量 > `.env` 文件 > 代码默认值**；解析是纯函数，便于单测。
"""
from __future__ import annotations

import os

from app.config import load_env_file, parse_env_text


class TestParse:
    def test_basic_pairs(self):
        assert parse_env_text("A=1\nB=hello\n") == {"A": "1", "B": "hello"}

    def test_ignores_comments_and_blank_lines(self):
        text = "# 注释\n\n   \nA=1\n   # 缩进注释\nB=2\n"
        assert parse_env_text(text) == {"A": "1", "B": "2"}

    def test_strips_surrounding_quotes(self):
        assert parse_env_text('A="1 2"\nB=\'x=y\'\n') == {"A": "1 2", "B": "x=y"}

    def test_export_prefix(self):
        assert parse_env_text("export A=1\n") == {"A": "1"}

    def test_inner_equals_is_kept(self):
        """值里出现 `=` 必须原样保留：连接串、base64 密钥都会被截断。"""
        assert parse_env_text("CTMS_DB_URL=postgresql://u:p@h/db?sslmode=require\n") == {
            "CTMS_DB_URL": "postgresql://u:p@h/db?sslmode=require"}

    def test_empty_value_is_allowed(self):
        assert parse_env_text("A=\n") == {"A": ""}

    def test_garbage_lines_are_skipped(self):
        assert parse_env_text("no equals sign\n=novalue\nA=1\n") == {"A": "1"}

    def test_crlf_not_leaked(self):
        """Windows 保存的 `.env` 是 CRLF，`\\r` 不能被带进值里。"""
        assert parse_env_text("A=1\r\nB=2\r\n") == {"A": "1", "B": "2"}

    def test_ignores_none(self):
        assert parse_env_text(None) == {}

    def test_inline_comment_is_stripped(self):
        """行内注释必须剥离：`.env.example` 模板里到处是 `KEY=值   # 说明`。"""
        assert parse_env_text("A=300   # 发送节流\n") == {"A": "300"}

    def test_inline_comment_on_int_param_stays_parsable(self):
        """回归防线：模板里那种带行内注释的整数参数，剥离后必须能被 int() 解析。

        不修这条的话，用户照模板取消注释 → `int("300   # …")` → ValueError →
        **后端启动即崩**（比"配置不生效"严重得多）。
        """
        parsed = parse_env_text("CTMS_FEISHU_SEND_INTERVAL_MS=300    # 节流\n")
        assert int(parsed["CTMS_FEISHU_SEND_INTERVAL_MS"]) == 300

    def test_hash_without_leading_space_is_kept(self):
        """`#` 前没有空白时是**值的一部分**，不能被当注释切掉。"""
        assert parse_env_text("A=p@ss#word\n") == {"A": "p@ss#word"}

    def test_quoted_value_keeps_hash(self):
        assert parse_env_text('A="a # b"\n') == {"A": "a # b"}


class TestLoad:
    def test_missing_file_returns_none(self, tmp_path):
        assert load_env_file(tmp_path / "nope.env") is None

    def test_injects_values(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CTMS_TEST_ENVFILE_VALUE", raising=False)
        f = tmp_path / ".env"
        f.write_text("CTMS_TEST_ENVFILE_VALUE=from-file\n", encoding="utf-8")
        assert load_env_file(f) == f
        assert os.environ["CTMS_TEST_ENVFILE_VALUE"] == "from-file"
        monkeypatch.delenv("CTMS_TEST_ENVFILE_VALUE", raising=False)

    def test_existing_env_wins(self, tmp_path, monkeypatch):
        """**已有环境变量优先**：生产注入的值不能被仓库里的 `.env` 覆盖。"""
        monkeypatch.setenv("CTMS_TEST_ENVFILE_WINS", "from-process")
        f = tmp_path / ".env"
        f.write_text("CTMS_TEST_ENVFILE_WINS=from-file\n", encoding="utf-8")
        load_env_file(f)
        assert os.environ["CTMS_TEST_ENVFILE_WINS"] == "from-process"

    def test_quoted_url_value(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CTMS_TEST_ENVFILE_URL", raising=False)
        f = tmp_path / ".env"
        f.write_text('CTMS_TEST_ENVFILE_URL="postgresql://u:p@h/db?sslmode=require"\n',
                     encoding="utf-8")
        load_env_file(f)
        assert os.environ["CTMS_TEST_ENVFILE_URL"] == "postgresql://u:p@h/db?sslmode=require"
        monkeypatch.delenv("CTMS_TEST_ENVFILE_URL", raising=False)

    def test_cannot_break_test_isolation(self, tmp_path):
        """回归防线：`CTMS_DB_URL` 由 conftest 决定，`.env` 不得改写它。

        否则"项目根放了个指向生产库的 `.env`"会让 pytest 直接读写生产数据 ——
        这是最危险的一类配置事故，必须有测试钉住。
        """
        f = tmp_path / ".env"
        f.write_text("CTMS_DB_URL=sqlite:///should-not-take-effect.db\n", encoding="utf-8")
        before = os.environ["CTMS_DB_URL"]
        load_env_file(f)
        assert os.environ["CTMS_DB_URL"] == before
