"""Word(.docx) → HTML 保真转换（CR-051）：以 mammoth 为主 + python-docx 补排版。

- **mammoth**：负责语义结构（标题/加粗/斜体/列表/表格合并单元格/图片 base64），质量远高于手写 XML；
- **python-docx**：补齐 mammoth 不保留的版式——段落对齐、首行缩进、字号（按文本顺序回填样式）；
- 输出 HTML 仍经服务端白名单清洗；图片由 mammoth 内嵌为 data URI。
"""
from __future__ import annotations

import html
import io
import re

import mammoth
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

#: 中英文 Word 样式名 → 语义标签（mammoth style map）
STYLE_MAP = """
p[style-name='Title'] => h1.doc-title:fresh
p[style-name='标题'] => h1.doc-title:fresh
p[style-name='Heading 1'] => h1:fresh
p[style-name='Heading 2'] => h2:fresh
p[style-name='Heading 3'] => h3:fresh
p[style-name='Heading 4'] => h4:fresh
p[style-name='标题 1'] => h1:fresh
p[style-name='标题 2'] => h2:fresh
p[style-name='标题 3'] => h3:fresh
p[style-name='标题 4'] => h4:fresh
"""

#: 无害提示：Word 的表格属性例外（tblPrEx）等，转换不受影响，不展示给用户
_IGNORED_WARNING_PREFIXES = (
    "An unrecognised element was ignored: w:tblPrEx",
    "An unrecognised element was ignored: w:proofErr",
    "An unrecognised element was ignored: w:bookmarkStart",
    "An unrecognised element was ignored: w:bookmarkEnd",
)

_BLOCK_RE = re.compile(r"<(p|h[1-6])([^>]*)>(.*?)</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _plain(fragment: str) -> str:
    return html.unescape(_TAG_RE.sub("", fragment)).replace("\u00a0", " ").strip()


def _align_style(para) -> list[str]:
    styles: list[str] = []
    align = para.alignment
    if align == WD_ALIGN_PARAGRAPH.CENTER:
        styles.append("text-align:center")
    elif align == WD_ALIGN_PARAGRAPH.RIGHT:
        styles.append("text-align:right")
    elif align in (WD_ALIGN_PARAGRAPH.JUSTIFY, WD_ALIGN_PARAGRAPH.DISTRIBUTE):
        styles.append("text-align:justify")
    first = para.paragraph_format.first_line_indent
    if first is not None and first > Pt(0):
        styles.append("text-indent:2em")
    # 字号：取首个非空 run
    for run in para.runs:
        if (run.text or "").strip() and run.font.size is not None:
            px = round(run.font.size.pt * 4 / 3)
            styles.append(f"font-size:{px}px")
            break
    return styles


def _enhance_with_docx(html_text: str, data: bytes, warnings: list[str]) -> str:
    """按文本顺序把 docx 段落的对齐/缩进/字号回填到 mammoth 生成的块级标签上。"""
    try:
        doc = Document(io.BytesIO(data))
    except Exception:  # noqa: BLE001
        return html_text

    blocks = list(_BLOCK_RE.finditer(html_text))
    used: set[int] = set()
    para_list = [p for p in doc.paragraphs if (p.text or "").strip()]
    # 表格单元格内的段落不参与匹配（mammoth 会单独渲染表格）
    for para in para_list[: len(blocks)]:
        text = re.sub(r"\s+", "", para.text)
        if not text:
            continue
        target = None
        for idx, m in enumerate(blocks):
            if idx in used:
                continue
            if re.sub(r"\s+", "", _plain(m.group(3))) == text:
                target = (idx, m)
                break
        if target is None:
            continue
        idx, m = target
        used.add(idx)
        extra = _align_style(para)
        if not extra:
            continue
        attrs = m.group(2) or ""
        style_match = re.search(r'style="([^"]*)"', attrs)
        if style_match:
            merged = ";".join([s for s in [style_match.group(1), *extra] if s])
            new_attrs = attrs[:style_match.start()] + f'style="{merged}"' + attrs[style_match.end():]
        else:
            new_attrs = attrs + f' style="{";".join(extra)}"'
        repl = f"<{m.group(1)}{new_attrs}>{m.group(3)}</{m.group(1)}>"
        html_text = html_text[: m.start()] + repl + html_text[m.end():]
        blocks = list(_BLOCK_RE.finditer(html_text))
        used = {i for i, b in enumerate(blocks)
                if html_text.find(b.group(0)) >= 0 and b.group(0) in html_text[: m.start()]}
    return html_text


def _decorate_tables(html_text: str) -> str:
    """给表格补边框样式（mammoth 只输出语义 table）。"""
    return re.sub(
        r"<table([^>]*)>",
        lambda m: ('<table' + m.group(1) +
                   ' border="1" cellspacing="0" cellpadding="6"'
                   ' style="border-collapse:collapse;width:100%;">'),
        html_text,
    )


def _filter_warnings(messages) -> list[str]:
    """只保留对用户有意义的提示；`w:tblPrEx` 等无害元素忽略提示不展示。"""
    out: list[str] = []
    for m in messages or []:
        if getattr(m, "type", "") not in ("warning", "error"):
            continue
        msg = m.message or ""
        if any(msg.startswith(p) for p in _IGNORED_WARNING_PREFIXES):
            continue
        out.append(msg)
    return out


def docx_to_html(data: bytes) -> dict:
    """docx → {html, warnings, images_bytes}。失败抛 ValueError。"""
    try:
        result = mammoth.convert_to_html(io.BytesIO(data), style_map=STYLE_MAP)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"不是有效的 docx 文件：{exc}")
    warnings = _filter_warnings(result.messages)
    html_text = result.value or "<p></p>"
    html_text = _enhance_with_docx(html_text, data, warnings)
    html_text = _decorate_tables(html_text)
    return {"html": html_text, "warnings": warnings, "images_bytes": 0}
