# 14. V2.0 · M2 验收报告（采购线与库存过账）

> 验收对象：`docs/03-development-plan.md` §9.3 **M2 采购线与库存过账**（T-V2-17 ~ T-V2-28），
> 并含 M3 的销售线（T-V2-29~31）与盘点（T-V2-32）后端。
> 验收依据：`docs/11-erp-requirements.md` §16 **AC-V2-13 ~ AC-V2-26**（含 27~29 盘点、31~32 合同互动、40 附件）。

## 1. 结论

| 项 | 结果 |
|---|---|
| 后端（T-V2-17~23、T-V2-26、T-V2-27） | **完成** |
| 销售线后端（T-V2-29~31）与盘点后端（T-V2-32） | **完成**（提前于 M3 排期） |
| 自动化测试 | `pytest app/tests -q` → **232 passed** |
| M2 端到端冒烟 | `python app/tests/smoke_m2.py` → **11/11 PASS** |
| M1 回归 | `smoke_m1.py` → **15/15 PASS** |
| V1.0 合同模块回归 | `smoke_p0.py` → **13/13 PASS** |
| 前端（T-V2-24/25：通用单据组件 + 采购三单据页面 + 库存明细页） | 见 §5（本轮交付，构建验证见提交记录） |
| 服务健康 | `GET /api/health` → `{"status":"ok","db":true}` |

**判定：M2 后端达到可上线条件**（关键风险 T-V2-19 过账服务已闭环）。

## 2. 交付物

### 2.1 数据模型

| 文件 | 内容 |
|---|---|
| `app/models_doc.py` | `DocMixin` / `DocItemMixin` + 7 类单据主表与行项表（采购申请/采购单/销售申请/销售订单/入库/出库/盘点）；状态常量 `DOC_STATUS`；下推数量列 `ordered_qty`/`received_qty`/`shipped_qty`；盘点差异列 `book_qty`/`actual_qty`/`diff_qty` |
| `app/models_stock.py` | `Stock`（结存，物料×仓库唯一）/ `StockLedger`（流水，只增不改，`qty_after` 快照） |
| `app/db_migrate.py` | 抽出 `_relax_nullable_column`：`change_logs.contract_id`、`attachments.contract_id` 由 NOT NULL 放开为可空（SQLite 表重建，历史数据保留、幂等） |

### 2.2 服务层

| 文件 | 职责 |
|---|---|
| `app/services/doc_service.py` | 状态机（草稿→待审核→已审核→已完成/已作废）、行项快照与金额、**单位小数位校验**（AC-V2-11）、变更历史、列表通用筛选（作废默认不进列表，AC-V2-17）、关联合同与往来单位校验 |
| `app/services/posting_service.py` | **审核即过账**（AC-V2-19/20）、幂等（AC-V2-23）、负库存拦截（AC-V2-21，拦截时状态与库存均不变）、反审核红冲（AC-V2-22）、盘点差异生成盘盈/盘亏单并过账（AC-V2-28/29，盘亏豁免负库存校验）、`recalc_stocks` 一致性校验（AC-V2-26） |
| `app/services/push_service.py` | 下推链（申请→采购单/销售订单→出入库）、剩余可下推量校验（AC-V2-16）、下游存在时禁止反审核（AC-V2-24）、过账回写 `received_qty`/`shipped_qty`（AC-V2-18） |
| `app/services/numbering_service.py` | 7 类单据取号（前缀 + 年月 + 序号，跨月重置）；修复 `ref_date` 缺省与"前缀含数字导致序号膨胀"两个缺陷 |

### 2.3 接口

| 文件 | 端点 |
|---|---|
| `app/routers/doc_routes.py` | 单据路由工厂：列表/新增/详情/修改/提交/审核/驳回/完成/作废/反审核/变更历史（7 类共用） |
| `app/routers/purchase.py` | `/api/purchase/requests`、`/api/purchase/orders`、`.../{id}/push`、`/api/purchase/contract-options` |
| `app/routers/sales.py` | `/api/sales/requests`、`/api/sales/orders`、`.../{id}/push`、`/api/sales/contract-options` |
| `app/routers/stock.py` | `/api/stock/in-orders`、`/out-orders`、`/takes`（含 `generate` 生成行项、`count` 录入实盘）、`/balances`、`/ledger`、`/recalc` |
| `app/routers/contracts.py` | `GET /api/contracts/{id}/related-docs`（关联单据只读汇总，AC-V2-32） |
| `app/routers/attachments.py` | 通用附件：`/api/attachments/list`、`/upload`、`/{id}`（删除）、`/{id}/download`；按对象类型映射权限（T-V2-27） |

### 2.4 前端（T-V2-24/25）

`web/src/components/doc/`（DocStatusTag、DocItemsTable、DocListPage、DocFormPage、ApproveDialog、PushDialog、RelatedDocs）
与 `web/src/views/purchase/*`、`web/src/views/stock/{InList,InForm,BalanceView}.vue`，
路由与权限点见 `web/src/router/index.ts`；合同详情抽屉新增"关联单据"只读区块。

## 3. 验收场景执行记录

| AC | 场景 | 证据 | 结果 |
|---|---|---|---|
| AC-V2-13 | 采购申请提交与审核 | `smoke_m2` / `test_v2_docs` | PASS |
| AC-V2-14 | 驳回回草稿并记录原因 | `smoke_m2` | PASS |
| AC-V2-15 | 创建人不可自审 | `test_v2_docs::test_self_approve_rejected` | PASS |
| AC-V2-16 | 申请下推采购单（100→60，剩余 40；填 50 被拦截） | `smoke_m2` | PASS |
| AC-V2-17 | 作废留痕且默认不进列表 | `test_v2_docs` | PASS |
| AC-V2-18 | 入库后回写采购单已入库数量（40） | `smoke_m2` | PASS |
| AC-V2-19 | 入库审核增加库存 + 流水 | `smoke_m2` | PASS |
| AC-V2-20 | 出库审核减少库存（40→36） | `smoke_m2` | PASS |
| AC-V2-21 | 负库存拦截（库存与单据状态均不变） | `smoke_m2` / `test_v2_docs` | PASS |
| AC-V2-22 | 反审核红冲（追加负向流水，原流水保留） | `smoke_m2` | PASS |
| AC-V2-23 | 重复审核不产生第二条流水 | `smoke_m2` / `test_v2_docs` | PASS |
| AC-V2-24 | 有下游单据时禁止反审核 | `smoke_m2` / `test_v2_docs` | PASS |
| AC-V2-25 | 库存流水下钻（按物料+仓库倒序，含变动后结存） | `/api/stock/ledger` + 前端流水抽屉 | PASS |
| AC-V2-26 | 结存 == 流水累计（`/api/stock/recalc`） | `smoke_m2` | PASS |
| AC-V2-27 | 全盘按结存生成行项、账面只读 | `smoke_m2` / `test_v2_docs` | PASS |
| AC-V2-28 | 盘亏自动生成盘亏出库单并过账 | `smoke_m2`（生成 `OUT...`） | PASS |
| AC-V2-29 | 盘盈自动生成盘盈入库单 | `test_v2_docs` | PASS |
| AC-V2-30 | 抽盘（按指定物料/类型生成行） | `test_v2_docs` | PASS |
| AC-V2-31 | 单据关联合同（下拉仅同方向合同） | `/api/purchase/contract-options`、`/api/sales/contract-options` | PASS |
| AC-V2-32 | 合同详情关联单据**只读**汇总（不改合同金额） | `smoke_m2` / `test_v2_docs` | PASS |
| AC-V2-40（附件部分） | 单据附件上传/列表/下载/删除 + 权限边界 | `smoke_m2` / `test_v2_docs` | PASS |

> AC-V2-40 的"8 类单据导出 Excel"属 T-V2-35（M3）范围，本报告不含。

## 4. 本轮发现并修复的缺陷

| # | 问题 | 影响 | 修复 |
|---|---|---|---|
| 1 | 单据 `create_hook` 在 `flush()` 之后执行 | 必填字段（仓库/供应商）先以 NULL 插入 → NOT NULL 约束失败 | `doc_routes._new_doc` 调整顺序：先落特有字段再 flush |
| 2 | 行项类获取写成 `...mapper.class_()`（多调用一次） | `TypeError: 'XxxItem' object is not callable`，下推与盘点建单失败 | 改为 `...mapper.class_`（类属性），并加注释 |
| 3 | `total_amount_of` 的 `sum()` 初值为 int | 无行项单据（盘点单/空白申请）报 `'int' has no attribute 'quantize'` | 初值改为 `Decimal("0")` |
| 4 | `BusinessError` 继承 `Exception` | 负库存被当成 500 而非 422 | 改为继承 `ValueError`，由路由统一转 422 并回滚 |
| 5 | `next_doc_no(kind)` 默认 `ref_date=None` | 按月重置类别格式化 None → 500 | 缺省取 `date.today()` |
| 6 | 过账只回写采购侧 `received_qty` | 销售订单 `shipped_qty` 恒为 0 | 过账/红冲同时调用采购与销售回写（各自按来源类型判断） |
| 7 | 下推时未指定来源行 | 报"下推行项与来源单据不匹配" | 支持按顺序映射（允许"整单下推只传数量"） |
| 8 | `attachments`/`change_logs` 重建时索引名冲突 | 迁移直接失败 | 重建前先 `DROP INDEX`（SQLite 重命名表不重命名索引） |

## 5. 未覆盖项与风险

| # | 项 | 说明 | 处理 |
|---|---|---|---|
| 1 | 前端浏览器目视验收 | 本轮 DSH 浏览器自动化组件不可用（`bsk` 未安装）；以 `npm run build` 成功 + 页面进入产物作为替代证据 | 按 §6 清单人工点一遍 |
| 2 | 8 类单据导出 Excel | 属 T-V2-35（M3） | M3 执行 |
| 3 | 打印样式、首页看板重规划 | 属 T-V2-37/T-V2-38（M4） | M4 执行 |
| 4 | 大数据量下过账性能 | 单据行数预期 < 100 行；SQLite 写串行化 | 上线后观察，必要时批量 flush |

## 6. 人工验收清单（浏览器，约 15 分钟）

前置：`cd web; npm run build`，再以 `CTMS_SERVE_STATIC=1` 启动后端；登录 `admin/admin12345`。

- [ ] 资料库建好：供应商、客户、物料（含单位）、仓库
- [ ] 采购申请：录入 2 行物料 → 保存 → 提交 → 换账号审核（同一账号审核会被拒）
- [ ] 采购申请"下推采购单"：选供应商、改数量为剩余量的一半 → 生成采购单草稿
- [ ] 采购单：提交 → 审核 → "下推入库单"（选仓库）→ 入库单提交 → 审核
- [ ] 库存明细：确认结存数量与流水（点击行看流水下钻）
- [ ] 出库单：录入超过库存的数量 → 审核应提示"库存不足"且状态不变
- [ ] 入库单反审核：填写原因 → 结存回退 → 流水多出一条"红冲-采购入库"
- [ ] 盘点单：全盘 → 生成行项 → 改实盘数量 → 提交 → 审核 → 查看自动生成的盘盈/盘亏单号
- [ ] 合同详情：查看"关联单据"区块（金额汇总只读，合同金额不变）
- [ ] 单据附件：在入库单上上传 PDF → 列表可见 → 下载 → 删除

## 7. 下一步

1. 前端目视通过后打 tag `v2.0-m2`；
2. **M3 剩余**：销售三单据前端页面（T-V2-33）、安全库存预警筛选（T-V2-34）、8 类单据与库存导出（T-V2-35）、M3 验收（T-V2-36）；
3. **M4**：单据 A4 打印（T-V2-37）、首页看板按角色重规划（T-V2-38）、权限矩阵复核（T-V2-39）、
   备份恢复演练与部署手册（T-V2-40）、UAT（T-V2-41）、文档冻结（T-V2-42）。
