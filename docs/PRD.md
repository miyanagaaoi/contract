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

### CR-015 浏览器桥插件适配 DSH 0.2.1-rc.2

- **问题**：`@yuxianglin/dsh-bridge-browser@0.0.7` 的 peerDependencies 精确锁定 `0.2.0-rc.2`，
  宿主升级到 `0.2.1-rc.2` 后 peer 校验失败 → bundle 被跳过：`/ext/bridge-config` 返回 404、
  工具集无 `browser_*`（2026-10-24 实测；此前在 0.2.0-rc.2 下可正常读取税局页面）。
- **规则**：不改插件业务代码，仅将本地清单（`~/.dsh/profiles/desktop/.dsh-browser-source/package.json`，
  即 `~/.dsh/dsh-browser/packages/browser/bridge-browser`）中 13 处 `0.2.0-rc.2` 改为 `0.2.1-rc.2`；
  修改前备份 `package.json.bak-<时间戳>`。上游仍为 0.0.7，待其正式适配后可回退为上游版本。
- **状态**：实现中（已改清单，待重启 DSH 桌面验证 `/ext/bridge-config` 与 `browser_*` 工具）
- **证据**：插件清单 peer 版本；验证记录见本条备注及 README「已知问题」。
- **关联**：TODO-001（容器内无头验证码限制与此插件无关，勿混用）

### CR-016 启动脚本健壮性修复

- **问题**（2026-10-24 检查发现）：
  `setup.bat` 结尾提示仍是 5173（实际单进程 8000）、不装 Playwright Chromium、默认灌演示数据、pip 无镜像、不检查 Node；
  `start-all.bat` 用 `timeout /t`（非交互环境报错）、端口占用只判断 LISTEN 不校验是否 CTMS、前端源码更新后不会重建；
  `restart-backend.bat` 路径未规范化、kill 失败无提示；缺 `stop-backend.bat`。
- **规则**：
  1. `setup.bat`：检查 python/node → venv → pip（清华源，可用 `PIP_INDEX_URL` 覆盖）→
     `playwright install chromium`（npmmirror，失败仅告警不中断）→ 建库（**默认不带演示数据**，`setup.bat demo` 才灌）→ 提示 `:8000`；
     另支持 `setup.bat check` 只做前置检查。
  2. `start-all.bat`：等待改 `ping`；8000 被占用时用 `/api/health` 校验是否为 CTMS，非 CTMS 则明确报错退出；
     新增 `--rebuild` 强制重建前端、`--no-open` 不自动开浏览器。
  3. `restart-backend.bat`：`pushd` 规范化路径；kill 后轮询确认端口释放；健康检查重试至多 30 秒。
  4. 新增 `stop-backend.bat`：按端口停后端并确认端口已释放。
- **状态**：已实现（2026-10-24）
- **证据**：`setup.bat`、`start-all.bat`、`scripts/restart-backend.bat`、`scripts/stop-backend.bat`；
  实测 7 项——setup check 全绿；空端口 stop 提示 nothing；start-all 首次启动 health OK；
  已运行时 start-all 正确 `[skip]`；restart 识别 CTMS 后停/起/health OK；stop 释放端口；
  **非 CTMS 占用 8000 时 stop/restart 拒绝执行**（需 `--force`）
- **备注**：`.bat` 内含中文会导致 cmd 解析异常（实测），脚本一律**纯 ASCII**，说明放文档

### CR-017 批次配对报表剩余口径修复 + 演示数据脚本

- **问题**（2026-10-24 用演示数据验收 CR-011 时发现）：
  部分消耗的入库批次会同时产生「出库行（带剩余快照）」和「未消耗行（同剩余）」→
  报表"剩余"合计重复计算（演示数据下应为 70，实际算出 150）；且缺一套可重复的演示数据。
- **规则**：
  1. 出库行的 `库存数量/库存金额` 一律留空，剩余只由**未消耗批次行**体现
     （每批次最多一行剩余），保证「剩余合计 == 库存结存」；
  2. 新增 `app/tools/seed_stock_demo.py`：造真实过账的演示数据
     （仓库 演示仓-DEMO、物料 DEMO26-A/B、入库 3+1 批、出库 4 单，含领用出库+领用人+出库项目），
     支持 `--report` 打印报表、`--purge` 清理；
  3. 新增回归测试 `app/tests/test_v2_6_3_batch_report.py`（行拆分、剩余合计、与结存交叉验证）。
- **状态**：已实现（2026-10-24）
- **证据**：`app/services/stock_report_service.py`、`app/tools/seed_stock_demo.py`、
  `app/tests/test_v2_6_3_batch_report.py`；演示数据 7 行、剩余 70 / 金额 1040 与库存结存一致

### CR-018 批次报表：红冲单独标记 + 无批次出库单独区域

- **问题**（2026-10-24 验收 CR-011/CR-017 提出）：当前报表把所有流水按正负号机械处理——
  ① 反审核产生的「红冲-*」流水被当作正常入库/出库参与 FIFO，看不出这是红冲；
  ② 负库存/期初缺失导致的「出库无入库批次」行混在正常配对行里，不易识别。
- **规则**：
  1. 每行增加 `row_kind`：`normal`（正常配对）/ `reversal`（红冲）/ `orphan`（无入库批次出库）；
  2. **红冲**：`biz_type` 以「红冲-」开头的流水单独成行并标记——红冲入库（冲减）回减原批次剩余，
     红冲出库（恢复）按该出库单的消耗记录 LIFO 归还批次；红冲行不计入正常出库量统计；
  3. **无批次出库**：入库列为空的行统一归入 `orphan`，不再混在正常行；
  4. 接口返回 `summary`（三类行数与金额）；列表弹窗把正常行作为主表，
     红冲、无批次行分别在下方「异常区」单独成表；导出增加「行类型」列。
- **状态**：已实现（2026-10-24）
- **证据**：`app/services/stock_report_service.py`（`row_kind` + 红冲归还入队修复）、
  `app/routers/stock.py`（`summary` 与 `row_kind` 过滤、导出「行类型」列）、
  `web/src/views/stock/BalanceView.vue`（统计标签 + 红冲/无批次两个独立异常区）、
  `app/tests/test_v2_6_3_batch_report.py`（异常行拆分与导出标签 2 条用例；全量 523 passed）；
  演示数据：`seed_stock_demo --abnormal` → normal 8 / reversal 1 / orphan 1

### CR-019 演示数据重置：10 条入库批次样例

- **问题**（2026-10-24 业务要求）：演示数据需要清空重建，并要求"新增 10 条"，
  用于验收批次配对报表的三类行（正常/红冲/无批次）。
- **规则**：
  1. 清理范围 = 脚本生成的**演示数据**（`DEMO26*`/`DEMO27*` 前缀的仓库、物料、单据、流水、结存），
     **不触碰**真实业务数据与 `init_db --demo` 的历史演示数据（如实说明，需另行确认才清）；
  2. 新增 `app/tools/seed_stock_demo10.py`：3 个物料 × **10 个入库批次** + 4 张出库单
     （含跨批次 FIFO、领用出库）+ 1 张红冲（反审核）+ 1 条无批次出库流水；
  3. `seed_stock_demo.purge(prefix)` 支持按前缀清理；默认仍为 `DEMO26`（测试不受影响）。
- **状态**：已实现（2026-10-24）
- **证据**：执行结果——清旧 26 数据集（4 入库/4 出库/10 流水/3 物料…）；
  新数据集 `DEMO27`：**10 批次**、报表 **17 行**（正常 15 / 红冲 1 / 无批次 1），
  剩余合计 240（P1 30@13 + P2 40@21 与 50@22 + P3 120@30/31/32），金额 6,050；
  全量测试 523 passed

### CR-020 开发库业务数据全量清空

- **问题**：开发库残留历史演示数据（`init_db --demo` 的合同/采购等 55 份合同、53 张入库单），
  与 CR-019 的新演示数据混在一起；业务方确认"开发环境无真实数据"，要求全部清除。
- **规则**：
  1. 新增 `app/tools/purge_business_data.py`：清空**全部业务表**
     （合同/采购/销售/库存/财务/附件/变更日志/通知/操作日志/标签），
     可选 `--keep-master` 保留主数据；**保留**账号、角色、权限、组织、字典与系统设置；
  2. 执行前自动备份 SQLite 到 `app/backups/`；
  3. 逐表独立事务 + `PRAGMA temp_store=MEMORY`（大事务在 SQLite 上会报
     `unable to open database file`，已实测）；
  4. 清空后重建 CR-019 的 10 批次演示数据。
- **状态**：已实现（2026-10-24）
- **证据**：清理前备份 `app/backups/ctms_before_purge_20261024_1646*.db`（1.9MB）；
  删除合同 55/合同行项/采购 39/入库 53/出库 6/流水 60/结存 7/供应商 4/仓库 7/单位 9/标签 8 等；
  清理后业务表全 0、账号 14/角色 9 保留；重建 DEMO27：10 批次、报表 17 行（15/1/1）、
  剩余 240 / 金额 6,050；全量 523 passed；`/api/health` 正常

### CR-021 物料树形选择统一应用到全部行项

- **问题**（2026-10-24 业务要求）："新增合同"的行项物料已是树形展开 + 悬停档案信息，
  但其它单据（采购申请/采购单、销售申请/销售订单、入库/出库单、盘点、调拨）仍是平铺下拉，
  交互不一致。
- **规则**：
  1. 抽出公共组件 `web/src/components/doc/ProductTreeSelect.vue`：
     商品类型分组树（组节点不可选）、悬停显示编码/名称/规格/单位/默认单价/类型、
     本地过滤 + 输入 ≥2 字按关键词远程补拉（后端 options 默认 50 条）、支持 `multiple` 多选；
  2. **单据行项**（`DocItemsTable`，被采购/销售/出入库/盘点/调拨全部复用）改用该组件，
     `change` 事件回传完整物料对象，保留"快速新增物料 ＋"按钮；
  3. **合同行项**改用同一组件，删除合同页私有实现（`productTree`/`productTip`/`ensureProducts`）；
  4. **盘点单**「指定物料（多选）」改为树形多选。
- **状态**：已实现（2026-10-24）
- **证据**：新增 `ProductTreeSelect.vue`；`DocItemsTable.vue`、`ContractsView.vue`、
  `stock/TakeForm.vue` 已接入；`vite build` 通过（无类型/模板错误）

### CR-022 出库单「更多 → 退库」

- **问题**（2026-10-24 业务要求）：出库后发生退货/退料时，目前只能手工新建入库单，
  容易漏记来源、数量对不上。
- **规则（提议稿，待确认）**：
  1. 入口：出库单列表「更多」新增「退库」，仅 **已审核（approved）** 出库单可见可用；
  2. 交互：弹窗按行项展示「已出库 / 已退 / 可退」，可勾选行并填退库数量（≤可退数量），
     支持整单全退；
  3. 落库：生成一张 **入库单**（`in_type=退库入库`，`source_doc_type=stock_out`、
     `source_doc_id/no` 指向原出库单），行项与原出库行关联（`src_item_id`），审核后正常过账；
  4. 防超退：累计已退数量回写/汇总自来源单据，超退在前端与后端双重拦截；
  5. 打印/导出沿用入库单模板，表头显示「退库入库」与来源单号。
- **状态**：已实现（2026-10-24）
- **口径确认**：支持部分行/部分数量退；落库方式=生成新「退库入库单」；仅已审核出库单可退。
- **证据**：`GET /api/stock/out-orders/{id}/return-preview`（已出/已退/可退）、
  `POST /api/stock/out-orders/{id}/return`（校验可退量、生成草稿退库入库单，来源与行关联）；
  `web/src/components/stock/StockReturnDialog.vue` + `stock/OutList.vue`（更多→退库）；
  `IN_TYPES` 增加「退库入库」；测试 `app/tests/test_v2_6_4_stock_return.py`（部分退/防超退/未审核拦截/审核后加库存），
  全量 **525 passed**；演示数据 DEMO27 端到端生成 `IN202610000001`（类型/来源/行关联均正确）

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
| 2026-10-24 | 桥插件 peer 版本适配宿主 0.2.1-rc.2 | CR-015 | 本地插件清单 13 处 peer 由 `0.2.0-rc.2` 改为 `0.2.1-rc.2`；重启后 `/ext/bridge-config` 已返回 wsUrl、`browser_*` 工具已注册（扩展侧待填新端口） |
| 2026-10-24 | 出库单「更多 → 退库」 | CR-022 | 弹窗选行+数量（部分退），生成草稿「退库入库单」并关联来源出库单与行；草稿计入已退防超退；新增类型「退库入库」；525 passed |
| 2026-10-24 | 物料树选择统一到全部行项 | CR-021 | 抽公共组件 ProductTreeSelect（树展开+悬停信息+远程补拉+多选）；单据行项/合同行项/盘点多选全部接入；前端构建通过 |
| 2026-10-24 | 开发库业务数据全量清空 | CR-020 | 新增 purge_business_data（备份→清空业务表，保留账号/角色/字典）；重建 DEMO27 10 批次；523 passed |
| 2026-10-24 | 演示数据重置为 10 批次 | CR-019 | 清空 DEMO26 演示数据；新增 seed_stock_demo10（10 入库批次+4 出库+红冲+无批次）；报表 17 行、剩余 240/6050 |
| 2026-10-24 | 批次报表异常行拆分 | CR-018 | 新增 `row_kind`（正常/红冲/无批次）；红冲行单独标记并归还批次剩余（修复"已耗尽批次归还后丢失"缺陷）；无批次出库单列；前端两个异常区；523 passed |
| 2026-10-24 | 批次报表剩余口径修复 + 演示数据 | CR-017 | 出库行不再带剩余快照（避免重复计数）；新增 seed_stock_demo（含 --report/--purge）与 2 条回归测试；全量 521 passed |
| 2026-10-24 | 启动脚本健壮性修复 | CR-016 | setup 不灌演示数据/装 Chromium/检查 node；start-all 端口身份校验+`--rebuild`+`--no-open`；restart/stop 只在确认是 CTMS 时才杀进程；新增 stop-backend.bat |
