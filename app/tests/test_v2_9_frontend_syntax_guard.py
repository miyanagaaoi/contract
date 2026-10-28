"""前端语法守卫（CR-028）：Vue/TS 源码里出现「孤立 async / 重复 async」等
脚本级语法错误时，`vite build` 仍可能通过，但页面会在 setup 阶段抛
ReferenceError 导致整页白屏（发票管理页实测）。

这里做静态文本守卫：命中即失败，提示具体文件与行号。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "web" / "src"

# 行首孤立关键字 / 重复关键字（真实故障写法：`async /** 注释 */`）
BAD_PATTERNS = [
    re.compile(r"^\s*async\s*/\*"),          # async /** ... */
    re.compile(r"^\s*async\s*$"),            # 单独一行 async
    re.compile(r"\basync\s+async\b"),        # async async function
    re.compile(r"^\s*(export\s+)?default\s*$"),  # 孤立 default
]


def _iter_sources():
    for path in ROOT.rglob("*"):
        if path.suffix in (".vue", ".ts") and path.is_file():
            yield path


def test_no_broken_js_keywords_in_frontend_sources():
    hits: list[str] = []
    for path in _iter_sources():
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pat in BAD_PATTERNS:
                if pat.search(line):
                    hits.append(f"{path.relative_to(ROOT.parent.parent)}:{no}: {line.strip()}")
                    break
    assert not hits, "前端源码存在会导致白屏的语法错误：\n" + "\n".join(hits)
