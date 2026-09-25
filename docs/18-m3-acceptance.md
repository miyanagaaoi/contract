# 18. V2.0 · M3 验收报告（销售、盘点与导出）

> 验收对象：`docs/03-development-plan.md` §9.3 **M3 销售与盘点**（T-V2-29 ~ T-V2-36）。
> 验收依据：`docs/11-erp-requirements.md` **AC-V2-20/21/27~30/40**，以及采购线同构条款（AC-V2-16/18）。

## 1. 结论

| 项 | 结果 |
|---|---|
| M3 后端（T-V2-29~32） | **完成**（销售申请/销售订单/出库单/盘点单，提前在 M2 期间落地） |
| T-V2-34 安全库存预警 | **完成**（后端 `below_safety` 筛选 + 看板预警 + 明细页高亮） |
| T-V2-35 导出扩展 | **完成**（7 类单据 + 库存结存/流水） |
| M3 端到端冒烟 | `python app/tests/smoke_m3.py` → **11/11 PASS** |
| 全量自动化测试 | `pytest app/tests -q` → **244 passed** |
| M1/M2/V1.0 回归 | `smoke_m1` 15/15、`smoke_m2` 11/11、`smoke_p0` 13/13 |
| M3 前端（T-V2-33：销售/出库/盘点页面） | **完成**：`npm run build` 通过（`✓ built in 4.80s`），销售/出库/盘点路由与页面 chunk 全部产出 |

## 2. 交付物

### 2.1 后端（M3）

| 文件 | 内容 |
|---|---|
| `app/routers/sales.py` | `/api/sales/requests`、`/api/sales/orders` 及下推端点（销售申请→销售订单→出库单）、销售合同下拉 |
| `app/routers/stock.py` | 出库单（`out_type`、客户档案化）、盘点单（`generate` 生成行项、`count` 录入实盘）、结存/流水/重算 |
| `app/services/push_service.py` | 销售线下推与 `shipped_qty` 回写/回退（与采购线同构） |
| `app/services/posting_service.py` | 盘点差异自动生成盘盈入库/盘亏出库单并过账；盘亏豁免负库存校验（账实不符修正不应被拦） |
| `app/routers/doc_routes.py`、`app/routers/export.py` | 单据导出端点（7 类）+ 通用 xlsx 工具；**导出与列表同一查询构建**（同数据范围） |
| `app/routers/dashboard.py` | 看板重规划：待办、库存预警、合同概览（T-V2-38，M4 项，提前交付） |
| `app/services/print_service.py`、`doc_routes` | 单据 A4 打印 HTML（T-V2-37，M4 项，提前交付） |

### 2.2 测试与脚本

| 文件 | 覆盖 |
|---|---|
| `app/tests/test_v2_sales.py` | 销售闭环（备货→申请→订单→出库→回写）、库存不足拦截、权限边界 |
| `app/tests/test_v2_docs.py`（扩展） | 盘点（全盘/抽盘/盘盈/盘亏）、导出（4 项）、打印（2 项）、附件、合同关联单据 |
| `app/tests/test_v2_dashboard.py` | 看板待办/库存预警/合同概览 |
| `app/tests/smoke_m3.py` | **M3 端到端冒烟**（销售闭环、盘点调整、预警、导出、打印、合同汇总） |
| `app/tools/audit_role_matrix.py` | 权限矩阵复核（`16-permission-matrix.md`） |
| `app/tests/drill_backup_restore.py` | 备份恢复演练（`15-backup-drill.md`） |

### 2.3 前端（T-V2-33）

| 文件 | 说明 |
|---|---|
| `web/src/views/sales/{RequestList,RequestForm,OrderList,OrderForm}.vue` | 销售申请单与销售订单页面（客户选择器、下推出库、关联合同下拉为销售方向） |
| `web/src/views/stock/{OutList,OutForm}.vue` | 出库单页面（与入库单同构，出库类型/客户） |
| `web/src/views/stock/{TakeList,TakeForm}.vue` | 盘点单页面（全盘/抽盘、生成行项、实盘录入与差异高亮、审核后显示生成的盘盈/盘亏单号） |
| `web/src/components/doc/*`（增强） | 列表导出入口、打印入口 |
| `web/src/router/index.ts`、`web/src/api.ts` | 销售/出库/盘点路由与 API 封装 |

> 前端验证方式与 M2 相同：`npm run build` 通过 + 后端 HTTP 契约冒烟；浏览器点击确认见 `17-uat-plan.md` §4。

## 3. 验收记录

| 场景 | 证据 | 结果 |
|---|---|---|
| AC-V2-16 同构：销售申请下推销售订单（20 + 剩余 10，超额拦截） | `smoke_m3` | PASS |
| AC-V2-20 同构：销售出库过账（结存 30→10）并回写出库数量 | `smoke_m3` | PASS |
| AC-V2-21：可用库存不足时审核被拦截，库存与单据状态不变 | `smoke_m3` / `test_v2_sales` | PASS |
| AC-V2-27：全盘按当前结存生成行项，账面只读 | `smoke_m3` / `test_v2_docs` | PASS |
| AC-V2-28：盘亏自动生成盘亏出库单并过账（结存 10→7） | `smoke_m3` | PASS |
| AC-V2-29：盘盈自动生成盘盈入库单并过账（结存 7→9） | `smoke_m3` | PASS |
| AC-V2-30：抽盘按商品类型/指定物料生成行项 | `test_v2_docs` | PASS |
| AC-V2-40：销售订单导出条数=当前筛选；库存结存导出数值正确 | `smoke_m3` | PASS |
| AC-V2-40：导出遵守数据范围（不得导出他人单据） | `test_v2_docs::TestDocExport` | PASS |
| BR-V2-16：出库单打印含单号与签字栏；越权打印被 403 | `smoke_m3` | PASS |
| AC-V2-26：结存 == 流水累计（recalc） | `smoke_m3` | PASS |
| T-V2-34：`below_safety` 预警筛选与看板预警 | `smoke_m3` / `test_v2_dashboard` | PASS |
| AC-V2-32 同构：合同关联单据汇总包含销售订单金额且合同金额不变 | `smoke_m3` | PASS |

## 4. 本轮修复的缺陷

| # | 问题 | 影响 | 修复 |
|---|---|---|---|
| 1 | 过账只回写采购侧 `received_qty` | 销售订单 `shipped_qty` 恒为 0，出库数量不可见 | 过账/红冲同时调用采购与销售回写（各自按来源类型判断） |
| 2 | 导出/打印端点若定义在 `/{doc_id}` 之后 | 静态路径会被路径参数捕获 → 422/404 | 打印与导出端点注册顺序提前（工厂内 `export.xlsx` 在 `{doc_id}` 之前） |
| 3 | 盘点单无行项时 `sum()` 初值为 int | 列表/详情 500（`'int' has no attribute 'quantize'`） | `total_amount_of` 初值改 `Decimal("0")` |
| 4 | 组织下拉缺失 | 采购申请/采购单/销售申请/销售订单的部门字段只能手填 ID，详情只显示 ID | 后端新增 `/api/master/options/org`（登录即可），前端四个表单改为可搜索下拉、四个详情抽屉显示部门/仓库/供应商**名称** |

## 5. 未覆盖项

| # | 项 | 说明 |
|---|---|---|
| 1 | 浏览器目视与 UAT | 本轮 DSH 浏览器自动化组件不可用；已提供 `17-uat-plan.md` 逐条场景清单，需业务用户执行 |
| 2 | 多页打印/批量打印 | 当前为单据级 A4 打印（单张），批量打印未纳入范围 |
| 3 | 单据打印模板自定义 | 固定模板（表头/行项/合计/签字栏），如需自定义模板登记为变更 |

## 6. 下一步（进入 M4 收尾）

1. 人工执行 `17-uat-plan.md`（三类用户 × 场景清单），填写异议与签字页；
2. UAT 通过后按 §9.6 打 tag：`v2.0-m1` / `v2.0-m2` / `v2.0-m3`（已打）→ `v2.0`；
3. 发布物：单容器 Docker 镜像（`10-docker-single.md`）或 Windows 原生部署（`08-deployment.md`）；
   升级步骤与回滚方案见 `19-go-live-checklist.md`。

### 6.1 M4 完成情况（本轮）

| 任务 | 状态 |
|---|---|
| T-V2-37 单据 A4 打印 | ✅ 后端 `GET {prefix}/{id}/print` + 前端打印入口（blob 打开） |
| T-V2-38 首页看板重规划 | ✅ 后端待办/库存预警/合同概览 + 前端展示 |
| T-V2-39 权限矩阵复核 | ✅ `audit_role_matrix.py`（8 角色 × 26 接口全部一致，记录见 `16-permission-matrix.md`） |
| T-V2-40 备份恢复演练 | ✅ `drill_backup_restore.py` 实测通过（记录见 `15-backup-drill.md`） |
| T-V2-41 UAT | ⏳ 计划与演示数据已就绪（`17-uat-plan.md` + `seed_demo_v2.py`）；**执行需业务用户**签字 |
| T-V2-42 文档更新 | ✅ `11`/`12` 冻结、`04` 补 V2.0 修订、README 与 `03` 同步；新增 `15`~`19` 六份运维/验收文档 |
