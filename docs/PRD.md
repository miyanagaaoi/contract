# PRD · 现行需求与变更登记（唯一真源）

> 本文件是 CTMS **现行需求、口径与变更状态**的唯一记录处。
> 历史规格（各版本当时的 PRD/设计/验收）已冻结，见文末「历史版本索引」。
> 新想法一律先进 [TODO.md](../TODO.md)；决定要做 → 在此新建 `CR-xxx` 条目；
> **只有状态变成「已确认」且经用户确认后，才开始写代码**。

## 状态图例（仅这 6 个取值）

| 状态 | 含义 |
|---|---|
| 提议 | 已登记、待业务方确认口径（**不得写代码**） |
| 已确认 | 口径已定，可以开工 |
| 实现中 | 正在开发 |
| 已实现 | 代码 + 测试 + 构建已完成，证据可查 |
| 搁置 | 决定暂不做（结论写到 TODO 或链接说明） |
| 取消 | 明确不做，不再跟踪 |

## 变更条目

<!-- 编号规则：CR-001 起顺序递增；不复用、不重排、不跳号。 -->

### CR-001 发票从电子发票服务平台同步

- **问题**：进项发票手工登记效率低、易错，且与税局平台数据不一致。
- **规则**：两条通道——
  ① **桥接**（开发/办公机）：读已登录的税局查询页 → `POST /api/finance/invoices/import-rows` 入库；
  ② **Playwright**（服务器，需 sync 镜像）：自动登录 + 抓取，验证码由人工在可见窗口完成。
  同步入库口径：`auth_status=已认证`、`bind_status=未确认`、`sync_source=tax_platform`；
  多公司按**我方主体码**预充凭据（`CTMS_TAX_SYNC_<主体码>_*`）；登录会话按主体码隔离、保活 1 小时。
- **状态**：已实现（V2.6.0）
- **证据**：`app/services/tax_sync_service.py`、`app/routers/finance.py`；[38-v2.6-invoice-sync-plan.md](38-v2.6-invoice-sync-plan.md) §4/§7；
  测试 `app/tests/test_v2_6_invoice_sync.py`。
- **关联**：TODO-001（无头浏览器无法人工过验证码）

### CR-002 发票包导入（解压 + 挂原始 PDF）

- **问题**：税局「下载→全部下载」得到发票包，手工归档成本高。
- **规则**：上传 zip → 解压 → 按文件名中 20 位数电票号匹配系统发票 → 原文件存
  `uploads/invoices/` 并挂为发票附件（`object_type=invoice`）；一票多格式只挂第一个；
  文件名无票号时从 XML 文本兜底匹配；未匹配文件在结果中列出。
- **状态**：已实现（V2.6.0）
- **证据**：`tax_sync_service.import_package`、`POST /api/finance/invoices/import-package`；
  附件类型白名单 `app/routers/attachments.py: OBJECT_PERMS["invoice"]`。

### CR-003 采购单绑定进项发票（多选弹窗）

- **问题**：原「更多→登记进项发票」跳转表单手工录票，无法用已同步发票核对。
- **规则**：弹窗默认筛「未确认」进项票，可多选；确认后写核销明细 → `bind_status=已确认`
  → 复用 V2.5 记账逻辑回写采购单 `invoiced_amount`；**收票进度按发票价税合计累计**；
  未审核/未完成的采购单不可绑定；解绑回到未确认并重算进度。红字票不可绑定。
- **状态**：已实现（V2.6.0）
- **证据**：`finance_service.bind_invoices / unbind_invoice`、`web/src/components/finance/InvoiceBindDialog.vue`。

### CR-004 红字/已冲红发票标记

- **问题**：查询结果中负数红字票与「已冲红-全额」票若混入进度，会把收票进度算错。
- **规则**：平台状态含「冲红」或价税合计 < 0 → `is_red=True`，**照常入库并标记**（列表中红色「红冲」标签），
  但**不参与收票进度绑定**（绑定接口拒绝）；已冲红票同样按此口径处理。
- **状态**：已实现（V2.6.0）
- **证据**：`Invoice.is_red`（模型 + 幂等迁移）、`tax_sync_service.normalize_row`、`finance_service.bind_invoices`。

### CR-005 发票列表改造（筛选与排序）

- **问题**：发票列表缺票种/收票单位/文件状态筛选；日期口径与排序不符业务习惯。
- **规则**：列口径 = 开票日期（默认倒序，可切升序/录入顺序）、收票单位（我方）、开票单位（对方）、
  税率（税额÷金额换算）、税额在前金额在后、认证/确认/文件三徽标；筛选项 = 方向、票种、认证、确认、原始文件（已下载/未上载）、
  收票单位（同时匹配 `subject_code` 与 `our_company_code`）。
- **状态**：已实现（V2.6.0）
- **证据**：`GET /api/finance/invoices`（`sort/invoice_type/bind_status/has_file/is_red/subject_code`）、`web/src/views/finance/InvoiceList.vue`。

### CR-006 打印发票（单个 / 批量）

- **问题**：发票需要按税局原始版式打印归档；不得自制仿发票版式。
- **规则**：**只打印发票包中的原始 PDF**（不做仿制版式）；详情/「更多」提供「打印发票」，
  未挂原始文件时提示先上传发票包；列表勾选后「批量打印」由服务端用 pypdf 合并为一个 PDF。
  因直链不带登录态，前端统一用带 token 的 blob 下载后打开。
- **状态**：已实现（V2.6.0）
- **证据**：`GET /api/finance/invoices/{id}/files`、`GET /api/finance/invoices/print-package`、
  `web/src/api.ts: downloadWithAuth / printInvoicePackages`。

### CR-007 分包 Docker 交付（核心包 + 浏览器底座）

- **问题**：整包 1.4GB+，每次更新都要重传 Chromium。
- **规则**：三层——`ctms-browser:1`（Chromium+字体，固定，一次性）、`ctms:<版本>`（业务核心，~71MB gz）、
  `ctms:<版本>-sync`（服务器本地 `FROM ctms-browser:1` + 从核心镜像 COPY，**离线秒级组装**，不再传输 Chromium）。
  另提供全量同步包作退路；镜像与发布包不入 git。
- **状态**：已实现（V2.6.0）
- **证据**：`deploy/Dockerfile.browser`、`deploy/Dockerfile.sync-local`、`deploy/docker-compose*.yml`；
  [39-v2.6-deploy.md](39-v2.6-deploy.md) §4.1。
- **关联**：TODO-003（群晖等面板只能导镜像，不能从 Git build）

### CR-008 合同行项物料树形选择 + 悬停信息

- **问题**：合同行项物料为平铺下拉，物料多时难选。
- **规则**：树形选择（**商品类型 → 物料**），支持搜索；悬停显示档案信息
  （编码/名称/规格/单位/默认单价/类型）；选中后自动带出名称、规格、单位、默认单价（用户可改）。
- **状态**：已实现（V2.6.1）
- **证据**：`web/src/views/ContractsView.vue`（`productTree` / `productTip`）。

### CR-009 采购单详情 `#` 复制整表

- **问题**：行项需要贴到 Excel 做二次核对，手工复制易错。
- **规则**：行项表头 `#` 可点击 → 复制整表为 TSV（序号/物料编码/名称/规格/单位/数量/单价/金额/仓库/备注），
  空行跳过；剪贴板不可用时降级 `execCommand('copy')`。
- **状态**：已实现（V2.6.1）
- **证据**：`web/src/components/doc/DocItemsTable.vue: copyItemsTable`。

### CR-010 出入库打印两个「部门负责人」分开选人

- **问题**：签字栏两个「部门负责人」共用一个选择，无法分别指定。
- **规则**：打印文字**保持「部门负责人」不变**；内部键 `部门负责人#1 / #2` 各自独立选人，
  `#1` 按组织架构自动带出单据所属部门负责人，`#2` 手选。
- **状态**：已实现（V2.6.1）
- **证据**：`print_template_service.STOCK_SIGN_LABELS` / `display_sign_label`、`print_service._render_sign`、
  `web/src/components/doc/PrintSignDialog.vue`；测试 `app/tests/test_v2_7_print_signers.py`。

### CR-011 库存批次配对报表（入出 FIFO）

- **问题**：需要"入库批次 → 出库配对"的明细表用于成本/追溯，现有流水列表无法直接看。
- **规则**：按 (仓库, 物料) 回放流水，入库批次 FIFO 消耗出库；输出 19 列：
  仓库/入库单号/入库时间/资产编号(=物料编码)/物料名称/规格/单位/数量/单价/金额/
  出库单号/出库时间/出库数量/出库金额/出库类型/出库项目(=出库单备注)/领用方(=出库单领用人)/库存数量/库存金额；
  未消耗批次单列一行（出库列为空）；库存金额 = 剩余数量 × 批次入库单价（系统只记数量不记成本，此为批次价近似）；
  支持 Excel 导出。
- **状态**：已实现（V2.6.1）
- **证据**：`app/services/stock_report_service.py`、`GET /api/stock/batch-report(.xlsx)`、`web/src/views/stock/BalanceView.vue`。

### CR-012 出库单新增「领用人」

- **问题**：领用出库没有领用人归属，报表无法统计。
- **规则**：`issue_party_type`（user/customer）+ `issue_party_id` + `issue_party_name` 快照；
  下拉 = 系统启用账号 + 客户档案（分组）；后端校验存在性；批次报表「领用方」取该字段。
- **状态**：已实现（V2.6.1）
- **证据**：`models_doc.StockOutOrder`、`db_migrate` 三列、`GET /api/stock/issue-options`、`web/src/views/stock/OutForm.vue`。

### CR-013 库存明细显示零结存

- **问题**：结存为 0 的物料（曾入库后出完）在列表中被隐藏，无法核对。
- **规则**：列表/导出均支持 `include_zero`；页面提供「显示零库存」开关，默认关闭（保持原行为）。
- **状态**：已实现（V2.6.1）
- **证据**：`GET /api/stock/balances`、`web/src/views/stock/BalanceView.vue`。

### CR-014 手写签名手机端全屏书写

- **问题**：手机屏幕小，画板区域过窄，签名体验差。
- **规则**：画板提供「全屏书写」——覆盖整屏（fixed）、按视口重算画布尺寸并**保留已有笔迹**，
  退出恢复默认 400×160；触摸事件 `preventDefault` 防页面滚动。
- **状态**：已实现（V2.6.1）
- **证据**：`web/src/components/SignaturePad.vue`（`enterFullscreen / resizeCanvas`）。

## 历史版本索引（已冻结，仅溯源，不再更新）

| 版本 | 规格 / 验收文档 | 说明 |
|---|---|---|
| V1.0 | [01-requirements.md](01-requirements.md)、[02-system-design.md](02-system-design.md)、[05-prototype-acceptance.md](05-prototype-acceptance.md) | 合同台账原型与首版 |
| V2.0 | [11-erp-requirements.md](11-erp-requirements.md)、[12-erp-system-design.md](12-erp-system-design.md)、[13](13-m1-acceptance.md)/[14](14-m2-acceptance.md)/[18](18-m3-acceptance.md)/[20](20-v2-acceptance-summary.md) | ERP 进销存（权限/采购/销售/库存/盘点/打印） |
| V2.1~V2.3 | [21](21-v2.1-upgrade-doc-plan.md)~[26](26-v2.3-adjustments.md) | 行项绑定物料、多公司维度、PG 迁移 |
| V2.4 | [27-feishu-integration-plan.md](27-feishu-integration-plan.md) | 飞书免登/推送 |
| V2.5 | [28](28-v2.5-finance-module-plan.md)~[37](37-release-v2.5.2.md) | 财务模块（付款/收款/发票 + 六条进度列）、打印模板、签字栏 |
| V2.6 | [38-v2.6-invoice-sync-plan.md](38-v2.6-invoice-sync-plan.md)、[39-v2.6-deploy.md](39-v2.6-deploy.md) | 发票同步与分包部署（本 PRD 的 CR-001~007） |

## 变更记录

> 收尾规矩：每次开发完成后**必须在此追加一行**（与 PRD 条目状态更新同一次提交）。

| 日期 | 事项 | 涉及条目 | 说明 |
|---|---|---|---|
| 2026-10-20 | 建立开发文档体系 | — | PRD/TODO/AGENTS/CLAUDE 首次落地；回填 V2.6.0（CR-001~007）与 V2.6.1（CR-008~014），状态均「已实现」 |
