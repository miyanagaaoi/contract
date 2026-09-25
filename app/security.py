"""安全基础：密码哈希与 JWT 令牌（标准库实现，不引入第三方依赖）。

- 密码：`pbkdf2_hmac('sha256')` + 每账号随机盐，120000 轮；存储格式
  `pbkdf2_sha256$轮数$盐(base64url)$哈希(base64url)`
- 令牌：自研 HS256 JWT（`header.payload.signature`，base64url 无填充）
- 说明：无状态令牌不做服务端吊销，账号停用由每次请求回查 `users.status` 保证即时失效
  （见 `12-erp-system-design.md` §3.1）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from .config import JWT_HOURS, get_jwt_secret

_ITERATIONS = 120_000
_ALGO = "pbkdf2_sha256"


class TokenError(Exception):
    """令牌缺失、被篡改或已过期。"""


# ---------- base64url 编解码（JWT 要求无填充） ----------

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(txt: str) -> bytes:
    if not isinstance(txt, str):
        raise TokenError("令牌格式错误")
    return base64.urlsafe_b64decode(txt + "=" * (-len(txt) % 4))


# ---------- 密码 ----------

def hash_password(raw: str) -> str:
    """生成密码哈希（每次调用使用新的随机盐）。"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", (raw or "").encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${_b64e(salt)}${_b64e(dk)}"


def verify_password(raw: str, stored: str) -> bool:
    """校验密码；任何解析异常都视为不匹配（不抛错，避免账号枚举）。"""
    try:
        algo, iter_s, salt_b64, hash_b64 = (stored or "").split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", (raw or "").encode("utf-8"),
                                _b64d(salt_b64), int(iter_s))
        return hmac.compare_digest(dk, _b64d(hash_b64))
    except Exception:
        return False


def check_password_strength(raw: str, min_len: int = 8) -> str | None:
    """返回不合规原因；合规返回 None（BR-V2-11）。"""
    if not raw or len(raw) < max(6, min_len):
        return f"密码长度至少 {max(6, min_len)} 位"
    if not any(c.isalpha() for c in raw) or not any(c.isdigit() for c in raw):
        return "密码需同时包含字母与数字"
    return None


# ---------- JWT ----------

def create_token(*, user_id: int, username: str, real_name: str,
                 org_id: int | None = None, hours: int | None = None) -> tuple[str, int]:
    """签发登录令牌，返回 `(token, 过期时间戳)`。"""
    now = int(time.time())
    exp = now + (hours or JWT_HOURS) * 3600
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "username": username,
        "name": real_name,
        "org_id": org_id,
        "iat": now,
        "exp": exp,
    }
    seg = (
        _b64e(json.dumps(header, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
        + "."
        + _b64e(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    )
    sig = hmac.new(get_jwt_secret().encode("utf-8"), seg.encode("ascii"), hashlib.sha256).digest()
    return f"{seg}.{_b64e(sig)}", exp


def decode_token(token: str) -> dict:
    """校验签名与有效期并解析载荷；失败抛 `TokenError`。"""
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise TokenError("令牌格式错误")
    h, p, s = parts
    seg = f"{h}.{p}"
    expect = hmac.new(get_jwt_secret().encode("utf-8"), seg.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(expect, _b64d(s)):
        raise TokenError("令牌签名校验失败")
    try:
        payload = json.loads(_b64d(p).decode("utf-8"))
    except Exception:
        raise TokenError("令牌载荷解析失败")
    if int(payload.get("exp") or 0) < int(time.time()):
        raise TokenError("登录已过期，请重新登录")
    return payload
