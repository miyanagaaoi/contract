# 13. V2.0 · M1 验收报告（权限与主数据地基）

> 验收对象：`docs/03-development-plan.md` §9.3 **M1 权限与主数据地基**（T-V2-01 ~ T-V2-16）。
> 验收依据：`docs/11-erp-requirements.md` §16 **AC-V2-01 ~ AC-V2-12**、`docs/12-erp-system-design.md` 设计约束。
> 执行时间：2026（本报告随 M1 代码提交）。
> 服务地址：`http://127.0.0.1:8010`（本轮验收实例；生产/开发默认 8000）。

## 1. 结论

| 项 | 结果 |
|---|---|
| M1 任务 T-V2-01 ~ T-V2-16 | **全部完成**（除 T-V2-16 的"人工目视 UI"一项见 §5） |
| 自动化测试 | `pytest app/tests -q` → **203 passed** |
| M1 端到端冒烟（真实 HTTP + 登录令牌） | `python app/tests/smoke_m1.py` → **15/15 PASS** |
| V1.0 合同模块回归（AC-01~AC-11/12/14） | `python app/tests/smoke_p0.py` → **13/13 PASS** |
| 前端构建 | `npm run build` → **成功**（全部新页面进入产物） |
| 服务健康 | `GET /api/health` → `{"status":"ok","db":true}`；SPA 首页 200 |

**Go 判定：M1 达到"可上线"条件**，可进入 M2（采购线与库存过账）。
保留 `CTMS_AUTH_ENABLED=0` 回退开关（R1 对策），异常时可临时关闭认证。

## 2. 交付物

### 2.1 后端

| 文件 | 说明 |
|---|---|
| `app/security.py`、`app/models_auth.py`、`app/permissions.py` | T-V2-01/04：JWT + pbkdf2、账号/角色/组织/操作日志模型、权限点与菜单真源 |
| `app/services/permission_service.py` | `require_perm` / `apply_data_scope`（服务端强校验与数据范围） |
| `app/services/org_service.py`、`role_service.py`、`user_service.py`、`audit_service.py` | T-V2-03/04/05：组织树、角色、账号、审计 |
| `app/routers/auth.py`、`system.py` | 登录/登出/改密/me；组织/角色/账号 + **T-V2-12 系统管理**（参数、编号规则、操作日志、变更历史、备份、关于） |
| `app/services/backup_service.py` | T-V2-12：SQLite 在线快照 + 附件打包 zip（含路径穿越防护） |
| `app/models_master.py` | T-V2-07~11：客户、供应商、商品类型、计量单位、仓库、物料、迁移草案 |
| `app/services/master_service.py`、`numbering_service.py`、`routers/master.py` | 主数据 CRUD、统一取号、REST + 下拉/元数据 |
| `app/services/migrate_service.py` | T-V2-14：历史甲乙方文本 → 草案 → 认领 → 批量绑定 |
| `app/routers/contracts.py` | T-V2-13：`customer_id`/`supplier_id` 档案化（校验存在、回填名称快照、带操作人的变更历史）+ 迁移端点 |

### 2.2 前端

| 文件 | 说明 |
|---|---|
| `web/src/layout/AppLayout.vue`、`components/MenuTree.vue`、`components/TopBar.vue`、`App.vue` | T-V2-15：主布局重构（菜单由后端权限裁剪后返回，前端不写死） |
| `web/src/router/index.ts` | 路由表（主区挂 AppLayout；`/settings` → `/system` 兼容旧入口） |
| `web/src/types/master.ts`、`components/MasterTablePage.vue`、`components/TreeMasterPage.vue` | 配置驱动的通用主数据页（列表/表单/启停用/删除、树形页） |
| `web/src/views/master/*.vue` | 客户、供应商、商品类型、物料、计量单位、仓库、组织、角色、账号、历史档案认领（10 个页面） |
| `web/src/views/system/SystemView.vue` | 系统管理页签（数据字典内嵌原设置页 + 参数/编号/日志/变更历史/备份/关于） |
| `web/src/api.ts` | 主数据/系统管理/迁移 API 封装（含 401 拦截、blob 下载） |
| `web/src/views/ContractsView.vue` | 合同表单按类型切换甲乙方选择器（PUR→供应商、SAL→客户），列表标注"档案" |

### 2.3 测试与脚本

| 文件 | 覆盖 |
|---|---|
| `app/tests/test_v2_auth*.py`、`test_v2_org.py`、`test_v2_role_user.py`、`test_v2_contract_perm.py`、`test_v2_api_gate.py` | T-V2-01~06（既有，115 项） |
| `app/tests/test_v2_master.py` | T-V2-07~11（37 项：编码生成/叶子校验/引用校验/权限） |
| `app/tests/test_v2_system.py` | T-V2-12（22 项：参数/编号/日志/变更历史/备份/关于） |
| `app/tests/test_v2_parties.py` | T-V2-13/14（15 项：档案化、迁移认领、权限） |
| `app/tests/smoke_m1.py` | **M1 验收冒烟**（AC-V2-01~12 + 迁移 + 系统管理，15 项） |
| `app/tests/smoke_p0.py` | V1.0 合同模块回归（已升级为携带登录令牌，13 项） |

## 3. 验收场景执行记录（AC-V2-01 ~ AC-V2-12）

| AC | 场景 | 证据 | 结果 |
|---|---|---|---|
| AC-V2-01 | 登录鉴权：错密码 401 + 操作日志，正确密码返回登录态与裁剪菜单 | `smoke_m1.ac_v2_01` | PASS |
| AC-V2-02 | 未登录拦截（业务与主数据接口 401，前端跳登录页） | `smoke_m1.ac_v2_02` | PASS |
| AC-V2-03 | 菜单与按钮权限（仓管员菜单裁剪；直接调接口 403） | `smoke_m1.ac_v2_03` | PASS |
| AC-V2-04 | 数据范围-本人 | `smoke_m1.ac_v2_04_05_06` | PASS |
| AC-V2-05 | 数据范围-本部门及下级 | 同上（采购部主管见下级"采购一组"数据，跨部门不可见） | PASS |
| AC-V2-06 | 多角色权限并集（范围取最宽，写权限仍受限） | 同上 | PASS |
| AC-V2-07 | 组织节点删除校验（有子节点/有账号 → 拒绝，可停用） | `smoke_m1.ac_v2_07` | PASS |
| AC-V2-08 | 首登强制改密 + 管理员重置再次强制 | `smoke_m1.ac_v2_08` | PASS |
| AC-V2-09 | 商品类型树与物料挂载（非叶子拒绝） | `smoke_m1.ac_v2_09_10_11` | PASS |
| AC-V2-10 | 物料编码自动生成与唯一（递增 + 重复拒绝） | 同上 | PASS |
| AC-V2-11 | 计量单位小数位校验（0~4） | 同上 | PASS |
| AC-V2-12 | 客户/供应商停用（下拉隐藏，历史合同显示名称快照） | `smoke_m1.ac_v2_12` | PASS |
| AC-V2-33/34/35 | 合同甲乙方档案化、历史文本兜底、认领迁移 | `smoke_m1.extras_migration_and_system`、`test_v2_parties.py` | PASS |
| AC-V2-36/37 | 操作日志（动作+时间筛选）、变更历史带操作人 | `test_v2_system.py`、`smoke_p0` | PASS |
| AC-V2-38/39 | 系统管理整合、手动备份下载 | `smoke_m1.extras_migration_and_system` | PASS |
| AC-V2-41/42 | 权限后端强校验、数据范围与主数据边界 | `test_v2_master.py::TestMasterPermissions`、`smoke_m1` | PASS |

> AC-V2-04/05/06 的原始描述针对"采购申请单"；单据域在 M2 落地，本轮以**合同台账**验证同一套数据范围机制
> （`apply_data_scope` 为单据与合同共用），机制同源，M2 验收时以单据复核。

## 4. 本轮发现并修复的缺陷

| # | 问题 | 影响 | 修复 |
|---|---|---|---|
| 1 | 编号规则前缀校验用 `str.isalpha()`，中文被判定为合法 | 可把客户编码前缀改成中文，生成"客户0001" | `dicts.set_number_rules` 加 `isascii()` 限定（仅 A~Z） |
| 2 | 取号时对整串编码提取尾部数字，前缀含数字（如类型码 `L476`）会并入序号 | 生成 `L4764760002` 的膨胀编码，序号错乱 | `numbering_service._next_by_prefix` 改为**从前缀之后**提取序号（新增回归用例） |
| 3 | 合同 `customer_id`/`supplier_id` 只存不校验 | 脏引用（指向不存在档案）可入库 | `_apply_party_refs` 校验档案存在，不存在返回 422 |
| 4 | 编号规则为全局配置，测试用例修改后未还原 | 污染开发库（曾把客户前缀写成 `KH`/中文） | 新增模块级 fixture 还原编号规则；用例改用唯一前缀隔离 |

## 5. 未覆盖项与风险

| # | 项 | 说明 | 处理 |
|---|---|---|---|
| 1 | **前端 UI 目视验收** | 本轮 DSH 的浏览器自动化组件不可用（`bsk` 未安装），无法截图核对；已用"构建通过 + 全部组件进入产物"作为替代证据 | M1 上线前由人工按 §6 清单点击一遍；或安装 `bsk` 后补做 |
| 2 | 各内置角色逐一登录巡检（T-V2-39 的前置） | 菜单裁剪已由 `smoke_m1` 对 buyer/keeper 验证；其余角色在 M4 的 T-V2-39 统一复核 | 列入 M4 |
| 3 | SQLite 并发写 | 3~4 人规模可接受（WAL + busy_timeout） | 按 R4 盯防，M4 备份演练覆盖 |

## 6. 人工验收清单（M1 上线前，浏览器）

启动（二选一）：

```powershell
# A. 开发模式（前端热更新）
app\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload   # 终端 1
cd web; npm run dev                                                                          # 终端 2

# B. 单进程（构建产物由后端托管）
cd web; npm run build
$env:CTMS_SERVE_STATIC=1; $env:CTMS_WEB_DIST="D:\dsh\hetong\web\dist"
app\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

登录：`admin / admin12345`（首次登录会被强制改密）。

- [ ] 登录页 → 改密页 → 首页看板（菜单与角色匹配）
- [ ] 资料库 → 客户信息：新增（编码自动生成）、编辑、停用、删除被拒时的中文提示
- [ ] 资料库 → 基础信息：商品类型树新增/停用；物料挂载到非叶子类型被拒
- [ ] 资料库 → 组织架构：新增子节点、移动、删除校验
- [ ] 资料库 → 角色管理：权限树勾选后保存，"仓管员"看不到系统管理
- [ ] 资料库 → 账号管理：新增账号（首登改密）、重置密码、停用自己被拒
- [ ] 合同台账：类型选"销售/收入"时甲方变客户选择器；选"采购/支出"时乙方变供应商选择器
- [ ] 历史档案认领：扫描 → 认领 → 对应合同出现"档案"标记
- [ ] 系统管理 → 各页签（字典/参数/编号规则/日志/变更历史/备份/关于）
- [ ] 备份：生成 → 下载 zip → 解压含 `ctms.db` 与 `uploads/`

## 7. 下一里程碑（M2）入口条件

- [x] M1 全部任务通过验收（自动化证据见 §1/§3）
- [x] 文档同步（`03` §9 任务状态、本报告）
- [ ] 人工目视清单（§6）通过后打 tag `v2.0-m1`
- 进入 M2：T-V2-17 单据公共层 → T-V2-18 编号服务扩展（8 类单据）→ **T-V2-19 过账服务**（关键路径）
