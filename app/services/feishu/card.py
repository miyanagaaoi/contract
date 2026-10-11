"""飞书消息卡片构造（V2.4）。

统一用**卡片 JSON 2.0**（`schema: "2.0"`）：2.0 把"卡片可更新/回调有效期"统一为 14 天，
且 `behaviors` 结构比 1.0 清晰（见 `docs/27` §9 官方文档）。

本模块只产出可序列化的 `dict`，**不发网络请求**；调用方（`notify_service`）负责
`json.dumps(..., ensure_ascii=False)` 后作为 `im/v1/messages` 的 `content` 传入。

字段取值一律走 `getattr` 容错：8 类单据模型字段并不完全相同（例如盘点单没有往来单位），
推送不该因为某个字段缺失就整条失败。
"""
from __future__ import annotations

from ... import config

# 卡片模板色（飞书预置）：区分语义，不追求花哨
TEMPLATE_BLUE = "blue"        # 待办 / 信息
TEMPLATE_GREEN = "green"      # 通过
TEMPLATE_RED = "red"          # 驳回 / 已作废
TEMPLATE_ORANGE = "orange"    # 预警（质保/库存）

# 单据类型 → 前端详情页路径（与 `web/src/router/index.ts` 的路由一致；
# 链接给**用户浏览器**打开，飞书服务器不会访问它）
DOC_PATHS: dict[str, str] = {
    "purchase_request": "/purchase/requests",
    "purchase_order": "/purchase/orders",
    "sales_request": "/sales/requests",
    "sales_order": "/sales/orders",
    "stock_in": "/stock/in-orders",
    "stock_out": "/stock/out-orders",
    "stock_take": "/stock/takes",
    "stock_transfer": "/stock/transfers",
    # V2.5：财务域（前端路由在 M2 落地；先登记，避免卡片按钮静默消失，
    # 并与 `permissions.DOC_APPROVE_PERM` 的完整性断言保持一致）
    "payment": "/finance/payments",
    "receipt": "/finance/receipts",
    "invoice": "/finance/invoices",
}

# 每日摘要每条最多列几项（卡片 ≤30 KB；刷屏也会让人关掉机器人）
DIGEST_MAX_ITEMS = 8


def _fmt_amount(value) -> str:
    try:
        return f"{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _short(text, limit: int = 40) -> str:
    s = str(text or "").strip().replace("\n", " ")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def doc_url(kind: str, doc_id: int | None) -> str | None:
    """单据详情页链接；未配置 `CTMS_FEISHU_BASE_URL` 时返回 None（卡片就不显示按钮）。"""
    base = config.FEISHU_BASE_URL
    path = DOC_PATHS.get(kind)
    if not base or not path or not doc_id:
        return None
    return f"{base}{path}/{doc_id}"


def _body(*elements: dict) -> dict:
    return {"schema": "2.0",
            "config": {"update_multi": True},
            "body": {"elements": [e for e in elements if e]}}


def _header(title: str, template: str) -> dict:
    return {"title": {"tag": "plain_text", "content": title}, "template": template}


def _markdown(content: str) -> dict:
    return {"tag": "markdown", "content": content}


def _link_button(text: str, url: str | None) -> dict:
    """跳转按钮（`open_url` 行为；飞书服务器不参与，纯客户端跳转）。"""
    if not url:
        return {}
    return {"tag": "button", "text": {"tag": "plain_text", "content": text},
            "type": "primary",
            "behaviors": [{"type": "open_url", "default_url": url}]}


def _doc_lines(doc, *, with_party: bool = True, with_amount: bool = True) -> list[str]:
    """单据公共信息行（各类型单据字段不完全一致，逐项容错）。"""
    lines: list[str] = []
    if getattr(doc, "doc_date", None):
        lines.append(f"- 单据日期：{doc.doc_date}")
    if with_party:
        party = (getattr(doc, "supplier_name", None) or getattr(doc, "customer_name", None)
                 or getattr(doc, "customer_name_text", None))
        if party:
            lines.append(f"- 往来单位：{party}")
    if with_amount and getattr(doc, "total_amount", None) is not None:
        lines.append(f"- 金额：{_fmt_amount(doc.total_amount)}")
    if getattr(doc, "handler_name", None):
        lines.append(f"- 经办人：{doc.handler_name}")
    if getattr(doc, "subject_name", None):
        lines.append(f"- 签约公司：{doc.subject_name}")
    if getattr(doc, "warehouse_name", None):
        lines.append(f"- 仓库：{doc.warehouse_name}")
    return lines


def build_doc_todo_card(doc, *, kind: str, kind_label: str,
                        actor_name: str | None = None) -> tuple[dict, str]:
    """待审核通知卡片。返回 `(card, title)`。"""
    doc_no = getattr(doc, "doc_no", "") or f"#{getattr(doc, 'id', '')}"
    title = f"{kind_label} {doc_no} 待审核"
    lines = [f"**{kind_label} {doc_no}** 提交审核" if not actor_name
             else f"**{kind_label} {doc_no}** 提交审核（发起人：{actor_name}）"]
    lines += _doc_lines(doc)
    if getattr(doc, "remark", None):
        lines.append(f"> 备注：{_short(doc.remark, 60)}")
    card = {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": _header(f"{kind_label}待审核", TEMPLATE_BLUE),
        "body": {"elements": [
            _markdown("\n".join(lines)),
            _link_button("查看并审核", doc_url(kind, getattr(doc, "id", None))),
        ]},
    }
    return card, title


def build_doc_result_card(doc, *, kind: str, kind_label: str, result: str,
                          reason: str | None = None,
                          operator: str | None = None) -> tuple[dict, str]:
    """审核结果通知卡片。`result`：`approved` / `rejected` / `unapproved` / `completed` / `voided`。"""
    labels = {"approved": ("已审核通过", TEMPLATE_GREEN),
              "rejected": ("已驳回", TEMPLATE_RED),
              "unapproved": ("已反审核", TEMPLATE_ORANGE),
              "completed": ("已完成", TEMPLATE_GREEN),
              "voided": ("已作废", TEMPLATE_RED)}
    result_label, template = labels.get(result, (result, TEMPLATE_BLUE))
    doc_no = getattr(doc, "doc_no", "") or f"#{getattr(doc, 'id', '')}"
    title = f"{kind_label} {doc_no} {result_label}"
    lines = [f"**{kind_label} {doc_no}** {result_label}"]
    if operator:
        lines.append(f"- 操作人：{operator}")
    lines += _doc_lines(doc)
    if reason:
        lines.append(f"> 原因：{_short(reason, 80)}")
    card = {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": _header(f"{kind_label}{result_label}", template),
        "body": {"elements": [
            _markdown("\n".join(lines)),
            _link_button("查看单据", doc_url(kind, getattr(doc, "id", None))),
        ]},
    }
    return card, title


def build_digest_card(*, title: str, markdown: str,
                      template: str = TEMPLATE_ORANGE) -> tuple[dict, str]:
    """每日摘要卡片（待办 + 质保到期 + 库存预警合为一条，避免刷屏）。"""
    card = {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": _header(title, template),
        "body": {"elements": [
            _markdown(markdown),
            _link_button("打开系统", config.FEISHU_BASE_URL or None),
        ]},
    }
    return card, title


def build_test_card(*, app_name: str, version: str, user_name: str) -> tuple[dict, str]:
    """系统管理页「发送测试消息」用。"""
    title = "CTMS 飞书接入测试"
    markdown = (f"**{app_name} 飞书接入已连通**\n"
                f"- 收件人：{user_name}\n"
                f"- 版本：{version}\n"
                f"- 若能看到这条消息，说明应用机器人权限与可用范围均正常。")
    card = {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": _header(title, TEMPLATE_GREEN),
        "body": {"elements": [
            _markdown(markdown),
            _link_button("打开系统", config.FEISHU_BASE_URL or None),
        ]},
    }
    return card, title
