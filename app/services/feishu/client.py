"""飞书开放平台出网客户端（**标准库实现，不引入第三方依赖**）。

## 为什么不用 lark-oapi / httpx

1. 本方案只用到 4 个 HTTPS 端点，为它引入 SDK 不划算；项目已有"自研 JWT、只用标准库"
   的先例（`app/security.py`）。
2. `lark-oapi` 的 `1.6.0`~`1.6.3` 与 `2.0.0.dev*` 因**Webhook 签名兼容性回归已被 PyPI yank**，
   引入即多一个需要盯版本的依赖；而本方案不需要事件订阅，用不到它的长连接与加解密。

## 端点（官方文档见 `docs/27-feishu-integration-plan.md` §9）

| 用途 | 请求 |
|---|---|
| 应用身份令牌（2 小时有效） | `POST {api}/open-apis/auth/v3/tenant_access_token/internal` |
| 授权码换 user_access_token | `POST {accounts}/oauth/v3/token`（form-urlencoded） |
| 取用户身份（open_id 等） | `GET  {api}/open-apis/authen/v1/user_info` |
| 发消息 | `POST {api}/open-apis/im/v1/messages?receive_id_type=open_id` |

## 安全

- `app_secret` 只在请求体里出现，**不进日志、不进异常消息、不入库**；
- 所有错误消息经 `_describe()` 归一，避免把响应体原样吐给前端（可能含内部信息）。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from ... import config

# 进程内 tenant_access_token 缓存（官方：最大有效期 2 小时；剩余 <30 分钟再取会返回**新**令牌，
# 因此提前 30 分钟刷新即可稳定复用同一个令牌，避免"双令牌"并存）。
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, object] = {"token": "", "expire_at": 0.0}

_REFRESH_MARGIN = 1800      # 提前 30 分钟刷新

# 只登记**已从官方文档确认**的错误码；其余原样透传 msg，不臆造提示（见 `docs/27` §8 风险 7）。
_KNOWN_ERRORS: dict[int, str] = {
    230013: "该用户不在应用机器人的可用范围内，请在飞书开发者后台把用户加入机器人可用范围",
}


class FeishuError(Exception):
    """飞书接口调用失败（网络、鉴权或业务错误码）。

    `kind`：`config`（未配置/未启用）| `network`（不通）| `api`（飞书返回错误码）。
    """

    def __init__(self, message: str, *, code: int | None = None,
                 http_status: int | None = None, kind: str = "api") -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.kind = kind


def _describe(code: int | None, msg: str | None, status: int) -> str:
    if code is not None and code in _KNOWN_ERRORS:
        return _KNOWN_ERRORS[code]
    if code is not None:
        return f"飞书接口错误（code={code}）：{msg or '未知原因'}"
    return f"飞书接口返回 HTTP {status}：{msg or '未知原因'}"


def _request(method: str, url: str, *, headers: dict | None = None,
             json_body: dict | None = None, form_body: dict | None = None,
             timeout: float | None = None) -> dict:
    """发起一次 HTTPS 请求并返回解析后的 JSON（`code != 0` 时抛 `FeishuError`）。"""
    data = None
    hdrs = dict(headers or {})
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
    elif form_body is not None:
        data = urllib.parse.urlencode(form_body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")

    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout or config.FEISHU_TIMEOUT) as resp:
            raw, status = resp.read(), int(resp.status)
    except urllib.error.HTTPError as exc:      # 4xx/5xx：飞书仍会给出 JSON 错误体
        raw, status = exc.read(), int(exc.code)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise FeishuError(f"无法连接飞书（{exc}）；请检查服务器出网、DNS 与代理设置",
                          kind="network") from exc

    text = raw.decode("utf-8", errors="replace") if raw else ""
    try:
        body = json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise FeishuError(f"飞书返回了非 JSON 响应（HTTP {status}）：{text[:200]}",
                          http_status=status) from exc
    if not isinstance(body, dict):
        raise FeishuError(f"飞书返回了非预期结构（HTTP {status}）", http_status=status)

    code = body.get("code")
    # 飞书成功响应统一 code=0；部分端点（如 OAuth v3）不带 code 字段，此时以 HTTP 状态为准
    if status >= 400 or (code is not None and code != 0):
        raise FeishuError(_describe(code if isinstance(code, int) else None,
                                    body.get("msg"), status),
                          code=code if isinstance(code, int) else None, http_status=status)
    return body


def _pick(body: dict, key: str):
    """从响应里取值：先看顶层，再看 `data`（飞书各端点嵌套层级不一致，做一层兼容）。"""
    if key in body:
        return body[key]
    data = body.get("data")
    return data.get(key) if isinstance(data, dict) else None


def _require_ready() -> None:
    if not config.feishu_ready():
        raise FeishuError("飞书接入未启用或配置不完整（需 CTMS_FEISHU_ENABLED=1 且 app_id/"
                          "app_secret/redirect_uri 齐全）", kind="config")


# ---------------- 应用身份令牌 ----------------

def tenant_access_token(*, force: bool = False) -> str:
    """取应用身份令牌（进程内缓存；提前 30 分钟刷新）。"""
    _require_ready()
    now = time.time()
    with _TOKEN_LOCK:
        cached = str(_TOKEN_CACHE.get("token") or "")
        if not force and cached and now < float(_TOKEN_CACHE.get("expire_at") or 0):
            return cached
        body = _request("POST",
                        f"{config.FEISHU_API_BASE}/open-apis/auth/v3/tenant_access_token/internal",
                        json_body={"app_id": config.FEISHU_APP_ID,
                                   "app_secret": config.FEISHU_APP_SECRET})
        token = str(body.get("tenant_access_token") or "")
        if not token:
            raise FeishuError("飞书未返回 tenant_access_token（请核对 App ID / App Secret）")
        try:
            expire = int(body.get("expire") or 7200)
        except (TypeError, ValueError):
            expire = 7200
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["expire_at"] = now + max(expire - _REFRESH_MARGIN, 60)
        return token


def reset_token_cache() -> None:
    """清空令牌缓存（测试与"改了配置后立即生效"用）。"""
    with _TOKEN_LOCK:
        _TOKEN_CACHE["token"] = ""
        _TOKEN_CACHE["expire_at"] = 0.0


# ---------------- 网页免登 ----------------

def build_authorize_url(state: str, *, scope: str | None = None) -> str:
    """构造免登授权地址（浏览器重定向用；飞书服务器不会访问本系统）。"""
    _require_ready()
    params = {
        "client_id": config.FEISHU_APP_ID,
        "response_type": "code",
        "redirect_uri": config.FEISHU_REDIRECT_URI,
        "state": state,
    }
    if scope:
        params["scope"] = scope
    return (f"{config.FEISHU_ACCOUNTS_BASE}/open-apis/authen/v1/authorize?"
            + urllib.parse.urlencode(params))


def oauth_exchange_code(code: str) -> str:
    """授权码换 `user_access_token`（官方现行 v3 端点；授权码 5 分钟有效且只能用一次）。"""
    _require_ready()
    if not code:
        raise FeishuError("缺少授权码 code")
    body = _request("POST", f"{config.FEISHU_ACCOUNTS_BASE}/oauth/v3/token", form_body={
        "grant_type": "authorization_code",
        "client_id": config.FEISHU_APP_ID,
        "client_secret": config.FEISHU_APP_SECRET,
        "code": code,
        "redirect_uri": config.FEISHU_REDIRECT_URI,
    })
    token = _pick(body, "access_token")
    if not token:
        raise FeishuError("飞书未返回 user_access_token（授权码可能已过期或被使用过）")
    return str(token)


def get_user_info(user_access_token: str) -> dict:
    """取飞书用户身份：`open_id` / `union_id` / `name` / `email` / `mobile` 等。

    本系统只依赖 `open_id`（应用内唯一，官方推荐的主键）+ `name` 做展示快照。
    """
    if not user_access_token:
        raise FeishuError("缺少 user_access_token")
    body = _request("GET", f"{config.FEISHU_API_BASE}/open-apis/authen/v1/user_info",
                    headers={"Authorization": f"Bearer {user_access_token}"})
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    if not data.get("open_id"):
        raise FeishuError("飞书未返回 open_id，无法完成身份匹配")
    return data


# ---------------- 发消息 ----------------

def send_message(*, receive_id: str, msg_type: str, content: str,
                 receive_id_type: str = "open_id", uuid: str | None = None) -> dict:
    """给用户/群发一条消息。

    `content` 是**JSON 字符串**（飞书要求）；`uuid` 用于飞书侧 1 小时内去重（与本地
    `event_key` 双重保障幂等）。
    """
    if not receive_id:
        raise FeishuError("缺少收件人 receive_id")
    payload: dict = {"receive_id": receive_id, "msg_type": msg_type, "content": content}
    if uuid:
        payload["uuid"] = uuid
    url = (f"{config.FEISHU_API_BASE}/open-apis/im/v1/messages?"
           + urllib.parse.urlencode({"receive_id_type": receive_id_type}))
    return _request("POST", url, headers={"Authorization": f"Bearer {tenant_access_token()}"},
                    json_body=payload)


def check_connectivity() -> dict:
    """配置自检：能取到应用身份令牌即视为连通（系统管理页"测试连接"用）。"""
    _require_ready()
    token = tenant_access_token(force=True)
    return {"ok": True, "token_prefix": token[:6] + "..." if token else "",
            "api_base": config.FEISHU_API_BASE}
