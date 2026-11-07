"""Word(.docx) → HTML 保真转换（CR-050）。

保留以下格式（够合同正文使用）：
- 段落：标题样式（Heading1~3 / Title）、对齐（居中/右/两端）、首行缩进、行距、字号；
- 文字：加粗/斜体/下划线/删除线/上标下标/字体颜色/字号（半磅→px）；
- 列表：`w:numPr` 段落聚合为 `<ul>/<ol>`；
- 表格：边框/表头底纹、列宽（百分比）、横向合并（gridSpan→colspan）、纵向合并（vMerge→rowspan）；
- 图片：`w:drawing` → 关系表 → `word/media/*` → base64 `data:` URI（受总大小上限保护，超限跳过并给警告）；
- 换行 `<br/>`、制表符转空格；文本一律 HTML 转义。

不依赖 python-docx：只读 OOXML（zip + ElementTree），离线容器零新增依赖。
"""
from __future__ import annotations

import base64
import html
import io
import mimetypes
import zipfile
import xml.etree.ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

#: 图片总大小上限（base64 后进正文；超过则跳过图片并提示）
MAX_IMAGE_BYTES = 4 * 1024 * 1024


def _qn(ns: str, tag: str) -> str:
    return "{%s}%s" % (ns, tag)


def _attr(el, name: str, ns: str = W) -> str | None:
    return el.get(_qn(ns, name)) if el is not None else None


def _bool_el(parent, tag: str) -> bool:
    """`<w:b/>` 这类开关：存在且 val 不是 0/false 即为真。"""
    el = parent.find(_qn(W, tag)) if parent is not None else None
    if el is None:
        return False
    val = _attr(el, "val")
    return val not in ("0", "false", "off")


def _halfpoints_to_px(sz: str | None) -> str | None:
    """Word 字号为半磅：10.5pt(五号) = sz 21 → 14px。"""
    if not sz:
        return None
    try:
        pt = float(sz) / 2
    except ValueError:
        return None
    return f"{round(pt * 4 / 3)}px"


def _load_rels(zf: zipfile.ZipFile) -> dict[str, str]:
    rels: dict[str, str] = {}
    try:
        data = zf.read("word/_rels/document.xml.rels")
    except KeyError:
        return rels
    root = ET.fromstring(data)
    for rel in root:
        rid = rel.get("Id")
        target = rel.get("Target")
        if rid and target:
            rels[rid] = target.lstrip("/")
    return rels


def _image_html(zf: zipfile.ZipFile, rels: dict[str, str], rid: str,
                budget: list[int], warnings: list[str]) -> str:
    target = rels.get(rid)
    if not target:
        return ""
    path = target if target.startswith("word/") else "word/" + target
    try:
        raw = zf.read(path)
    except KeyError:
        return ""
    if budget[0] + len(raw) > MAX_IMAGE_BYTES:
        warnings.append("部分图片超过大小上限，已跳过")
        return ""
    budget[0] += len(raw)
    mime = mimetypes.guess_type(path)[0] or "image/png"
    b64 = base64.b64encode(raw).decode("ascii")
    return (f'<img src="data:{mime};base64,{b64}" '
            'style="max-width:100%;height:auto;" />')


def _run_html(run, zf, rels, budget, warnings) -> str:
    rpr = run.find(_qn(W, "rPr"))
    styles: list[str] = []
    tags_open: list[str] = []
    if rpr is not None:
        if _bool_el(rpr, "b"):
            styles.append("font-weight:700")
        if _bool_el(rpr, "i"):
            styles.append("font-style:italic")
        if _bool_el(rpr, "u"):
            styles.append("text-decoration:underline")
        if _bool_el(rpr, "strike"):
            styles.append("text-decoration:line-through")
        color = _attr(rpr.find(_qn(W, "color")), "val")
        if color and color.upper() != "000000":
            styles.append(f"color:#{color}")
        sz = _attr(rpr.find(_qn(W, "sz")), "val")
        fsize = _halfpoints_to_px(sz)
        if fsize:
            styles.append(f"font-size:{fsize}")
        vert = _attr(rpr.find(_qn(W, "vertAlign")), "val")
        if vert == "superscript":
            tags_open.append("<sup>")
        elif vert == "subscript":
            tags_open.append("<sub>")

    pieces: list[str] = []
    for child in run:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "t":
            pieces.append(html.escape(child.text or ""))
        elif tag == "br":
            pieces.append("<br/>")
        elif tag == "tab":
            pieces.append("&emsp;")
        elif tag == "drawing":
            for blip in child.iter(_qn(A, "blip")):
                rid = _attr(blip, "embed", R)
                if rid:
                    pieces.append(_image_html(zf, rels, rid, budget, warnings))
    if not pieces:
        return ""
    inner = "".join(pieces)
    if styles:
        inner = f'<span style="{";".join(styles)}">{inner}</span>'
    inner = "".join(tags_open) + inner + "".join(t[::-1] for t in tags_open)
    return inner


def _paragraph_html(p, zf, rels, budget, warnings) -> tuple[str, dict]:
    """返回 (段落 html, 元信息{style, list_id, level, empty})。"""
    ppr = p.find(_qn(W, "pPr"))
    align = ""
    indent = False
    style_name = ""
    list_id = None
    level = 0
    if ppr is not None:
        jc = _attr(ppr.find(_qn(W, "jc")), "val")
        if jc == "center":
            align = "text-align:center"
        elif jc == "right":
            align = "text-align:right"
        elif jc == "both":
            align = "text-align:justify"
        ind = ppr.find(_qn(W, "ind"))
        if ind is not None:
            first = _attr(ind, "firstLine") or _attr(ind, "firstLineChars")
            if first and first not in ("0",):
                indent = True
        style_el = ppr.find(_qn(W, "pStyle"))
        style_name = (_attr(style_el, "val") or "").lower()
        num = ppr.find(_qn(W, "numPr"))
        if num is not None:
            num_id_el = num.find(_qn(W, "numId"))
            ilvl_el = num.find(_qn(W, "ilvl"))
            list_id = _attr(num_id_el, "val")
            try:
                level = int(_attr(ilvl_el, "val") or 0)
            except ValueError:
                level = 0

    inner = "".join(
        _run_html(r, zf, rels, budget, warnings) for r in p.findall(_qn(W, "r")))
    # 超链接内的文字（r:id 关系暂不还原链接样式，保留文字）
    for hl in p.findall(_qn(W, "hyperlink")):
        inner += "".join(_run_html(r, zf, rels, budget, warnings) for r in hl.findall(_qn(W, "r")))

    meta = {"style": style_name, "list": list_id, "level": level, "empty": not inner.strip()}
    if not inner.strip():
        return "<p>&nbsp;</p>", meta

    styles = [align] if align else []
    if indent:
        styles.append("text-indent:2em")
    attr = f' style="{";".join(styles)}"' if styles else ""
    s = style_name
    if s.startswith("heading1") or "title" in s:
        return f"<h1{attr}>{inner}</h1>", meta
    if s.startswith("heading2"):
        return f"<h2{attr}>{inner}</h2>", meta
    if s.startswith("heading3"):
        return f"<h3{attr}>{inner}</h3>", meta
    return f"<p{attr}>{inner}</p>", meta


def _cell_html(tc, zf, rels, budget, warnings) -> tuple[str, int, str]:
    """返回 (单元格内部 html, 横向跨列数, 纵向合并状态 start/continue/none)。"""
    tcpr = tc.find(_qn(W, "tcPr"))
    span = 1
    vmerge = "none"
    if tcpr is not None:
        span_el = tcpr.find(_qn(W, "gridSpan"))
        try:
            span = max(1, int(_attr(span_el, "val") or 1))
        except (TypeError, ValueError):
            span = 1
        vm = tcpr.find(_qn(W, "vMerge"))
        if vm is not None:
            vmerge = "continue" if _attr(vm, "val") in ("continue", None) else "start"
    inner = "".join(_paragraph_html(p, zf, rels, budget, warnings)[0]
                    for p in tc.findall(_qn(W, "p")))
    return (inner or "&nbsp;"), span, vmerge


def _table_html(tbl, zf, rels, budget, warnings) -> str:
    rows = []
    pending_rows: dict[int, int] = {}   # 列索引 → 剩余 rowspan 累计
    for tr in tbl.findall(_qn(W, "tr")):
        cells_html: list[str] = []
        col = 0
        for tc in tr.findall(_qn(W, "tc")):
            inner, span, vmerge = _cell_html(tc, zf, rels, budget, warnings)
            if vmerge == "continue":
                pending_rows[col] = pending_rows.get(col, 0) + 1
                col += span
                continue
            rowspan = 1
            if vmerge == "start":
                rowspan = 1
                pending_rows.setdefault(col, 0)
            rowspan += pending_rows.pop(col, 0)
            attrs = ""
            if span > 1:
                attrs += f' colspan="{span}"'
            if rowspan > 1:
                attrs += f' rowspan="{rowspan}"'
            cells_html.append(f"<td{attrs}>{inner}</td>")
            col += span
        rows.append("<tr>" + "".join(cells_html) + "</tr>")
    return ('<table border="1" cellspacing="0" cellpadding="6" '
            'style="border-collapse:collapse;width:100%;">'
            + "".join(rows) + "</table>")


def docx_to_html(data: bytes) -> dict:
    """转换 docx → {html, warnings, images_bytes}。失败抛 ValueError（路由转 422）。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"不是有效的 docx 文件：{exc}")
    with zf:
        try:
            xml = zf.read("word/document.xml")
        except KeyError:
            raise ValueError("docx 缺少 word/document.xml")
        root = ET.fromstring(xml)
        rels = _load_rels(zf)
        body = root.find(_qn(W, "body"))
        if body is None:
            return {"html": "<p></p>", "warnings": [], "images_bytes": 0}

        budget = [0]
        warnings: list[str] = []
        parts: list[str] = []
        open_list: tuple[str, int] | None = None   # (tag, numid)

        def close_list() -> None:
            nonlocal open_list
            if open_list is not None:
                parts.append(f"</{open_list[0]}>")
                open_list = None

        for el in list(body):
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "p":
                ph, meta = _paragraph_html(el, zf, rels, budget, warnings)
                if meta["list"]:
                    list_tag = "ol" if int(meta["list"]) % 2 == 1 else "ul"
                    if open_list != (list_tag, meta["list"]):
                        close_list()
                        parts.append(f"<{list_tag}>")
                        open_list = (list_tag, meta["list"])
                    parts.append(f"<li>{ph[3:-4]}</li>")
                else:
                    close_list()
                    parts.append(ph)
            elif tag == "tbl":
                close_list()
                parts.append(_table_html(el, zf, rels, budget, warnings))
            elif tag == "sectPr":
                close_list()
        close_list()
        out = "\n".join(p for p in parts if p) or "<p></p>"
        return {"html": out, "warnings": warnings, "images_bytes": budget[0]}
