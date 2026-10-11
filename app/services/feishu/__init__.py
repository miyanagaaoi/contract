"""飞书接入服务（V2.4，见 `docs/27-feishu-integration-plan.md` §4.2）。

模块划分：

| 模块 | 职责 |
|---|---|
| `client` | 出网封装：`tenant_access_token` 缓存、OAuth 授权码换令牌、`user_info`、发消息；错误码归一 |
| `identity_service` | 身份绑定与免登：`state` 防重放签名、`open_id` → 本系统账号、自助/管理员绑定 |
| `card` | 消息卡片 JSON 构造（待办/结果/每日摘要/测试消息） |
| `notify_service` | outbox 入队、后台发送线程、退避重试、每日摘要 |

设计约束（三条不可动摇）：

1. **飞书只做身份认证，不做授权。** 免登成功后签发的仍是本系统 JWT，角色/权限点/数据范围
   完全沿用既有逻辑（`security.create_token` + `permission_service`）。
2. **业务请求内绝不发网络调用。** 业务侧只写 `notifications(pending)`，发送由后台线程完成。
3. **整体可降级。** `config.feishu_ready()` 为假时，登录入口不显示、发送线程不启动、
   接口返回明确提示；既有密码登录与全部既有测试不受影响（AC-FS-09）。
"""
