# 12. ERP 进销存系统设计（V2.0 详细设计）

项目名称：合同管理与跟踪系统 → **ERP 进销存（内网版，代号 CTMS）**
文档状态：**V2.0 草案（待评审）**
对应规格：`11-erp-requirements.md`（PRD V2.0，D1~D12 / BR-V2-01~20 / AC-V2-01~42）
交付物定位：**把 PRD 翻译成可施工的技术方案**——表结构、服务、接口、前端结构、并发与迁移。

> 编号说明：PRD §19 原写"输出 `02-system-design.md` V2.0"。为保留 V1.0 设计留档（与 `01`→`11` 的处理方式一致），V2.0 设计独立成 `12`，并在 `02` 顶部加指向说明。

---

## 1. 架构演进总览

### 1.1 V1.0 → V2.0 变化

| 维度 | V1.0 | V2.0 |
|---|---|---|
| 认证 | 无 | **JWT 登录态**（HS256，自研，标准库实现，不引入新依赖） |
| 权限 | 无 | 菜单权限 + 按钮权限 + 数据范围（三重校验，后端强制） |
| 业务域 | 合同 | 合同 + 采购 + 销售 + 库存 + 资料库 |
| 库存账 | 无 | `stocks` 结存 + `stock_ledger` 流水，只由过账服务写入 |
| 后端结构 | `app/*.py` 单层 + `routers/` | 新增 `services/`（业务服务层）、`models_*.py`（按域拆模型） |
| 前端结构 | 3 路由 + 单文件页面 | 侧边多级菜单 + ~25 路由 + 通用单据组件 + Pinia 权限态 |
| 审计 | 变更历史（无操作人） | 变更历史补操作人 + 新增操作日志 |
| 迁移 | `db_migrate.py` 幂等加列 | 沿用（**不引入 Alembic**，D8） |

### 1.2 架构分层

```
浏览器（Vue3 + Element Plus）
   │  JWT in Authorization: Bearer <token>
   ▼
FastAPI 路由层 routers/          ← 登录态校验 → 按钮权限校验 → 参数校验
   ▼
业务服务层 services/             ← 数据范围过滤、编号、过账、下推、审计
   ▼
数据访问层 models_*.py（SQLAlchemy 2.x）
   ▼
SQLite（WAL 模式）
```

**关键约束**：所有数据范围过滤与权限判定都在**服务端**执行，前端隐藏按钮仅改善体验，不构成安全边界（AC-V2-41）。

---

## 2. 后端目录结构（渐进式改造）

为降低一次性重构风险，**V1.0 的 `app/models.py` 保持不动**（合同域继续用），新增文件按域承载新模型；`main.py` 统一导入以让 `create_all` 感知全部表。

```
app/
  main.py                 # 引入新路由；lifespan 里执行 ensure_schema_upgrades + 权限/字典种子
  config.py               # 新增：JWT_SECRET / JWT_HOURS / AUTH_ENABLED
  database.py             # 新增：SQLite WAL + busy_timeout 事件
  db_migrate.py           # 扩展 _ADD_COLUMNS 清单
  init_db.py              # 新增：seed_admin()、seed_roles()、seed_sys_params()
  dicts.py                # 保留；新增 sys_params / number_rules 存取
  numbering.py            # 保留（合同编号）；新编号统一走 services/numbering_service.py
  security.py             # 新增：密码哈希 + JWT 签发/校验
  permissions.py          # 新增：权限点清单 + 菜单树（唯一真源）
  models.py               # 保留（合同/标签/附件/变更历史/行项/KVSetting）
  models_master.py        # 新增：客户/供应商/商品类型/物料/单位/仓库
  models_auth.py          # 新增：组织/账号/角色/关联/操作日志
  models_doc.py           # 新增：单据公共 Mixin + 8 张单据主表 + 8 张行项表
  models_stock.py         # 新增：stocks / stock_ledger
  services/
    __init__.py
    auth_service.py       # 登录、改密、重置、令牌解析
    permission_service.py # 权限聚合、菜单树、数据范围过滤
    org_service.py        # 组织树（物化路径维护、下级查询）
    numbering_service.py  # 统一编号引擎（单据 + 主数据）
    posting_service.py    # **库存过账（核心）**
    push_service.py       # 单据下推（申请→单→出入库）
    audit_service.py      # 变更历史 + 操作日志
    backup_service.py     # 手动备份打包
  routers/
    auth.py  system.py  master.py  purchase.py  sales.py  stock.py
    contracts.py（改造）  attachments.py（扩展）  export.py（扩展）  imports.py（保留）
```

> 说明：`models_doc.py` 用 SQLAlchemy `Mixin` 承载公共字段，8 张单据主表与 8 张行项表继承 Mixin，避免重复代码（对应 §4.4）。

---

## 3. 认证与权限设计（核心）

### 3.1 认证流程

```
POST /api/auth/login  {username, password}
  → 查 users（状态启用）→ 校验 pbkdf2 哈希 → 签发 JWT（8 小时）
  → 若 must_change_pwd=true，响应 {must_change_pwd: true}，前端强制跳改密页
  → 写 operation_logs（登录成功/失败）

GET /api/auth/me  → {user, org, roles, perms[], menus[]}
POST /api/auth/change-password  {old_password, new_password}
POST /api/auth/logout  → 写操作日志（无状态令牌，服务端仅记日志）
```

JWT 载荷：

```json
{ "sub": "12", "username": "buyer01", "name": "张三", "org_id": 5,
  "iat": 1750000000, "exp": 1750028800 }
```

- 密钥：`CTMS_JWT_SECRET`（环境变量；未设置时使用本地文件生成的随机密钥，避免硬编码）；
- 有效期：`CTMS_JWT_HOURS`（默认 8）；**不做 refresh token**（内网低风险，过期重新登录）；
- 登出/停用：无状态令牌不能即时吊销 → 依赖每次请求**回查账号状态**（`users.status != 'enabled'` 即 401），停用即可立即失效。

### 3.2 密码哈希（标准库实现，无新依赖）

```python
# security.py
import base64, hashlib, hmac, os

_ITER = 120_000

def hash_password(raw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode(), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"

def verify_password(raw: str, stored: str) -> bool:
    try:
        _algo, iter_s, salt_b64, hash_b64 = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", raw.encode(),
                                base64.b64decode(salt_b64), int(iter_s))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:
        return False
```

### 3.3 权限点与菜单（`app/permissions.py`，唯一真源）

```python
# (code, 名称, 模块, 类型 menu|button)
PERMISSIONS: list[tuple[str, str, str, str]] = [
    ("dashboard.view",        "首页看板",       "dashboard", "menu"),

    ("contract.view",         "合同查看",       "contract", "menu"),
    ("contract.create",       "合同新增",       "contract", "button"),
    ("contract.edit",         "合同编辑",       "contract", "button"),
    ("contract.delete",       "合同停用/恢复",  "contract", "button"),
    ("contract.import",       "合同导入",       "contract", "button"),
    ("contract.export",       "合同导出",       "contract", "button"),
    ("contract.log.view",     "合同变更历史",   "contract", "button"),

    ("purchase.request.view",    "采购申请查看", "purchase", "menu"),
    ("purchase.request.create",  "采购申请新增", "purchase", "button"),
    ("purchase.request.edit",    "采购申请编辑", "purchase", "button"),
    ("purchase.request.submit",  "采购申请提交", "purchase", "button"),
    ("purchase.request.approve", "采购申请审核", "purchase", "button"),
    ("purchase.request.void",    "采购申请作废", "purchase", "button"),
    ("purchase.request.export",  "采购申请导出", "purchase", "button"),

    ("purchase.order.view",    "采购单查看",     "purchase", "menu"),
    ("purchase.order.create",  "采购单新增",     "purchase", "button"),
    ("purchase.order.edit",    "采购单编辑",     "purchase", "button"),
    ("purchase.order.submit",  "采购单提交",     "purchase", "button"),
    ("purchase.order.approve", "采购单审核",     "purchase", "button"),
    ("purchase.order.void",    "采购单作废",     "purchase", "button"),
    ("purchase.order.push",    "采购单下推入库", "purchase", "button"),
    ("purchase.order.export",  "采购单导出",     "purchase", "button"),

    ("sales.request.view",    "销售申请查看", "sales", "menu"),
    ("sales.request.create",  "销售申请新增", "sales", "button"),
    ("sales.request.edit",    "销售申请编辑", "sales", "button"),
    ("sales.request.submit",  "销售申请提交", "sales", "button"),
    ("sales.request.approve", "销售申请审核", "sales", "button"),
    ("sales.request.void",    "销售申请作废", "sales", "button"),
    ("sales.request.export",  "销售申请导出", "sales", "button"),

    ("sales.order.view",    "销售订单查看",   "sales", "menu"),
    ("sales.order.create",  "销售订单新增",   "sales", "button"),
    ("sales.order.edit",    "销售订单编辑",   "sales", "button"),
    ("sales.order.submit",  "销售订单提交",   "sales", "button"),
    ("sales.order.approve", "销售订单审核",   "sales", "button"),
    ("sales.order.void",    "销售订单作废",   "sales", "button"),
    ("sales.order.push",    "销售订单下推出库","sales", "button"),
    ("sales.order.export",  "销售订单导出",   "sales", "button"),

    ("stock.in.view",     "入库单查看",      "stock", "menu"),
    ("stock.in.create",   "入库单新增",      "stock", "button"),
    ("stock.in.edit",     "入库单编辑",      "stock", "button"),
    ("stock.in.submit",   "入库单提交",      "stock", "button"),
    ("stock.in.approve",  "入库单审核(过账)", "stock", "button"),
    ("stock.in.void",     "入库单作废",      "stock", "button"),
    ("stock.in.export",   "入库单导出",      "stock", "button"),

    ("stock.out.view",    "出库单查看",      "stock", "menu"),
    ("stock.out.create",  "出库单新增",      "stock", "button"),
    ("stock.out.edit",    "出库单编辑",      "stock", "button"),
    ("stock.out.submit",  "出库单提交",      "stock", "button"),
    ("stock.out.approve", "出库单审核(过账)", "stock", "button"),
    ("stock.out.void",    "出库单作废",      "stock", "button"),
    ("stock.out.export",  "出库单导出",      "stock", "button"),

    ("stock.take.view",    "盘点单查看", "stock", "menu"),
    ("stock.take.create",  "盘点单新增", "stock", "button"),
    ("stock.take.edit",    "盘点单编辑", "stock", "button"),
    ("stock.take.submit",  "盘点单提交", "stock", "button"),
    ("stock.take.approve", "盘点单审核", "stock", "button"),
    ("stock.take.void",    "盘点单作废", "stock", "button"),
    ("stock.take.export",  "盘点单导出", "stock", "button"),

    ("stock.balance.view", "库存明细",   "stock", "menu"),
    ("stock.ledger.view",  "库存流水",   "stock", "button"),

    ("master.org.view",      "组织架构查看", "master", "menu"),
    ("master.org.edit",      "组织架构维护", "master", "button"),
    ("master.role.view",     "角色查看",     "master", "menu"),
    ("master.role.edit",     "角色维护",     "master", "button"),
    ("master.user.view",     "账号查看",     "master", "menu"),
    ("master.user.edit",     "账号维护",     "master", "button"),
    ("master.user.resetpwd", "重置密码",     "master", "button"),
    ("master.customer.view", "客户查看",     "master", "menu"),
    ("master.customer.edit", "客户维护",     "master", "button"),
    ("master.supplier.view", "供应商查看",   "master", "menu"),
    ("master.supplier.edit", "供应商维护",   "master", "button"),
    ("master.product.view",  "物料查看",     "master", "menu"),
    ("master.product.edit",  "物料维护",     "master", "button"),
    ("master.ptype.view",    "商品类型查看", "master", "menu"),
    ("master.ptype.edit",    "商品类型维护", "master", "button"),
    ("master.uom.view",      "计量单位查看", "master", "menu"),
    ("master.uom.edit",      "计量单位维护", "master", "button"),
    ("master.wh.view",       "仓库查看",     "master", "menu"),
    ("master.wh.edit",       "仓库维护",     "master", "button"),

    ("system.dict.view",      "数据字典查看", "system", "menu"),
    ("system.dict.edit",      "数据字典维护", "system", "button"),
    ("system.param.view",     "系统参数查看", "system", "button"),
    ("system.param.edit",     "系统参数维护", "system", "button"),
    ("system.number.view",    "编号规则查看", "system", "button"),
    ("system.log.view",       "操作日志查看", "system", "menu"),
    ("system.changelog.view", "变更历史查看", "system", "menu"),
    ("system.backup.create",  "生成备份",     "system", "button"),
    ("system.backup.download","下载备份",     "system", "button"),
    ("system.about.view",     "关于",         "system", "button"),
]
```

菜单树（`MENUS`，前端渲染左侧导航，按 `perm` 裁剪）：

```python
MENUS = [
  {"key": "dashboard", "title": "首页看板", "path": "/", "icon": "Odometer", "perm": "dashboard.view"},
  {"key": "contract",  "title": "合同管理", "path": "/contracts", "icon": "Files", "perm": "contract.view"},
  {"key": "purchase",  "title": "采购管理", "icon": "ShoppingCart", "perm": "purchase.request.view", "children": [
      {"key": "purchase-request", "title": "采购申请单", "path": "/purchase/requests", "perm": "purchase.request.view"},
      {"key": "purchase-order",   "title": "采购单",     "path": "/purchase/orders",   "perm": "purchase.order.view"}]},
  {"key": "sales",     "title": "销售管理", "icon": "Sell", "perm": "sales.request.view", "children": [
      {"key": "sales-request", "title": "销售申请单", "path": "/sales/requests", "perm": "sales.request.view"},
      {"key": "sales-order",   "title": "销售订单",   "path": "/sales/orders",   "perm": "sales.order.view"}]},
  {"key": "stock",     "title": "库存管理", "icon": "Box", "perm": "stock.balance.view", "children": [
      {"key": "stock-in",      "title": "入库单",   "path": "/stock/in-orders",  "perm": "stock.in.view"},
      {"key": "stock-out",     "title": "出库单",   "path": "/stock/out-orders", "perm": "stock.out.view"},
      {"key": "stock-balance", "title": "库存明细", "path": "/stock/balances",   "perm": "stock.balance.view"},
      {"key": "stock-take",    "title": "盘点单",   "path": "/stock/takes",      "perm": "stock.take.view"}]},
  {"key": "master",    "title": "资料库", "icon": "Folder", "perm": "master.customer.view", "children": [
      {"key": "m-org",      "title": "组织架构",   "path": "/master/orgs",      "perm": "master.org.view"},
      {"key": "m-role",     "title": "角色管理",   "path": "/master/roles",     "perm": "master.role.view"},
      {"key": "m-user",     "title": "账号管理",   "path": "/master/users",     "perm": "master.user.view"},
      {"key": "m-customer", "title": "客户信息",   "path": "/master/customers", "perm": "master.customer.view"},
      {"key": "m-supplier", "title": "供应商信息", "path": "/master/suppliers", "perm": "master.supplier.view"},
      {"key": "m-base",     "title": "基础信息",   "perm": "master.product.view", "children": [
          {"key": "m-ptype", "title": "商品类型", "path": "/master/product-types", "perm": "master.ptype.view"},
          {"key": "m-prod",  "title": "物料档案", "path": "/master/products",      "perm": "master.product.view"},
          {"key": "m-uom",   "title": "计量单位", "path": "/master/uoms",          "perm": "master.uom.view"},
          {"key": "m-wh",    "title": "仓库",     "path": "/master/warehouses",    "perm": "master.wh.view"}]},
      {"key": "m-system",   "title": "系统管理",   "path": "/system",            "perm": "system.dict.view"}]},
]
```

### 3.4 依赖注入式校验（后端强制）

```python
# services/permission_service.py
def get_current_user(token: str = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    if not settings.AUTH_ENABLED:          # 本地调试开关（CTMS_AUTH_ENABLED=0）
        return _system_user(db)
    payload = decode_token(token)          # 失败 → 401
    user = db.get(User, int(payload["sub"]))
    if user is None or user.status != "enabled":
        raise HTTPException(401, "登录已失效，请重新登录")
    return user

def require_perm(code: str):
    def _dep(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if user.is_superadmin:
            return user
        if code not in collect_perms(db, user):   # 多角色并集
            raise HTTPException(403, f"无权限：{code}")
        return user
    return _dep

# 路由用法
@router.post("/{doc_id}/approve")
def approve(doc_id: int, payload: dict = Body(...),
            user: User = Depends(require_perm("purchase.order.approve")),
            db: Session = Depends(get_db)):
    ...
```

**性能**：`collect_perms` 与组织下级集合按请求缓存（同一请求内多次调用只算一次），必要时加进程内 LRU（键 = user_id + 角色版本号）。

### 3.5 数据范围注入

```python
# services/permission_service.py
def apply_data_scope(q, model, user: User, db: Session):
    if user.is_superadmin:
        return q
    scopes = {r.data_scope for r in user.roles}
    if "ALL" in scopes:
        return q
    conds = []
    if "SELF" in scopes:
        conds.append(model.created_by == user.id)
    if "DEPT" in scopes:
        conds.append(model.org_id == user.org_id)
    if "DEPT_SUB" in scopes:
        ids = org_service.descendant_ids(db, user.org_id)   # 物化路径匹配
        conds.append(model.org_id.in_(ids))
    return q.filter(or_(*conds)) if conds else q.filter(false())
```

组织下级查询用**物化路径**：`org_units.path` 形如 `/1/5/12/`，下级 = `path LIKE '/1/5/%'`（含自身）；节点移动时批量刷新后代 path（3~4 人规模，节点数极少，直接全量重算即可）。

### 3.6 前端权限落地

- 登录后 `GET /api/auth/me` 返回 `{user, org, roles, perms[], menus[]}`；
- Pinia `auth` store 持久化到 `localStorage`（含 token），刷新页面先回查 `/api/auth/me` 校验有效性；
- 路由守卫：`meta.perm` 不在 `perms` 中 → 跳 403 页；
- 按钮级：自定义指令 `v-perm="'purchase.order.approve'"`（无权限则移除元素），**仅为体验**；
- 菜单：直接渲染后端返回的 `menus` 树（后端已按权限裁剪），避免前后端两套菜单定义不一致。

### 3.7 兼容与开关

| 变量 | 默认 | 说明 |
|---|---|---|
| `CTMS_AUTH_ENABLED` | `1` | `0` = 跳过认证与权限（仅本地调试/迁移期），此时使用内置"系统账号" |
| `CTMS_JWT_SECRET` | 自动生成并落盘 `app/data/.jwt_secret` | 生产建议显式设置 |
| `CTMS_JWT_HOURS` | `8` | 令牌有效期 |

> M1 上线时若担心影响现有 3~4 人使用，可先给所有人生成账号（默认角色"只读+合同编辑"）后一次性启用，平稳过渡。

---

## 4. 数据模型详细设计

### 4.1 权限与组织（`models_auth.py`）

```python
class OrgUnit(Base):          # org_units
    id PK
    parent_id: int | None = FK("org_units.id", ondelete="SET NULL"), index
    name: str(64) 必填
    code: str(32) | None
    unit_type: str(16) = "部门"           # 公司/部门/岗位
    leader_user_id: int | None = FK("users.id", ondelete="SET NULL")
    phone: str(32) | None
    path: str(255) index                  # 物化路径 "/1/5/"
    level: int = 1
    sort: int = 0
    enabled: bool = True
    created_at / updated_at

class User(Base):             # users
    id PK
    username: str(64) UK index 必填
    password_hash: str(255) 必填
    real_name: str(64) 必填
    org_id: int | None = FK("org_units.id", ondelete="SET NULL"), index
    phone: str(32) | None
    email: str(128) | None
    status: str(16) = "enabled"            # enabled/disabled
    is_superadmin: bool = False
    must_change_pwd: bool = False
    last_login_at: datetime | None
    remark: Text | None
    created_by: int | None = FK("users.id")
    created_at / updated_at

class Role(Base):             # roles
    id PK
    code: str(32) UK index 必填
    name: str(64) 必填
    data_scope: str(16) = "SELF"           # SELF/DEPT/DEPT_SUB/ALL
    remark: Text | None
    builtin: bool = False
    enabled: bool = True
    created_at / updated_at

class UserRole(Base):         # user_roles（复合主键 user_id + role_id）
class RolePermission(Base):   # role_permissions（复合主键 role_id + perm_code）

class OperationLog(Base):     # operation_logs
    id PK
    user_id: int | None = FK("users.id", ondelete="SET NULL"), index
    username: str(64) | None; real_name: str(64) | None      # 快照
    module: str(32) index                                  # auth/contract/purchase/.../system
    action: str(32) index                                  # login/create/edit/approve/unapprove/void/export/backup/perm_change
    object_type: str(32) | None
    object_id: int | None
    object_no: str(64) | None
    result: str(16) = "success"                            # success/fail
    detail: Text | None
    ip: str(64) | None
    created_at: datetime index
```

索引：`idx_oplog_created`(created_at)、`idx_oplog_user`(user_id, created_at)、`idx_oplog_action`(action)。

### 4.2 主数据（`models_master.py`）

```python
class Customer(Base):     # customers
    id PK; code str(32) UK index; name str(128) UK index; short_name str(64) | None
    tax_no str(32) | None; contact_name str(64) | None; contact_phone str(32) | None
    address str(255) | None; bank_name str(128) | None; bank_account str(64) | None
    credit_limit Numeric(14,2) | None; level str(8) | None
    status str(16) = "enabled"; remark Text | None
    created_by FK; created_at/updated_at

class Supplier(Base):     # suppliers（同 Customer 结构，差异字段如下）
    supply_scope str(255) | None; payment_days int | None

class ProductType(Base):  # product_types
    id PK; parent_id FK(self) index; code str(32) | None; name str(64) 必填
    path str(255) index; level int; sort int; enabled bool
    created_at/updated_at

class Uom(Base):          # uoms
    id PK; code str(16) UK index; name str(32) 必填; decimals int = 2
    enabled bool; remark Text | None

class Product(Base):      # products
    id PK; code str(32) UK index 必填; name str(128) 必填; spec str(128) | None
    product_type_id FK("product_types.id") index 必填
    uom_id FK("uoms.id") 必填
    brand str(64) | None; barcode str(64) | None
    default_price Numeric(14,4) = 0; safety_stock Numeric(14,3) | None
    status str(16) = "enabled"; remark Text | None
    created_by FK; created_at/updated_at

class Warehouse(Base):    # warehouses
    id PK; code str(32) UK index; name str(64) 必填; address str(255) | None
    keeper_user_id FK("users.id") | None; enabled bool = True; remark Text | None
    created_at/updated_at
```

### 4.3 库存（`models_stock.py`）

```python
class Stock(Base):        # stocks —— 结存（商品 × 仓库）
    __table_args__ = (UniqueConstraint("product_id", "warehouse_id", name="uq_stock_prod_wh"),)
    id PK
    product_id FK("products.id") index 必填
    warehouse_id FK("warehouses.id") index 必填
    qty Numeric(16,3) = 0                 # 只记数量（D4）
    updated_at datetime

class StockLedger(Base):  # stock_ledger —— 流水（只增不改）
    id PK
    product_id FK index 必填
    warehouse_id FK index 必填
    biz_type: str(24) 必填                # 采购入库/退货入库/盘盈入库/其他入库/销售出库/领用出库/盘亏出库/其他出库/红冲-*
    doc_type: str(24) 必填                # stock_in/stock_out/stock_take
    doc_id: int 必填; doc_no: str(32) 必填
    src_doc_no: str(32) | None            # 来源单据（采购单/销售订单）
    qty_change Numeric(16,3) 必填         # 正数入库、负数出库
    qty_after Numeric(16,3) 必填          # 变动后结存快照，便于对账
    unit_price Numeric(14,4) | None       # 预留成本层（本期不使用）
    org_id int | None FK("org_units.id")
    created_by int | None FK("users.id")
    created_at datetime index
```

索引：`idx_ledger_prod_wh`(product_id, warehouse_id, id)、`idx_ledger_doc`(doc_type, doc_id)。

**一致性不变式**（对应 AC-V2-26）：对任一 `(product_id, warehouse_id)`，
`stocks.qty == SUM(stock_ledger.qty_change)`。提供运维接口 `POST /api/stock/recalc` 校验并修复（写操作日志）。

### 4.4 单据（`models_doc.py`）

公共 Mixin：

```python
class DocMixin:
    id: int PK
    doc_no: str(32) UK index 必填
    doc_date: date 必填
    status: str(16) = "draft" index
    org_id: int | None FK("org_units.id") index
    created_by: int | None FK("users.id") index
    remark: Text | None
    contract_id: int | None FK("contracts.id") index
    source_doc_type: str(24) | None
    source_doc_id: int | None
    submitted_by / submitted_at / approved_by / approved_at
    voided_by / voided_at / void_reason
    posted: bool = False                  # 库存类单据是否已过账
    deleted: bool = False
    created_at / updated_at

class DocItemMixin:
    id PK
    seq: int
    product_id FK("products.id") 必填 index
    product_code: str(32) 快照; product_name: str(128) 快照
    spec: str(128) | None 快照; uom_name: str(32) | None 快照; uom_decimals: int | None 快照
    qty: Numeric(16,3) = 0
    unit_price: Numeric(14,4) = 0
    amount: Numeric(16,2) = 0
    warehouse_id: int | None FK("warehouses.id")
    src_item_id: int | None               # 来源行项 id
    remark: Text | None
```

单据状态常量：

```python
DOC_STATUS = {"draft": "草稿", "submitted": "待审核", "approved": "已审核",
              "completed": "已完成", "voided": "已作废"}
# 库存类单据（入库/出库/盘点）approved 即终态，不使用 completed（O2）
```

8 张主表与特有字段：

| 表 | 类 | 特有字段 |
|---|---|---|
| `purchase_requests` | `PurchaseRequest` | `request_dept_id`、`need_date`、`suggest_supplier_id`、`purpose` |
| `purchase_orders` | `PurchaseOrder` | `supplier_id` NOT NULL、`supplier_name` 快照、`purchase_dept_id`、`expected_arrival_date`、`settle_type`、`currency`、`total_amount`、`receipt_warehouse_id`、`handler_user_id` |
| `sales_requests` | `SalesRequest` | `customer_id` 可空、`customer_name_text`、`sales_dept_id`、`expect_delivery_date` |
| `sales_orders` | `SalesOrder` | `customer_id` NOT NULL、`customer_name` 快照、`sales_dept_id`、`delivery_date`、`delivery_address`、`contact_name`、`contact_phone`、`ship_warehouse_id`、`currency`、`total_amount`、`handler_user_id` |
| `stock_in_orders` | `StockInOrder` | `warehouse_id` NOT NULL、`in_type` NOT NULL、`supplier_id`、`total_amount` |
| `stock_out_orders` | `StockOutOrder` | `warehouse_id` NOT NULL、`out_type` NOT NULL、`customer_id`、`total_amount` |
| `stock_takes` | `StockTake` | `warehouse_id` NOT NULL、`take_type`(full/partial)、`scope_note`、`generated_in_id`、`generated_out_id` |

8 张行项表：`purchase_request_items`、`purchase_order_items`、`sales_request_items`、`sales_order_items`、`stock_in_order_items`、`stock_out_order_items`、`stock_take_items`（另加合同已有 `contract_items`）。

行项特有字段：

| 行项表 | 特有字段 |
|---|---|
| 采购申请 / 销售申请行项 | `ordered_qty`（已下推数量，用于剩余量校验） |
| 采购单 / 销售订单行项 | `received_qty`（已入库）/ `shipped_qty`（已出库），由过账回写 |
| 入库 / 出库行项 | `src_item_id` 指向采购单/销售订单行；仓库可覆盖表头 |
| 盘点行项 | `book_qty`、`actual_qty`、`diff_qty`、`diff_reason` |

### 4.5 对 V1.0 既有表的改动

| 表 | 新增列 | 说明 |
|---|---|---|
| `contracts` | `customer_id INTEGER`、`supplier_id INTEGER` | 引用档案（D6/D10），可空 |
| `contracts` | `org_id INTEGER`、`created_by INTEGER` | 数据范围与审计 |
| `change_logs` | `operator_id INTEGER`、`operator_name VARCHAR(64)` | 操作人（修订 BR12） |
| `change_logs` | `object_type VARCHAR(32)`、`object_id INTEGER` | 支持非合同对象（合同记录 `object_type='contract'` 且 `contract_id` 继续写） |
| `attachments` | `object_type VARCHAR(32)`、`object_id INTEGER` | 支持单据附件；`contract_id` 允许为空 |

`db_migrate.py` 增量清单（幂等，SQLite 用 `ALTER TABLE ADD COLUMN`）：

```python
_ADD_COLUMNS = [
    ("contract_tag", "auto", "INTEGER NOT NULL DEFAULT 0"),
    ("contracts", "subject_code", "VARCHAR(8)"),
    # --- V2.0 ---
    ("contracts", "customer_id", "INTEGER"),
    ("contracts", "supplier_id", "INTEGER"),
    ("contracts", "org_id", "INTEGER"),
    ("contracts", "created_by", "INTEGER"),
    ("change_logs", "operator_id", "INTEGER"),
    ("change_logs", "operator_name", "VARCHAR(64)"),
    ("change_logs", "object_type", "VARCHAR(32)"),
    ("change_logs", "object_id", "INTEGER"),
    ("attachments", "object_type", "VARCHAR(32)"),
    ("attachments", "object_id", "INTEGER"),
]
# 另需 _ADD_INDEXES 与 _BACKFILL（历史 change_logs 补 object_type='contract', object_id=contract_id）
```

> 注意：SQLite 的 `ALTER TABLE ADD COLUMN` 只能加列、不能加外键约束与"无默认值的 NOT NULL"列——因此新列一律**可空、无外键约束**，外键关系由应用层保证（与 V1.0 的 `subject_code` 处理一致）。

### 4.6 系统参数（`kv_settings` 扩展，不建独立表）

```json
// key = "sys_params"
{
  "warranty_window_days": 30,
  "allow_negative_stock": false,
  "allow_self_approve": false,
  "default_qty_decimals": 2,
  "default_price_decimals": 4,
  "money_decimals": 2,
  "pwd_min_length": 8
}
// key = "number_rules"
{
  "purchase_request": {"prefix": "PR",  "reset": "month", "seq_len": 6},
  "purchase_order":   {"prefix": "PO",  "reset": "month", "seq_len": 6},
  "sales_request":    {"prefix": "SR",  "reset": "month", "seq_len": 6},
  "sales_order":      {"prefix": "SO",  "reset": "month", "seq_len": 6},
  "stock_in":         {"prefix": "IN",  "reset": "month", "seq_len": 6},
  "stock_out":        {"prefix": "OUT", "reset": "month", "seq_len": 6},
  "stock_take":       {"prefix": "ST",  "reset": "month", "seq_len": 6},
  "customer":         {"prefix": "CUS", "reset": "never", "seq_len": 4},
  "supplier":         {"prefix": "SUP", "reset": "never", "seq_len": 4},
  "product":          {"prefix": "",    "reset": "never", "seq_len": 4}
}
```

---

## 5. 核心服务设计

### 5.1 编号服务 `services/numbering_service.py`

统一入口，兼容 V1.0 合同编号（`numbering.py` 继续服务合同，不改造）：

```python
def next_doc_no(db, kind: str, ref_date: date | None = None) -> str:
    """kind ∈ number_rules 的键。
       reset=month → {prefix}{YYYYMM}{seq:06d}；reset=never → {prefix}{seq:04d}。
       序号 = 该前缀（+年月）下库内最大序号 + 1；唯一索引冲突时重试 3 次。"""
```

- 实现：对目标表 `doc_no LIKE '{prefix}{yyyymm}%'` 取最大值（与 V1.0 同思路），配合 `doc_no` 的 UNIQUE 索引 + 捕获 `IntegrityError` 重试；
- 并发安全：SQLite 全局写锁已串行化写入，重试兜底；
- 主数据编码同理（`customers.code` 等，`reset=never`）。

### 5.2 过账服务 `services/posting_service.py`（核心，最高风险）

```python
class BusinessError(Exception): ...   # 路由层捕获 → HTTP 400/422 + 中文提示

def post_stock_doc(db: Session, doc, *, user: User, reverse: bool = False,
                   skip_negative_check: bool = False) -> None:
    """对入库/出库单过账；reverse=True 表示红冲（反审核）。
       入库 +qty；出库 -qty；reverse 时整体取反。
       幂等：reverse=False 且 doc.posted → 直接返回。"""
    params = get_sys_params(db)
    if not reverse and doc.posted:
        return                                          # AC-V2-23 幂等
    sign = (1 if doc.direction > 0 else -1) * (-1 if reverse else 1)
    for item in doc.items:
        wh_id = item.warehouse_id or doc.warehouse_id
        stock = _get_stock(db, item.product_id, wh_id)  # 不存在则创建 qty=0
        delta = sign * item.qty
        new_qty = (stock.qty or 0) + delta
        if new_qty < 0 and not params["allow_negative_stock"] and not skip_negative_check:
            raise BusinessError(
                f"{wh.name} {item.product_name} 库存不足（可用 {stock.qty}，需要 {item.qty}）")  # AC-V2-21
        stock.qty = new_qty
        stock.updated_at = datetime.now()
        db.add(StockLedger(
            product_id=item.product_id, warehouse_id=wh_id,
            biz_type=("红冲-" + item_biz_type(doc, item)) if reverse else item_biz_type(doc, item),
            doc_type=doc.doc_type, doc_id=doc.id, doc_no=doc.doc_no,
            src_doc_no=doc.source_doc_no, qty_change=delta, qty_after=new_qty,
            unit_price=item.unit_price, org_id=doc.org_id, created_by=user.id))
    doc.posted = not reverse
    if reverse:
        push_service.rollback_received_qty(db, doc)
    else:
        push_service.backfill_received_qty(db, doc)      # 回写采购单已入库/销售订单已出库
    audit_service.log(db, user, module="stock",
                      action="unapprove" if reverse else "approve",
                      object_type=doc.doc_type, object_id=doc.id, object_no=doc.doc_no)
```

**事务边界**：审核接口整体在一个事务内完成（状态变更 + 流水 + 结存 + 回写 + 审计），路由层统一 `db.commit()`；任一步抛错则 `db.rollback()`，保证 AC-V2-21（拦截时库存与单据状态都不变）。

**盘点单过账**（差异调整，对应 AC-V2-28/29）：

```python
def approve_stock_take(db, take, *, user):
    diffs = [it for it in take.items if (it.diff_qty or 0) != 0]
    if diffs:
        gain = [d for d in diffs if d.diff_qty > 0]      # 盘盈 → 生成盘盈入库单并过账
        loss = [d for d in diffs if d.diff_qty < 0]      # 盘亏 → 生成盘亏出库单并过账
        if gain:
            in_doc = create_adjust_doc(db, take, "in", gain, user)
            post_stock_doc(db, in_doc, user=user); take.generated_in_id = in_doc.id
        if loss:
            out_doc = create_adjust_doc(db, take, "out", loss, user)
            # 盘亏豁免负库存校验：账实不符本身即差异证据，拦截将导致永远无法平账
            post_stock_doc(db, out_doc, user=user, skip_negative_check=True)
            take.generated_out_id = out_doc.id
    take.status = "approved"
```

> `skip_negative_check` 的设计理由必须写进代码注释与本文档：盘点差异是"账面与实物不符"的修正动作，若被负库存校验拦截，盘点将永远无法完成。

### 5.3 下推服务 `services/push_service.py`

```python
def remaining_qty(item) -> Decimal:
    """采购申请→采购单：qty - ordered_qty
       采购单→入库单：  qty - received_qty
       销售申请→订单：  qty - ordered_qty
       销售订单→出库单：qty - shipped_qty"""

def push(db, src_doc, *, target_kind, item_payloads, user)   # 生成下游草稿单
def backfill_received_qty(db, stock_in_doc)                  # 过账后回写来源采购单行
def rollback_received_qty(db, stock_in_doc)                  # 红冲时回退
def assert_source_voidable(db, doc)                          # 上游作废/反审核前检查下游（AC-V2-24）
```

### 5.4 审计服务 `services/audit_service.py`

```python
def log(db, user, *, module, action, object_type=None, object_id=None,
        object_no=None, result="success", detail=None, ip=None) -> None
def change(db, *, object_type, object_id, field, old, new, note=None, source="manual", user=None)
```

- `change` 兼容 V1.0 的 `contract_id` 写入（`object_type='contract'` 时 `contract_id = object_id`）；
- 合同改造：`routers/contracts.py` 的 `_log()` 增加 `user` 参数（从当前登录用户取），其余逻辑不动。

### 5.5 备份服务 `services/backup_service.py`

```python
def create_backup() -> Path:
    """SQLite 用 sqlite3 的 backup API 生成一致性快照 → 与 uploads/ 一起打 zip
       → 存 app/data/backups/ctms_backup_YYYYmmdd_HHMMSS.zip"""
```

- 不用文件复制（避免写事务期间复制出损坏库）；
- 下载走 `GET /api/system/backup/{name}`（鉴权 + 路径穿越防护 + 文件名白名单）。

---

## 6. 接口清单

### 6.1 认证与系统

| 方法 | 路径 | 权限 |
|---|---|---|
| POST | `/api/auth/login` | — |
| POST | `/api/auth/logout` | 登录 |
| GET | `/api/auth/me` | 登录 |
| POST | `/api/auth/change-password` | 登录 |
| GET/POST/PUT | `/api/system/org-units` | `master.org.view` / `.edit` |
| GET/POST/PUT | `/api/system/roles`、`/api/system/roles/{id}` | `master.role.*` |
| GET/POST/PUT | `/api/system/users`、`/api/system/users/{id}`、`/{id}/reset-password` | `master.user.*` |
| GET/PUT | `/api/system/params` | `system.param.*` |
| GET | `/api/system/number-rules` | `system.number.view` |
| GET | `/api/system/logs` | `system.log.view` |
| GET | `/api/system/changelogs` | `system.changelog.view` |
| POST/GET | `/api/system/backup`、`/api/system/backup/{name}` | `system.backup.*` |
| GET | `/api/system/about` | `system.about.view` |

### 6.2 主数据

| 资源 | 路径前缀 | 权限前缀 |
|---|---|---|
| 客户 | `/api/master/customers` | `master.customer.*` |
| 供应商 | `/api/master/suppliers` | `master.supplier.*` |
| 商品类型 | `/api/master/product-types` | `master.ptype.*` |
| 物料 | `/api/master/products` | `master.product.*` |
| 计量单位 | `/api/master/uoms` | `master.uom.*` |
| 仓库 | `/api/master/warehouses` | `master.wh.*` |

统一约定：`GET` 列表（分页 + 关键字 + 状态筛选）、`POST` 新增、`GET/{id}` 详情、`PUT/{id}` 修改、`PUT/{id}/status` 停用/启用、`GET /api/master/options/{kind}`（轻量下拉数据，供单据页引用）。

### 6.3 单据（8 类统一模式）

以采购单为例，其余同构：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/purchase/orders` | 分页列表（编号/日期/状态/供应商/物料/经办人/关联合同 + 数据范围） |
| POST | `/api/purchase/orders` | 新增（草稿） |
| GET/PUT | `/api/purchase/orders/{id}` | 详情 / 修改（仅草稿） |
| POST | `/api/purchase/orders/{id}/submit` | 提交审核 |
| POST | `/api/purchase/orders/{id}/approve` | 审核通过 |
| POST | `/api/purchase/orders/{id}/reject` | 驳回（回草稿，必填原因） |
| POST | `/api/purchase/orders/{id}/complete` | 手工置"已完成" |
| POST | `/api/purchase/orders/{id}/void` | 作废（必填原因） |
| POST | `/api/purchase/orders/{id}/unapprove` | 反审核（必填原因） |
| POST | `/api/purchase/orders/{id}/push` | 下推生成入库单草稿 |
| GET | `/api/purchase/orders/{id}/changelogs` | 变更历史 |
| GET | `/api/purchase/orders/export.xlsx` | 导出当前筛选 |

对应前缀：`/api/purchase/requests`、`/api/sales/requests`、`/api/sales/orders`、`/api/stock/in-orders`、`/api/stock/out-orders`、`/api/stock/takes`。

### 6.4 库存

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/stock/balances` | 结存列表（仓库/类型/关键字/低于安全库存） |
| GET | `/api/stock/ledger` | 流水（product_id + warehouse_id 必填 + 日期区间） |
| POST | `/api/stock/recalc` | 结存重算校验（运维，写操作日志） |
| GET | `/api/stock/balances/export.xlsx` | 导出结存 |

### 6.5 合同扩展

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/contracts/{id}/related-docs` | 关联单据 + 已执行汇总（只读，AC-V2-32） |
| GET | `/api/contracts/{id}/logs` | 变更历史（补操作人） |
| POST | `/api/contracts/migrate-parties` | 历史甲乙方→档案草案生成（一次性，AC-V2-35） |
| GET | `/api/contracts/party-drafts` | 草案列表（认领页） |
| POST | `/api/contracts/party-drafts/{id}/claim` | 认领并批量绑定 |

---

## 7. 前端设计

### 7.1 目录结构

```
web/src/
  main.ts
  App.vue                     # 仅承载 <router-view/> 与全局样式
  layout/
    AppLayout.vue             # 侧边菜单 + 顶栏 + 主区（替代原 App.vue 的布局职责）
  components/
    SideMenu.vue              # 渲染 /api/auth/me 的 menus 树
    TopBar.vue                # 当前用户/组织/改密/登出
    doc/
      DocListPage.vue         # 单据列表通用壳（筛选区 + 表格 + 分页 + 导出）
      DocFormPage.vue         # 单据表单通用壳（表头 + 行项 + 保存/提交）
      DocItemsTable.vue       # 行项编辑表格（物料选择、数量/单价/金额联动、快照列）
      DocStatusTag.vue        # 状态标签（颜色映射）
      ApproveDialog.vue / RejectDialog.vue / VoidDialog.vue / UnapproveDialog.vue
    ProductPicker.vue         # 物料选择器（弹窗 + 关键字/类型筛选）
    PartyPicker.vue           # 客户/供应商选择器
    TreePage.vue              # 树 + 详情通用壳（组织架构/商品类型复用）
  directives/perm.ts          # v-perm
  router/
    index.ts  routes.ts  guard.ts
  stores/
    auth.ts  meta.ts
  api/
    client.ts                 # axios 实例 + 401 拦截 + token 注入
    auth.ts  master.ts  purchase.ts  sales.ts  stock.ts  system.ts  contract.ts
  views/
    LoginView.vue  ForbiddenView.vue
    dashboard/DashboardView.vue
    contract/ContractsView.vue              # V1.0 单文件保留，M4 渐进拆分
    purchase/RequestList.vue  RequestForm.vue  OrderList.vue  OrderForm.vue
    sales/RequestList.vue  RequestForm.vue  OrderList.vue  OrderForm.vue
    stock/InList.vue  InForm.vue  OutList.vue  OutForm.vue
          BalanceView.vue  TakeList.vue  TakeForm.vue
    master/OrgView.vue  RoleView.vue  UserView.vue  CustomerView.vue
           SupplierView.vue  ProductTypeView.vue  ProductView.vue  UomView.vue  WarehouseView.vue
    system/SystemView.vue（页签：字典/编号规则/参数/操作日志/变更历史/备份/关于）
```

### 7.2 路由表

```ts
{ path: '/login', component: LoginView, meta: { public: true } }
{ path: '/', component: AppLayout, children: [
  { path: '', name: 'dashboard', component: DashboardView, meta: { perm: 'dashboard.view' } },
  { path: 'contracts', name: 'contracts', component: ContractsView, meta: { perm: 'contract.view' } },
  { path: 'purchase/requests', ... }, { path: 'purchase/requests/new' | ':id/edit' | ':id', ... },
  { path: 'purchase/orders', ... },   // 同构
  { path: 'sales/requests', ... }, { path: 'sales/orders', ... },
  { path: 'stock/in-orders', ... }, { path: 'stock/out-orders', ... },
  { path: 'stock/balances', meta: { perm: 'stock.balance.view' } },
  { path: 'stock/takes', ... },
  { path: 'master/orgs' | 'roles' | 'users' | 'customers' | 'suppliers'
        | 'product-types' | 'products' | 'uoms' | 'warehouses', ... },
  { path: 'system', meta: { perm: 'system.dict.view' } },
  { path: '403', component: ForbiddenView },
]}
```

### 7.3 单据页面统一交互范式

1. **列表页**：筛选区（编号、日期区间、状态、对方单位、物料、关联合同、经办人）+ 表格 + 分页 + 顶部动作（新增 / 导出）+ 行内动作（查看/编辑/提交/审核/作废，按权限与状态显示）；
2. **表单页**：表头字段（两列布局）+ 行项表格（物料选择、数量、单价、金额自动计算、快照列只读）+ 底部（保存草稿 / 保存并提交 / 返回）；
3. **详情页**：只读展示 + 动作按钮（按状态机与权限渲染）+ 变更历史时间线 + 附件区 + 来源/下游单据链接；
4. 所有"审核/驳回/作废/反审核"统一弹窗组件，**原因必填项在弹窗内校验**；
5. 状态标签颜色：草稿灰、待审核橙、已审核蓝、已完成绿、已作废红。

> 结论：`DocListPage.vue` + `DocFormPage.vue` + `DocItemsTable.vue` 三个通用组件覆盖 8 类单据，各页面只提供字段配置（列定义、表头字段定义），显著降低重复代码。

---

## 8. 一致性与并发

### 8.1 SQLite 配置（3~4 人可接受）

```python
# database.py 增量
@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _rec):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")      # 改善读写并发
    cur.execute("PRAGMA busy_timeout=5000")     # 写锁等待 5s 而非立即报错
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()
```

### 8.2 并发风险与对策

| 风险 | 对策 |
|---|---|
| 编号并发重复 | 唯一索引 + `IntegrityError` 重试（最多 3 次）；SQLite 写串行化天然降低概率 |
| 过账并发超卖 | 过账在单事务内完成；SQLite 同一时刻只有一个写事务，天然串行；负库存校验与扣减在同一事务内 |
| 重复审核（双击/重放） | `doc.posted` 幂等检查（AC-V2-23） |
| 长时间事务阻塞 | 过账循环内避免跨网络/IO；单据行数预期 < 100 行 |
| 未来切 PostgreSQL（非本期） | 用 `SELECT ... FOR UPDATE` 替代全局写锁；`_get_stock()` 已抽为独立函数，改一处即可 |

---

## 9. 测试策略

| 层次 | 内容 |
|---|---|
| 单元测试（pytest） | 编号引擎（跨月/跨年重置、并发重试）、过账（正常/负库存/幂等/红冲）、盘点差异生成、下推剩余量、数据范围 SQL、密码哈希与 JWT |
| 接口测试 | 8 类单据主流程：创建→提交→审核→过账→反审核→作废 + 越权 403 + 数据范围隔离 |
| 场景回归 | 把 `11` 的 AC-V2-01~42 逐条转成 pytest 用例（P0 全转），形成"按规格回归" |
| 数据一致性 | 定时/手动 `POST /api/stock/recalc` 断言 `stocks.qty == SUM(ledger.qty_change)` |
| 前端冒烟 | 关键流程手工清单：登录→建主数据→采购闭环→库存核对→盘点→合同对账 |

---

## 10. 迁移与上线步骤（M1 上线）

```
1. 停服 → 备库：复制 app/data/ctms.db 与 app/uploads/ 到备份盘
2. 拉取新代码 → 安装依赖（无新增第三方依赖）
3. python -m app.init_db        # 建新表 + ensure_schema_upgrades 加列 + 种子（角色/权限/系统参数/超管）
4. 配置环境变量：CTMS_JWT_SECRET、CTMS_AUTH_ENABLED=1
5. 启动 → 用 admin 首登（强制改密）→ 建组织 → 建角色 → 建账号
6. 执行 POST /api/contracts/migrate-parties 生成档案草案 → 在认领页确认
7. 冒烟：AC-V2-01~12（权限与主数据）+ 原合同模块 AC-01~15 回归
8. 回滚方案：停服 → 恢复第 1 步备份的数据库与附件 → 回滚代码版本
```

> 用户表/权限表的种子是**幂等**的（已存在则跳过），重复执行安全。

---

## 11. 风险与对策

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| R1 | 推翻"无登录"决策后，现有用户访问被中断 | 使用受阻 | 提供 `CTMS_AUTH_ENABLED` 开关 + 预置账号 + 一次性全员建号；M1 上线前做一次内部演示 |
| R2 | 过账逻辑缺陷导致库存错账 | 高（数据可信度崩塌） | 过账服务单点实现 + 单元测试覆盖 + `recalc` 校验接口 + 流水只增不改（可回溯重算） |
| R3 | 8 类单据 × 8 张行项表重复代码多，易漏字段 | 中 | 用 Mixin + 三个通用前端组件；每类单据上线前跑同一套接口测试模板 |
| R4 | 历史合同甲乙方迁移产生脏档案 | 中 | 只生成"停用"草案 + 人工认领，不自动绑定 |
| R5 | SQLite 写锁在并发审核时偶发 `database is locked` | 低 | WAL + busy_timeout=5000 + 写事务短小；必要时应用层重试 |
| R6 | 前端重构面大（3 路由 → 25 路由） | 中 | 保留原 `ContractsView.vue` 不动，新增页面独立开发，M4 再渐进拆分 |
| R7 | 权限点清单漏项导致"点了报 403" | 中 | 权限点由后端唯一真源生成，前端只消费 `/api/auth/me`；上线前按角色跑菜单巡检 |
| R8 | 范围膨胀（O1~O15 + 财务/成本诉求） | 高 | 冻结 §14 范围外清单；新需求走 `03` 变更登记表，评估后再排期 |

---

## 12. 追溯矩阵（PRD → 设计落点）

| PRD 条目 | 设计落点 |
|---|---|
| D1 账号权限 | §3.1~3.6、§4.1 |
| D2 模块范围 | §2（目录）、§6（接口）、§7（前端） |
| D3/D12 单据↔合同 | §5.3（下推）、§6.5（related-docs）、§4.5（contracts 新列） |
| D4 库存只记数量 | §4.3（`stocks.qty`）、§5.2 |
| D5 单级审核+过账 | §5.2、§4.4（状态常量） |
| D6/D10 甲乙方映射 | §4.5、§6.5 |
| D8 SQLite | §8.1、§4.5 迁移 |
| D9 数据权限 | §3.5 |
| D11 单位 | §4.2（`uoms.decimals`）、§5.2 精度校验 |
| BR-V2-01 编号 | §5.1 |
| BR-V2-02 状态机 | §4.4（`DOC_STATUS`）+ 各单据路由动作 |
| BR-V2-03 审核过账 | §5.2 |
| BR-V2-04/05 库存与负库存 | §4.3（不变式）、§5.2 |
| BR-V2-06 盘点差异 | §5.2（`approve_stock_take`） |
| BR-V2-07 合同关联 | §6.5 |
| BR-V2-08 权限三层 | §3.3~3.6 |
| BR-V2-17 下推 | §5.3 |
| AC-V2-21 负库存拦截 | §5.2（`BusinessError` + 事务回滚） |
| AC-V2-23 幂等 | §5.2（`posted` 检查） |
| AC-V2-26 结存=流水 | §4.3（`recalc`） |
| AC-V2-32 合同只读汇总 | §6.5（`related-docs`） |
| AC-V2-41 后端强校验 | §3.4 |

---

## 13. 下一步

1. 本设计评审（重点：§3 认证权限、§5.2 过账服务、§4.5 迁移清单、§8 并发）；
2. 评审通过后进入 M1 开发（任务清单见 `03-development-plan.md` §9）；
3. 每完成一个功能（其 AC 全绿）即 commit，并在 `03` 的变更登记表留痕。
