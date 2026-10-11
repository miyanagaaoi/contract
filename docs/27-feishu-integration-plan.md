# 27. 飞书接入方案（免登 + 消息推送）

> 触发：业务方提出"把本系统接入飞书"。
> 已确认范围：**① 飞书免登**（用飞书账号登录本系统）+ **② 消息推送 / 到期提醒**（待办、质保到期、库存预警推到飞书）。
> 已确认网络条件：**服务器可出公网，但本系统没有公网可达的域名/IP**。
> 文档状态：**已实施（M1 免登 + M2 推送 + M3 每日提醒），分支 `exp/feishu-integration`**。
> 代码落点与 §4 基本一致，实现时的差异与验证证据见 §10；尚未并入 `main`，待评审后合并。

---

## 1. 结论先行（三条反直觉的事实）

1. **本方案不需要公网入口、不需要内网穿透、也不需要长连接。**
   免登走的是**用户浏览器重定向**（飞书服务器不访问本系统），推送走的是**本系统主动出网调用飞书 API**。二者都只要求服务器能**出网访问** `open.feishu.cn` / `accounts.feishu.cn`（443）。
   长连接（WebSocket）只在"要在飞书卡片上点按钮直接审批、接收飞书事件"时才需要——**不在本次范围**（见 §7）。
2. **飞书只做"你是谁"，不做"你能干什么"。** 免登成功后由本系统按既有逻辑签发自己的 JWT（复用 `app/security.py::create_token`），角色、权限点、数据范围、审计**零改动**。飞书身份**不得**成为权限真源（AC-V2-41 的口径不变）。
3. **推送必须先做免登，顺序不能反。** 给某人发飞书消息需要他的 `open_id`，而 `open_id` 只在免登（或通讯录接口）时才能拿到。因此里程碑 M1 免登顺带完成"落库绑定"，M2 推送才有收件人。

## 2. 现状与改造面（基于当前代码）

| 现状 | 位置 | 对飞书接入的含义 |
|---|---|---|
| 自研 HS256 JWT，无 refresh、无服务端吊销 | `app/security.py:73`、`docs/12` §3.1 | 免登只需在"签发令牌"前多一条身份来源分支，**不引入会话表** |
| 登录唯一入口 `POST /api/auth/login`（账号+密码） | `app/routers/auth.py:50` | 新增 `POST /api/auth/feishu/login`，与它并列 |
| 登录态解析唯一入口 `get_current_user` | `app/services/permission_service.py:47` | **不改动**——飞书登录产出的就是同一个 JWT |
| 账号表 `users`（username/password_hash/real_name/phone/email） | `app/models_auth.py:72` | **无外部身份字段** → 需新增身份绑定表（§4.1） |
| 单据审核状态机 submit/approve/unapprove | `app/routers/doc_routes.py:212/223/272` | 推送触发点，替换为"写 outbox"（§4.3） |
| 站内待办与到期数据已算好 | `app/routers/dashboard.py:87/136/163/189` | 推送内容**复用**这些查询，抽到服务层，不重写口径 |
| 无消息、无队列、无定时任务框架 | `docs/02` §221、`docs/12` | 用"outbox 表 + lifespan 内守护线程 + 计划任务 CLI"，**不引入 Celery/Redis** |
| 增量迁移靠幂等加列 | `app/db_migrate.py:15/88` | 新增字段按此清单加；新增**表**由 `create_all` 负责 |
| 新权限点需补到内置角色 | `app/init_db.py:194`（sysadmin 自动补齐） | 新增权限点后 sysadmin 自动获得，其他内置角色需 `sync_builtin_roles` |
| 依赖极简：后端仅 6 个包 | `app/requirements.txt` | 需新增 `httpx`（`requirements-dev.txt` 已有，属既有生态） |

## 3. 目标架构

```
用户在飞书工作台/浏览器点击「飞书登录」
        │  ① 302 → accounts.feishu.cn/open-apis/authen/v1/authorize
        ▼        (client_id, response_type=code, redirect_uri, state)
   CTMS 前端 /feishu/callback?code=&state=          ← redirect_uri 由飞书回跳【用户浏览器】
        │  ② POST /api/auth/feishu/login {code, state}
        ▼
   CTMS 后端 ──③ 出网换 user_access_token（accounts.feishu.cn/oauth/v3/token）
        │       ④ GET /open-apis/authen/v1/user_info → open_id / union_id / name
        │       ⑤ 查 user_identities：open_id → users.id（未绑定 → 401 明确提示）
        │       ⑥ 复用 create_token() 签发【本系统 JWT】（飞书令牌用完即弃，不落库）
        ▼
   前端存 token（复用 utils/token.ts）→ replace('/')

业务侧（提交/审核单据）→ 同事务写 notifications(pending) → 守护线程出网发送 → sent/failed
每日计划任务 → python -m app.tools.feishu_digest → 汇总待办/质保/库存 → 写 outbox
```

## 4. 改造清单

### 4.1 数据模型（2 张新表）

**表 1：`user_identities`**（外部身份绑定，一对多，为将来钉钉/企微留口）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | Integer | PK | |
| `user_id` | Integer | FK→`users.id`，**NOT NULL**，index | 本系统账号 |
| `provider` | String(16) | NOT NULL，默认 `feishu` | 身份源 |
| `open_id` | String(64) | NOT NULL，index | **应用内**唯一标识，官方建议的主键 |
| `union_id` | String(64) | nullable | 开发商维度标识（换应用后可复用） |
| `tenant_key` | String(64) | nullable | 租户标识，防串号 |
| `display_name` | String(64) | nullable | 飞书姓名快照 |
| `bound_at` / `bound_by` / `last_login_at` | DateTime / Integer | | 审计 |

- **唯一约束**：`(provider, open_id)` 唯一（防一个飞书身份绑两个账号）。
- 新增表由 `Base.metadata.create_all`（`app/main.py:56`）创建，SQLite / PostgreSQL 均适用；**不需要**写进 `db_migrate._ADD_COLUMNS`（那里只管已存在表补列）。
- 不选"给 `users` 加 `feishu_open_id` 列"的理由：只能绑一个身份源，且外键只能在应用层保证（`db_migrate` 的 SQLite 限制，见 `docs/12` §4.5）。

**表 2：`notifications`**（发送 outbox，业务事务与网络调用解耦）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | |
| `event_key` | String(128) **UNIQUE** | 幂等键，如 `doc:purchase_order:12:submit:user3` |
| `channel` | String(16) | 默认 `feishu` |
| `recipient_user_id` | Integer index | 收件人（本系统账号） |
| `recipient_open_id` | String(64) | **快照**（重试时不再查库，避免绑定变更导致漂移） |
| `msg_type` | String(16) | `interactive`（卡片）/ `text` |
| `payload` | Text | 卡片 JSON 字符串 |
| `status` | String(16) index | `pending` / `sent` / `failed` / `skipped` |
| `attempts` | Integer | 重试次数 |
| `last_error` | String(512) | 失败原因（截断，不含密钥） |
| `next_retry_at` | DateTime index | 指数退避：1/5/30 分钟，最多 5 次 |
| `created_at` / `sent_at` | DateTime | |

### 4.2 后端新增文件

```
app/services/feishu/
  __init__.py
  client.py            # 出网封装：tenant_access_token 缓存、oauth code 换 token、
                       # user_info、im/v1/messages 发送；统一超时/重试/限速；密钥只从 env 读
  identity_service.py  # 绑定/解绑/按 open_id 解析账号/自助绑定（含 state 签名校验）
  notify_service.py    # enqueue_*（同事务写 outbox）+ 卡片构造 + outbox 发送与退避
  errors.py            # 飞书错误码 → 本系统 4xx/5xx 的中文提示映射
app/routers/feishu.py  # 免登入口/回调、绑定管理、连通性自检、测试消息
app/tools/feishu_digest.py  # 每日提醒 CLI（计划任务调用），复用 dashboard 口径
```

`app/routers/feishu.py` 接口清单：

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/auth/feishu/config` | 公开 | 返回 `{enabled, authorize_url, redirect_uri}`；关闭时前端不显示入口 |
| POST | `/api/auth/feishu/login` | 公开 | body `{code, state}` → 校验 state → 换令牌 → 取 `open_id` → 查绑定 → 签发本系统 JWT。失败：`401` 未绑定 / `400` state 失效 |
| GET | `/api/auth/feishu/bind-info` | 登录态 | 当前账号绑定状态 |
| POST | `/api/auth/feishu/bind` | 登录态 | **自助绑定**：body `{code, state}`，把当前登录账号与飞书身份绑定 |
| DELETE | `/api/auth/feishu/bind` | 登录态 | 自助解绑 |
| GET | `/api/system/feishu/config` | `system.feishu.view` | 配置自检：app_id 是否配置、出网是否通、已绑定人数 |
| POST | `/api/system/feishu/test-message` | `system.feishu.edit` | 给当前用户发一条测试卡片（验证权限/可用范围/限频） |
| POST | `/api/system/users/{id}/feishu/bind` | `system.feishu.edit` | 管理员为某人解绑（换人/离职场景） |

**新增权限点**（`app/permissions.py`，追加到 system 段）：

```python
("system.feishu.view", "飞书接入查看", "system", "menu"),
("system.feishu.edit", "飞书配置与绑定维护", "system", "button"),
```
- `sysadmin` 由 `_backfill_sysadmin_perms` 自动补齐；其他内置角色需显式跑 `python -m app.init_db --sync-roles`（沿用既有机制，不新增逻辑）。

### 4.3 触发点改造（推送）

| 动作 | 位置 | 改造 |
|---|---|---|
| 单据提交 | `app/routers/doc_routes.py:212` `_submit` | 提交成功后，按 `_APPROVE_PERM` 找出**有审核权限的启用账号**，逐个 `enqueue`（同事务） |
| 单据审核/驳回 | 同文件 `:223` `_approve` | 通知**提交人**（`submitted_by`/`created_by`）结果 |
| 反审核 | 同文件 `:272` `_unapprove` | 通知提交人 |
| 质保到期 / 库存预警 / 待办汇总 | 新增 `app/tools/feishu_digest.py` | 每日一次，**复用** `dashboard.py` 的 `_todos`/`_stock_alerts`/质保窗口口径（抽为服务层函数） |

**硬约束（必须遵守）**：
- 飞书网络调用**绝不能**出现在业务请求的事务内。业务侧只写 outbox（`db.add` + `commit`），发送由后台线程做——否则飞书限流/超时会直接拖慢或拖垮单据录入，且违反"审计与业务同事务"（`docs/12` §5.4）。
- 发送失败**不得**让单据提交失败；只在 `notifications.last_error` 留痕，并在系统管理页可见。
- 幂等：`event_key` 唯一约束兜底"至少一次"语义（飞书事件与重试都会重复）。

**发送 worker**：`app/main.py` 的 `lifespan` 启动一个 `daemon` 线程，轮询 `notifications(status='pending' AND next_retry_at<=now)`，串行发送、单条间隔 ≥250ms（守住"同一用户 5 QPS"）、指数退避。进程重启后 outbox 仍在库中，**不丢消息**。**不引入 Celery/Redis**（与"依赖极简"风格一致）。

> ⚠️ 并发发送的防护：若将来改用 `uvicorn --workers N`（或容器多副本），每个进程都会启动 worker。
> 因此发送前必须**原子抢占**：`UPDATE notifications SET status='sending', attempts=attempts+1
> WHERE id=:id AND status='pending'`，仅当影响行数为 1 时才真正调用飞书接口；
> 配合 `event_key` 唯一约束，保证"至多一次实际发送"。当前部署是单进程（见 `docs/08`、`docs/10`），
> 但该防护必须一开始就写，否则多副本上线即重复推送。

### 4.4 前端改造

| 文件 | 改造 |
|---|---|
| `web/src/views/FeishuCallbackView.vue` | **新增**，路由 `/feishu/callback`（`meta.public = true`），取 `code`/`state` → `POST /auth/feishu/login` → 复用 `stores/auth.setToken` → `fetchMe(true)` → `replace(redirect)` |
| `web/src/views/LoginView.vue:18` 附近 | 在"登 录"按钮下加「飞书登录」；`GET /auth/feishu/config` 为 `enabled=false` 时**整块不渲染**（关闭开关的回归要求） |
| `web/src/stores/auth.ts:69` 附近 | 新增 `feishuLogin(code, state)` 与 `bindFeishu(code, state)` |
| `web/src/router/index.ts:17` 附近 | 注册 `/feishu/callback` |
| `web/src/views/master/UserView.vue` | 用户列表加「飞书」列（已绑定/未绑定/飞书姓名）+「解绑」操作（`system.feishu.edit`） |
| `web/src/views/system/SystemView.vue` | 新增「飞书接入」卡片：配置自检、绑定人数、测试消息、outbox 失败列表（`system.feishu.view`） |
| `web/src/utils/token.ts:16` | **不改**（`ctms_token` 仍是唯一令牌真源） |

`/feishu/callback` 必须放在 SPA 路由内（不要新建后端 302 跳转），这样前端统一处理令牌落库与失败提示；`redirect_uri` 也就是 `<CTMS_BASE_URL>/feishu/callback`。

### 4.5 配置与部署

`.env.example` 追加（`app/config.py` 按同一风格读取）：

```bash
# ---- 飞书接入（可选；不配置则登录页不显示飞书入口，功能整体降级）----
CTMS_FEISHU_ENABLED=1
CTMS_FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
CTMS_FEISHU_APP_SECRET=CHANGE_ME          # 仅环境变量，禁止入库/入 git
CTMS_FEISHU_REDIRECT_URI=http://192.168.31.27:8080/feishu/callback
CTMS_FEISHU_BASE_URL=http://192.168.31.27:8080   # 卡片跳转链接的根地址
```

- `app_secret` **只从环境变量读**，与 `CTMS_JWT_SECRET` 同策略；不入 KV 库、不进日志、错误信息中脱敏。
  取值来自飞书后台 **基础信息 → 凭证与基础信息 → App Secret**，必须与 `CTMS_FEISHU_APP_ID` 属于**同一个应用**。
- ✅ **`.env` 会被自动加载**（V2.4 起，零依赖实现见 `config.py::load_env_file`）：
  把 `.env.example` 复制为项目根目录 `.env` 填值即可，无需任何第三方库。
  优先级为 **真实环境变量 > `.env` > 代码默认值**（用 `os.environ.setdefault`，
  `.env` **不会**覆盖已注入的环境变量 —— 这是为了防止"本地文件改写生产配置"这类
  最难排查的事故；`CTMS_ENV_FILE` 可指定其它路径）。
  也完全可以不用 `.env`：`set` / `$env:` / NSSM `AppEnvironmentExtra` /
  compose `environment:` / systemd `Environment=` 都等价。环境变量在**进程启动时**读取
  （模块级常量），改完必须**重启后端**。
- 四项必须齐全才会启用：`CTMS_FEISHU_ENABLED` + `APP_ID` + `APP_SECRET` + `REDIRECT_URI`；
  缺任何一项，飞书功能整体降级（**包括消息推送**，因为 `feishu_ready()` 是单一开关）。
- 出网白名单（443）：`open.feishu.cn`、`accounts.feishu.cn`；如有出口代理，需为 `httpx` 配置代理（具体参数落地时确认）。
- 每日提醒（复用既有计划任务机制，见 `docs/08` §57 / `docs/09` §9 / `deploy` 容器 cron）：
  `python -m app.tools.feishu_digest --kind warranty,stock,todo`

### 4.6 飞书侧配置清单（管理员/运维在开发者后台完成）

> 官方依据：[创建并配置应用](https://open.feishu.cn/document/mass-messaging-to-designated-departments/create-app-request-permission)、
> [应用配置说明](https://open.feishu.cn/document/develop-an-echo-bot/faq)、
> [配置应用可用范围](https://open.feishu.cn/document/develop-process/test-and-release-app/availability)、
> [获取用户信息](https://open.feishu.cn/document/ukTMukTMukTM/uIDO4UjLygDO14iM4gTN)。

| # | 配置项 | 后台位置 | 影响本系统哪个功能 | 缺失时的现象 |
|---|---|---|---|---|
| 1 | 创建**企业自建应用** | [open.feishu.cn/app](https://open.feishu.cn/app) → 创建企业自建应用 | 全部 | — |
| 2 | 抄下 **App ID / App Secret** | 基础信息 → 凭证与基础信息 | 全部 | 连通性检查失败 |
| 3 | 添加**机器人**能力 | 应用能力 → 添加应用能力 → 机器人 → 添加 | 消息推送（免登不受影响） | 发消息报错 |
| 4 | 开通权限 `im:message:send_as_bot` | 开发配置 → 权限管理 → API 权限 | 待办 / 审核结果 / 每日提醒 | 发消息 401/权限错误 |
| 5 | 登记**重定向 URL** | 开发配置 → 安全设置 → 重定向 URL | 飞书免登 | 授权页报错，免登走不通 |
| 6 | 配置**可用范围** | 应用发布 → 版本管理与发布 → 创建版本 → 版本详情 → 可用范围（或管理员在管理后台 → 工作台 → 应用管理 → 应用可用范围） | 推送投递 | 发消息报 **230013** |
| 7 | 发布应用 | 应用发布 → 版本管理与发布 → 创建版本 | 使 1~6 生效 | 配置不生效 |

**明确不需要的**（少开权限，减小攻击面）：

- ❌ **事件订阅 / 回调地址 / 长连接** —— 本方案只**主动出网发消息**，不接收事件；
- ❌ **通讯录类权限** —— `authen/v1/user_info` 的基础字段（`open_id`/`union_id`/`name`/`tenant_key`）
  官方标注**无权限要求**；只有 `user_id`/`mobile`/`email` 等敏感字段才需要额外权限，
  而本系统**一个都不用**（§5.2 已明确不按手机号/邮箱自动匹配账号）；
- ❌ **群自定义机器人 webhook** —— 那是另一条路（无应用身份、不支持卡片回调、无数据访问权限），
  与本方案使用的**应用机器人** `im/v1/messages` 不是一回事，不要混用；
- ❌ 机器人**不需要**被拉进任何群：推送是给个人（`receive_id_type=open_id`）发单聊消息。

**加速验证的官方机制**：`测试企业和人员 → 创建测试企业 → 关联应用`后切换到**测试版应用**，
该版本"权限和配置变更都会直接生效，**无需管理员审核**"；正式版每次改动都必须重新发版审核。
本方案的重定向 URL 内网地址实测（§8 风险 1）建议就在测试版上做。

**本系统侧的验证入口**：系统管理 → **飞书接入** → 「连通性检查」（等价于取一次应用令牌）、
「发送测试消息」（给当前账号发一张卡片，失败会直接显示原因）。

**排错对照**：`230013` → 第 6 项可用范围未覆盖该用户；授权页报 `20029` → 第 5 项重定向 URL
与请求不一致（见[官方排错文档](https://open.larkoffice.com/document/faq/trouble-shooting/how-to-resolve-the-authorization-page-20029-error)）；
连通性检查失败 → 第 2 项密钥或服务器出网/代理问题。

## 5. 关键设计决策

### 5.1 账号匹配：默认"先绑定后免登"（安全优先）

免登拿到 `open_id` 后如何对上本系统账号？三选一：

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（推荐）** | 管理员在用户管理页预先绑定，或用户先密码登录后自助绑定；未绑定 → `401「飞书账号尚未绑定系统账号，请联系管理员」` | 无越权风险，审计清晰；代价是首个用户要有初始绑定动作 |
| B | 按 `user_info.mobile`/`email` 自动匹配 `users.phone`/`email` | 便捷，但手机号/邮箱**未经实时核验**（官方明确），改号/复用即越权；仅可作为**预匹配建议**交给管理员确认 |
| C | 首次免登自动建号 | **禁止**：绕过角色与数据范围，等于把内网系统的权限边界交给飞书通讯录 |

落地取 **A**，B 仅作为「待认领绑定」列表的辅助建议（对齐既有 `PartyDraftView` 历史档案认领的交互习惯）。

### 5.2 令牌处理

- 飞书 `user_access_token` **只用于调一次 `user_info` 取 `open_id`，用完即弃、不落库**（本系统不需要长期持有它，也就没有刷新令牌的负担）。
- 本系统 JWT 照旧：`create_token()`，有效期 `CTMS_JWT_HOURS`（默认 8）。
- `tenant_access_token` 供发消息使用，**进程内缓存**，按响应 `expire` 提前 30 分钟刷新（官方说明：剩余 <30 分钟会返回新令牌）。

### 5.3 `state` 防 CSRF

无状态实现，贴合本项目风格：`state = base64url(ts|nonce) + "." + HMAC-SHA256(secret, ts|nonce)`，回调时校验签名 + 10 分钟有效期。**不引入服务端会话表**。

### 5.4 免登账号的密码与首登改密

- `users.password_hash` 为 NOT NULL，免登账号仍需一个密码哈希（管理员创建时随机生成即可），否则表约束与审计口径都要动。
- **口径待确认**：`must_change_pwd=True` 的用户经飞书免登时，是否仍强制跳改密页？建议**免登路径跳过强制改密**（否则免登体验自相矛盾），仅在密码登录路径保留强制。该条需业务方签字确认后写入规格。

## 6. 里程碑与验收

| 里程碑 | 内容 | 预估 | 验收要点 |
|---|---|---|---|
| **M1 免登** | 身份表 + feishu client + 免登接口 + 前端回调页/登录入口 + 绑定管理 | 1.5~2 人日 | AC-FS-01~04、AC-FS-09 |
| **M2 推送** | outbox 表 + worker + 卡片 + submit/approve 触发点 + 测试消息 | 2~3 人日 | AC-FS-05~07、AC-FS-10 |
| **M3 定时提醒** | `feishu_digest` + 计划任务 + 去重 | 1 人日 | AC-FS-07、AC-FS-11 |
| **M4（可选，不在本次）** | 卡片按钮直接审批（需长连接或事件订阅）、飞书审批流对接、云文档附件 | 3~5 人日+ | 见 §7 |

**验收场景草案**（按 `00-sdd-process.md` 补成正式 AC 并逐条留证）：

| 编号 | 场景 | 期望 |
|---|---|---|
| AC-FS-01 | 飞书账号未绑定，点飞书登录 | 落回登录页并提示"尚未绑定，请联系管理员"；**不签发任何令牌** |
| AC-FS-02 | 已绑定账号免登 | 进入系统，`/api/auth/me` 返回的角色/权限/菜单与密码登录**完全一致** |
| AC-FS-03 | `state` 被篡改或超 10 分钟 | `400`，不换令牌（CSRF 防护） |
| AC-FS-04 | 解绑后再免登 | `401`；该用户密码登录仍可用 |
| AC-FS-05 | 提交采购单（审核人有绑定） | 审核人在飞书收到卡片：单号/金额/发起人/直达链接 |
| AC-FS-06 | 飞书接口不可用（断网/限流）时提交单据 | **单据提交照常成功**，`notifications` 留 `failed` 与原因，系统管理页可见 |
| AC-FS-07 | 同一事件重复投递 | 仅一条通知（`event_key` 唯一约束） |
| AC-FS-08 | 每日提醒重复运行 | 同日同收件人同类别只发一次 |
| AC-FS-09 | `CTMS_FEISHU_ENABLED=0` | 登录页无飞书入口、无飞书接口副作用；密码登录与全量既有测试不受影响 |
| AC-FS-10 | 无 `im:message:send_as_bot` 权限 / 用户不在机器人可用范围 | 自检与测试消息给出**可读的**中文提示与错误码，不 500 |
| AC-FS-11 | 后端重启（outbox 有 pending） | 未发送通知在重启后继续发送，不丢 |

**回归基线**：`pytest`（329 项）、前端 Playwright E2E（81 项）、冒烟 M1/M2/M3 必须全绿——飞书功能默认关闭时对既有行为**零影响**。

## 7. 明确不做（本次范围外）

| 项 | 原因 |
|---|---|
| 飞书卡片按钮直接审批（点"同意"就过账） | 需接收 `card.action.trigger` 事件 → 需公网回调或长连接；且会把"谁审的"从本系统审计挪到飞书，需业务方先定口径 |
| 飞书审批流（`approval/v4`）承载单据审批 | 本系统是"提交→审核→过账"的简单状态机（`docs/11` §14.5 明确不做多级审批/审批流引擎）；双向同步成本与风险最高 |
| 附件上传到飞书云文档 | 与既有本地附件方案（`app/uploads`）重叠，无明确收益 |
| 用长连接接收事件 | 本范围只需**主动出网发送**，不需要接收事件；引入 `lark-oapi` 会为 3 秒处理时限/集群随机投递/≤50 连接等约束付出复杂度 |

## 8. 风险与待确认项

| # | 风险/待确认 | 影响 | 应对 |
|---|---|---|---|
| 1 | **飞书后台是否接受 `http://<内网IP>/feishu/callback` 作为重定向 URL** | 免登能否落地 | **落地第一步就实测**。若被拒：内网搭 DNS 名 + HTTPS（自签或内部 CA），或改用从飞书工作台进入的客户端内免登方式；此点官方文档未给出内网场景明确口径，**必须实测后再排期** |
| 2 | 存量账号无 `phone`/`email`（`users` 可空） | 绑定只能人工 | M1 提供"批量绑定"与自助绑定两条路；不做手机号自动匹配（§5.1） |
| 3 | 消息限频：同一用户 5 QPS、卡片 ≤30 KB | 突发事件刷屏/失败 | worker 串行 + 间隔 ≥250ms；摘要类内容合框或超长截断 |
| 4 | `app_secret` 泄漏 | 可冒充应用发消息 | 仅 env 注入；日志与错误信息脱敏；系统管理页只显示"已配置/未配置" |
| 5 | 规格冲突：`docs/11` §14.5（消息推送范围外）、§14.8（对接外部系统范围外）、`docs/01` §6（邮件/短信/企微推送范围外） | SDD 纪律：先改规格再写码 | 落地前先出 `27-feishu-requirements.md` 并在 `11`/`01` 的范围外清单加"经评审变更"批注 |
| 6 | 若未来做卡片交互需 `lark-oapi` | 依赖风险 | 必须 pin `>=1.6.4`（`1.6.0`~`1.6.3` 与 `2.0.0.dev*` 因 **Webhook 签名兼容性回归已被 yank**） |
| 7 | 飞书 OAuth 已是 **v3**（`accounts.feishu.cn/oauth/v3/token`），旧 `authen/v2/oauth/token` 为历史版本 | 接口选错会返工 | 按 v3 实现；落地时以开发者后台当时文档为准 |

## 9. 参考（飞书官方文档）

- [自建应用开发流程](https://open.feishu.cn/document/home/introduction-to-custom-app-development/self-built-application-development-process) · [应用类型与能力](https://open.feishu.cn/document/home/app-types-introduction/overview)
- 免登：[获取授权码](https://open.feishu.cn/document/common-capabilities/sso/api/obtain-oauth-code) · [获取 user_access_token（v3）](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/authentication-management/access-token/get-user-access-token-v3) · [获取用户信息](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/authen-v1/user_info/get)
- 应用身份：[tenant_access_token](https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal)
- 消息：[发送消息 im/v1/messages](https://open.feishu.cn/document/server-docs/im-v1/message/create) · [消息卡片交互](https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/configuring-card-interactions)
- 事件订阅（M4 备查）：[事件概述](https://open.feishu.cn/document/ukTMukTMukTM/uUTNz4SN1MjL1UzM) · [长连接接收事件](https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-configure-/request-url-configuration-case)
- 审批（范围外，备查）：[创建审批实例](https://open.feishu.cn/document/server-docs/approval-v4/instance/create)

---

## 10. 实施记录（M1 免登 + M2 推送 + M3 每日提醒）

分支：`exp/feishu-integration`（基线为 V2.3 成果提交之后的 `main`）。

### 10.1 实际文件落点

| 类型 | 文件 |
|---|---|
| 配置 | `app/config.py`（`FEISHU_*` + `feishu_ready()`，默认**关闭**） |
| 模型 | `app/models_auth.py::UserIdentity`、`app/models_notify.py::Notification` |
| 权限 | `app/permissions.py`：新增 `system.feishu.view/edit`；`DOC_VIEW_PERM` / `DOC_APPROVE_PERM` 上移为单一真源（看板与飞书推送共用） |
| 服务 | `app/services/feishu/{__init__,client,identity_service,card,notify_service}.py` |
| 路由 | `app/routers/feishu.py`（`/api/auth/feishu/*` 免登与绑定、`/api/system/feishu/*` 运维） |
| 触发点 | `app/routers/doc_routes.py`：submit / approve / reject / complete / void / unapprove 各自**同事务入队** |
| 线程与任务 | `app/main.py` lifespan 启停发送线程；`app/tools/feishu_digest.py` 每日摘要 CLI |
| 前端 | 新增 `web/src/views/FeishuCallbackView.vue`；改 `LoginView.vue`、`stores/auth.ts`、`router/index.ts`、`api.ts`、`views/master/UserView.vue`、`views/system/SystemView.vue` |
| 测试 | `app/tests/test_v2_4_feishu.py`（41 项，飞书 API 全部 mock，不外网） |

### 10.2 与本文方案的差异（均为简化或加固，不改变业务口径）

1. **没有引入任何新依赖**：出网用标准库 `urllib.request`，未加 `httpx` / `lark-oapi`；
   原方案里的 `errors.py` 合并进 `client.py`（错误类 + 已确认错误码的中文映射）。
2. `UserIdentity` 落在 `models_auth.py`（认证域）而不是新建 models 文件；
   `Notification` 独立为 `models_notify.py`。
3. **发现并修复一个真实缺陷**：发送前的原子抢占若用
   `query.update(synchronize_session=False)`，session 中那份**陈旧对象**会在后续 flush 时
   把 `status` / `attempts` 的旧值写回，**覆盖抢占结果**（表现为 attempts 不增长、
   或消息已发出却被改回 pending）。修复为抢占后立即 `db.expire_all()`，
   并由 `test_send_failure_backs_off_then_fails` 固定住该行为。
4. 重试语义：`next_retry_at` 为空表示"可立即发送"；退避 1 / 5 / 30 分钟，
   达到 `CTMS_FEISHU_MAX_ATTEMPTS`（默认 5）次后转 `failed`，管理页可一键重试。

### 10.3 验证证据

```
app/.venv/Scripts/python.exe -m pytest app/tests -q   → 370 passed（既有 329 + 新增 41）
cd web && npm run build                               → ✓ built（无导入/语法错误）
```

新增用例覆盖 AC-FS-01~09：默认关闭时整体降级、`state` 篡改/超时/重放、绑定冲突与换绑、
未绑定拒绝且审计留痕、免登签发**本系统** JWT、outbox 幂等、入队冲突不污染业务事务、
发送成功/失败退避/原子抢占、每日摘要同日去重与"无内容不打扰"、卡片链接映射完整性。

### 10.4 合并前仍需完成

1. **实测飞书后台是否接受 `http://<内网IP>/feishu/callback` 作为重定向 URL**（§8 风险 1）——
   这决定免登能否成立，必须在真实企业自建应用上验证，不能靠代码推断；
2. 真实租户端到端联调：发卡片、点按钮跳回内网系统、免登闭环；
3. 规格回写：`docs/11` §14.5（消息推送）/§14.8（对接外部系统）与 `docs/01` §6
   的"范围外"清单需加评审变更批注；
4. Playwright E2E 未覆盖飞书入口（依赖真实飞书授权页，属外部依赖），
   当前以接口/服务层测试 + 手工联调替代。
