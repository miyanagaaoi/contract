# 业务视图层审查报告（只读审查，未修改任何代码）

范围：`web/src/views/ContractsView.vue`、`DashboardView.vue`、`master/*`（10 个）、`purchase|sales/{RequestForm,RequestList,OrderForm,OrderList}`（8 个）、`stock/*`（9 个）、`system/SystemView.vue`、`web/src/types/doc.ts`、`web/src/types/master.ts`。
标尺：`web-design-guidelines`（Vercel Web Interface Guidelines 钉版）+ `critique` 5 维框架。
说明：`purchase/sales/stock` 的列表页与表单页实际是配置壳，真实交互在 `web/src/components/doc/DocListPage.vue`、`DocFormPage.vue`、`DocItemsTable.vue`、`MasterTablePage.vue`、`TreeMasterPage.vue`（已在结论中一并取证并标注组件行号）。

全局复核结论（自行确认）：全 `web/src/**/*.vue` 中 `aria-label` / `aria-live` / `aria-hidden` / `prefers-reduced-motion` / `Intl.` / `transition: all` 命中数均为 **0**；全项目仅 **1 处** `@media`（`ContractsView.vue:1240`）；**0 个页面**把筛选状态写入 URL query；**0 个列表页**提供批量操作。

---

## 1. 逐文件合规问题清单

### web/src/views/ContractsView.vue（1260 行，问题最集中）
- ContractsView.vue:776 - 框架树折叠是 `<span @click.stop>`，非 `<button>`，无键盘处理、无 `aria-label`（`<div>/<span>` with click handlers / Interactive elements need keyboard handlers）
- ContractsView.vue:776 - 折叠三角用字符 `▸/▾` 表达展开态，无 `aria-expanded`（semantic HTML before ARIA）
- ContractsView.vue:750 - 「重置」不重置 `include_deleted`、不置 `page=1`，重置行为不完整（URL reflects state / 一致性）
- ContractsView.vue:754 - `el-checkbox` 使用 `label="显示已停用"` 作为值（Element Plus 2.6+ 已弃用 `label` 作 value 的写法，应用 `value`）
- ContractsView.vue:718,737 - 关键词/经办人输入框无 `name`、无 `autocomplete="off"`（Inputs need autocomplete and meaningful name）
- ContractsView.vue:765,949,1024,1043,1084,1109 - 布局用内联 `style="display:flex;..."` 而非类，与同文件 `.filter-bar` 的类化做法自相矛盾（Philosophy consistency / 设计令牌）
- ContractsView.vue:932,935,964,969,982,983,985 - 数字输入为 `el-input-number` 且无 `inputmode`，金额/数量列无 `font-variant-numeric: tabular-nums`（Use correct inputmode / tabular-nums for number columns）
- ContractsView.vue:808,811,937,1163 - 金额/已付列右对齐但未加等宽数字，长数字对不齐（tabular-nums）
- ContractsView.vue:656 - 金额用 `toLocaleString('zh-CN', { minimumFractionDigits: 2 })`，未约束 `maximumFractionDigits`，3 位小数会漏出（hardcoded number format）
- ContractsView.vue:651-653 - 日期用 `String(s).slice(0,10)` 手工截断，未用 `Intl.DateTimeFormat`（Dates: use Intl.DateTimeFormat）
- ContractsView.vue:1207 - 时间戳用 `(lg.created_at||'').slice(11,19)` 拼字符串（hardcoded date format）
- ContractsView.vue:213,215,262,295,297,412,448 - 中文枚举硬编码为前端默认值（`'采购'` / `'内部审批中'`），与后端字典重复（Locale & i18n / 单一真源）
- ContractsView.vue:956 - 金额硬编码 `￥` 前缀，而同页 `fmtMoney` 不带币种（一致性 / hardcoded format）
- ContractsView.vue:1116 - 标签色用行内 `style="color:#fff;border:none"`（硬编码颜色，无令牌）
- ContractsView.vue:1130,1015,849,1040,1064,1083,1108 - 抽屉/弹窗宽高写死 `640px/760px/1080px/720px/460px/520px`，无 `max-width`（窄屏适配）
- ContractsView.vue:1253,1254,1255,1256,1257,1258,1259 - 7 处硬编码颜色（`#909399 #606266 #f56c6c #409eff #c0c4cc #fafbfd #ecf5ff`），无设计令牌
- ContractsView.vue:1245,1251 - 12px 与 1253 的 13px 混用（字号无标尺）
- ContractsView.vue:1240 - 唯一的媒体查询，仅改筛选按钮组对齐；表格/弹窗/表单在窄屏无适配（Responsive）
- ContractsView.vue:773 - 行双击打开详情（`@row-dblclick`），可发现性差，且与 BalanceView.vue:297 的单击打开不一致（一致性）
- ContractsView.vue:836-844 - 分页 `layout="total, prev, pager, next"`，无 `sizes`（分页控件不一致）
- ContractsView.vue:772 - 主干表格未配 `#empty`，空结果只剩表头（Handle empty states）

### web/src/views/DashboardView.vue
- DashboardView.vue:260 - `el-alert` 加 `@click` + `cursor:pointer` 当按钮用，无键盘处理（`<div>` with click handlers）
- DashboardView.vue:85-87 - 日期手工 `slice(0,10)`（use Intl.DateTimeFormat）
- DashboardView.vue:91 - `toLocaleString('zh-CN', …)` 第 2 处重复实现（hardcoded number format）
- DashboardView.vue:153-155,195-200 - 金额数字无 `tabular-nums`，且与 269/276 的数字卡不同号不同宽（对齐/层级）
- DashboardView.vue:101,104,107,110,117,123,129,195-200 - `el-col :span` 全为固定值（6/8/4/5/3），无任何断点（无媒体查询，窄屏卡片被压到 <120px）
- DashboardView.vue:76 - `new Date().toISOString().slice(0,10)` 作为「今天」写入（时区/格式硬编码）
- DashboardView.vue:91 - 金额格式化与本文件 199 行 `overview.paid_ratio ?? '—'` 的比例展示口径不统一（数值展示一致性）
- DashboardView.vue:144,167,168,214,238 - 空态用 `el-empty`（弱），而列表页用 `template #empty` 文本（空态不统一）
- DashboardView.vue:268-276 - 6 处硬编码颜色（`#409eff #303133 #e6a23c #f56c6c #909399`）
- DashboardView.vue:269,276 - 28px 与 20px 两级「大数字」无统一令牌，`ovnum` 无 `font-variant-numeric`

### web/src/views/master/UserView.vue
- UserView.vue:254-256 - 分页 `v-if="total > pageSize"`（数据少于一页时分页消失，与其他页行为不一致）
- UserView.vue:183 - 关键词输入无 `name` / `autocomplete="off"`（Forms）
- UserView.vue:239-241 - `prop="last_login_at"` 直接渲染原始时间串，未走统一日期格式（Locale）
- UserView.vue:242 - 操作列 210px 内放 3 个链接按钮（含「重置密码」破坏性操作），信息密度过高
- UserView.vue:208 - 主干表格无 `#empty` 空态（Handle empty states）
- UserView.vue:271,312 - 密码输入框无 `autocomplete="new-password"`（Forms / password manager）
- UserView.vue:325-330 - 硬编码 `#909399`、字号 15/12.5px

### web/src/views/master/RoleView.vue
- RoleView.vue:182 - 表格无 `#empty` 空态
- RoleView.vue:169-180 - 筛选区只有「关键词 + 含停用」，无「重置」按钮（与 UserView/ContractsView 不一致）
- RoleView.vue:238-241 - 权限树容器 `max-height:320px` 固定，无「全选/展开/仅看已选」，权限点多时勾选效率低（功能/效率）
- RoleView.vue:256 - 硬编码 `#e4e7ed` 边框色 + `border-radius:4px`（令牌缺失）
- RoleView.vue:253-255 - 硬编码字号 15/12.5px

### web/src/views/master/ProductView.vue / CustomerView.vue / SupplierView.vue / WarehouseView.vue / UomView.vue
- ProductView.vue / CustomerView.vue / SupplierView.vue / WarehouseView.vue / UomView.vue - ✓ pass（页面本身仅声明列/字段，全部交互在 `MasterTablePage.vue`，缺陷见第 2、3 节共享组件条目）

### web/src/views/master/ProductTypeView.vue / OrgView.vue
- ProductTypeView.vue:10 / OrgView.vue:15 - 「上级id」字段暴露给用户且标签用「id」，是数据库字段名直出，非业务语言（Content & Copy）
- ProductTypeView.vue / OrgView.vue - ✓ pass（交互在 `TreeMasterPage.vue`）

### web/src/views/master/PartyDraftView.vue
- PartyDraftView.vue:145-179 - 表格无分页、无总数（草案量大时全量渲染），且无 `#empty` 之外的分页控件（Performance / 大列表）
- PartyDraftView.vue:138 - `el-radio-group @change="load"` 状态切到 URL 不可深链（URL reflects state）
- PartyDraftView.vue:97-100 - 忽略草案用 `ElMessageBox.prompt`，提示文案「可填写说明」与按钮「确定忽略」不构成一致动作语义（Copy）
- PartyDraftView.vue:220,223 - 硬编码 `#909399`、字号 12.5px

### web/src/views/purchase/RequestList.vue
- RequestList.vue:33-35 - 第 4 处 `slice(0,10)` 日期截断（Locale）
- RequestList.vue:43 - 未匹配到供应商时回退显示 `ID {id}`，把主键暴露给业务用户（Content Handling / Copy）
- RequestList.vue:56-63 - 列表能力标签写死（含作废/导出/分页等行为在共享壳内，页面无 URL 状态）
- RequestList.vue:59 - `show-supplier` 同时启用「供应商」列与筛选项，而该单专有字段是「建议供应商」（suggest_supplier_id），列标题会与实际语义错位（一致性）

### web/src/views/purchase/OrderList.vue
- OrderList.vue:27-31 - `fmtMoney` 第 5 处重复实现（hardcoded number format）
- OrderList.vue:33-35 - 第 6 处 `slice(0,10)`
- OrderList.vue:40-44 - 未匹配仓库时回退 `ID {id}`（Copy）
- OrderList.vue:60 - `:extra-cols="['received']"` 但本页采购单是「已入库」语义，与 `InList.vue:19` 同名同列重复展示（信息密度）
- OrderList.vue:56 - 无 `#empty` 自定义（由共享壳兜底）

### web/src/views/sales/OrderList.vue
- OrderList.vue:29-33 - `fmtMoney` 第 7 处重复实现
- OrderList.vue:35-37 - 第 8 处 `slice(0,10)`
- OrderList.vue:43-53 - 两个未匹配回退 `ID {id}`（Copy）
- OrderList.vue:78 - `detail.currency || 'CNY'` 兜底硬编码币种（hardcoded format）

### web/src/views/sales/RequestList.vue
- RequestList.vue:31-33 - 第 9 处 `slice(0,10)`
- RequestList.vue:38-42 - 未匹配部门回退 `ID {id}`（Copy）
- RequestList.vue:58 - 使用 `show-customer`，但列表壳 `partyOf()` 取 `customer_name || customer_name_text`；「客户（文本）」只在详情出现，列表无标识（一致性）

### web/src/views/purchase/RequestForm.vue
- RequestForm.vue:25-33,36-44,66-67 - 三个 `void ensureSuppliers()/ensureOrgs()` 立即调用 + 下拉 `@visible-change` 再次调用，同一份数据两条加载路径（Detail execution / 重复）
- RequestForm.vue:99-108 - 覆盖已有行项时的确认框是唯一防线，`items.splice(0, items.length)` 直接覆盖，无撤销（Destructive actions need confirmation or undo — 有确认，但无撤销窗口）
- RequestForm.vue:159-162 - 「建议供应商快照」用只读文本再占一列，等于把已选值重复显示一遍（信息密度）
- RequestForm.vue:194 - 硬编码 `#909399`、12.5px

### web/src/views/purchase/OrderForm.vue
- OrderForm.vue:26-27 - `SETTLE_TYPES` / `CURRENCIES` 硬编码在前端（Locale & i18n / 单一真源）
- OrderForm.vue:29-42 - 三个 `fetchMasterOptions` 各自 catch 后赋空数组，失败无任何提示（Error messages include fix/next step）
- OrderForm.vue:74-76 - 币种 `filterable allow-create`，可输入任意字符串，与主数据档案化方向冲突（一致性）
- OrderForm.vue:51 - 「供应商」标 `required` 但校验只在 `DocFormPage.extraRequired`（本页未传 `extra-required`，见 46-48 行），必填星号与真实校验点不一致（Errors inline / 一致性）

### web/src/views/sales/OrderForm.vue
- sales/OrderForm.vue:28 - `CURRENCIES` 第 2 处硬编码（与 purchase/OrderForm.vue:27 完全重复）
- sales/OrderForm.vue:30-42 - 同 OrderForm 的空 catch 静默降级
- sales/OrderForm.vue:86-89 - 币种 `allow-create` 同上
- sales/OrderForm.vue:69,74,102 - `maxlength` 有但无字数提示，`contact_phone` 未用 `type="tel"` / `inputmode="tel"`（Forms / Use correct type）

### web/src/views/sales/RequestForm.vue
- sales/RequestForm.vue:44-63 - 4 个 `computed` get/set 包装 `extra`（与 purchase/OrderForm.vue 直接 `v-model="extra.xxx"` 两种写法并存，同一套壳两种范式）
- sales/RequestForm.vue:72-90 - 「客户」「客户文本」「客户快照」三行展示同一信息（信息密度 / 视觉权重）
- sales/RequestForm.vue:110 - 硬编码 `#909399`、12.5px

### web/src/views/stock/InForm.vue / OutForm.vue
- InForm.vue:19 / OutForm.vue:19 - 入库/出库类型硬编码在前端（后端字典另有来源，Locale）
- InForm.vue:60 - 供应商下拉 `allow-create`（对数值字段启用自由输入，类型不一致风险）
- InForm.vue:26,29 / OutForm.vue:26,29 - `fetchMasterOptions` catch 后静默置空
- InForm.vue / OutForm.vue - `el-col :span="12"` 固定，窄屏不折行

### web/src/views/stock/InList.vue / OutList.vue / TransferList.vue / TakeList.vue
- InList.vue:7-9 / OutList.vue:7-9 / TransferList.vue:9-11 - 3 份完全相同的 `fmtDate`（`slice(0,10)`）逐页复制（重复 / Locale）
- InList.vue:23-25 / OutList.vue:23-25 / TransferList.vue:25-27 / TakeList.vue:22-24 - 四处「过账状态」`el-tag` 结构逐字节重复（应为共享组件，同 `DocStatusTag`）
- InList.vue:13-19 / OutList.vue:13-19 - 除 `api`/`title`/`perm-prefix` 外属性完全对称，属可参数化的重复
- TakeList.vue:7 - `TAKE_TYPE_LABEL` 本地映射枚举，同类映射在其他页不存在（枚举展示不统一）

### web/src/views/stock/TransferForm.vue
- TransferForm.vue:36-37,41,49 - 调出/调入仓库仅前端 `required` 星号，未传 `extra-required`，「不得相同」只有后端拦截，前端无即时提示（Errors inline next to fields）
- TransferForm.vue:38-59 - `:span="12"` 固定 + `:span="24"` 提示，窄屏不折行

### web/src/views/stock/TakeForm.vue
- TakeForm.vue:190,198 - 行内校验用 `ElMessage.warning`（弹窗式），非字段旁内联错误（Errors inline next to fields）
- TakeForm.vue:313-351 - 盘点录入表 `max-height="520"` 固定，无「差异行筛选/只看差异」开关（效率）
- TakeForm.vue:331-332 - 实盘录入 `el-input-number` 无 `inputmode`，无 Enter 跳下一行的键盘流（键盘流）
- TakeForm.vue:398-406 - 硬编码 `#67c23a #f56c6c #f0f9eb #fef0f0 #909399`
- TakeForm.vue:311-312 - 空态提示用 `el-alert`（与 BalanceView/TakeList 的 `#empty` 文本、Dashboard 的 `el-empty` 三种并存）

### web/src/views/stock/BalanceView.vue
- BalanceView.vue:269 - 内联 `style="margin:0 6px; color:#909399"` 分隔符（硬编码，令牌缺失）
- BalanceView.vue:297 - 整行 `@row-click` 打开抽屉，同时 333 行又有「流水下钻」按钮（同一动作两处入口，且行点击会与文本选择冲突）
- BalanceView.vue:428-432 - 5 处硬编码颜色；`:deep(.el-table__row){cursor:pointer}` 对全部行生效，语义仅对结存行成立
- BalanceView.vue:149 - `fmtMoney` 用 `toFixed(2)`（无千分位），与 ContractsView/DocListPage 的 `toLocaleString` 两套（货币展示不一致）
- BalanceView.vue:153 - 时间用 `slice(0,19)` 第 2 种截断长度（10/11-19/19 三种并存）
- BalanceView.vue:307,312,393,400 - 数量列右对齐但无 `tabular-nums`
- BalanceView.vue:282-292 - 「库存重算」结果用 `el-alert` 内嵌一段可滚动文本，`mismatch` 明细无表格/无导出（功能）

### web/src/views/system/SystemView.vue
- SystemView.vue:303-304,350-351 - 时间列直接绑定 `created_at` 原串渲染，未格式化（Locale / 展示一致性）
- SystemView.vue:242 - `el-table :data="Object.keys(rules)"` 用 key 数组当行数据，行内直接 `rules[row].prefix`，属反模式且无法排序（Detail execution）
- SystemView.vue:321,365 - 分页 `v-if="logTotal > logPageSize"` 且**缺 `background`**（462 行同类控件样式不统一）
- SystemView.vue:228 - `label-width="200px"` 固定，窄屏表单标签挤压输入（Responsive）
- SystemView.vue:311-317 - 操作日志「结果」只区分成功/失败，无错误原因列（Error messages include fix/next step）
- SystemView.vue:419-427 - 硬编码 `#909399` ×3、字号 15/12.5px

### web/src/types/doc.ts / web/src/types/master.ts
- types/doc.ts:99 - `[key: string]: unknown` 兜底索引签名使全部字段访问失去类型检查，是列渲染大量 `?? '—'` 的根因（类型/细节）
- types/doc.ts:226-230 - `ContractRelatedDoc.total_amount: number | null` 与列表 `total_amount: number`（61 行）口径不一致，调用方需各自兜底（一致性）
- types/doc.ts:188-201 - `StockLedgerRow.biz_type/doc_type` 为 `string | null` 无枚举约束，页面各自 `|| '—'`（枚举展示不统一）
- types/master.ts:34 - `kind` 仅支持 `money|tag|status|bool`，无 `date`/`qty` 种类，导致主数据列无法统一日期与数量格式化（令牌/一致性）
- types/master.ts - ✓ 其余 pass

---

## 2. 跨页面一致性矩阵

`是`=有；`否`=无；`—`=不适用。

| 页面 | 搜索 | 筛选(除关键词) | 分页 | 分页含 sizes | 批量操作 | 导出 | 空态 | URL 状态 |
|---|---|---|---|---|---|---|---|---|
| ContractsView.vue | 是(718) | 是(类型/状态/经办人/标签/日期/含停用) | 是(836) | 否 | 否 | 是(列可选+记忆) | 否(主干表无 #empty) | 否 |
| DashboardView.vue | 否 | 否 | 否 | — | 否 | 否 | 是(el-empty) | 否 |
| master/* (MasterTablePage.vue) | 是(255) | 是(状态/含停用/额外筛选) | 是(310) | 否 | 否 | 否 | 是(文本) | 否 |
| master/PartyDraftView.vue | 否 | 是(状态 radio, 138) | 否 | — | 否 | 否 | 是(文本) | 否 |
| master/UserView.vue | 是(183) | 是(组织/角色/状态) | 是(254) | 否 | 否 | 否 | 否 | 否 |
| master/RoleView.vue | 是(171) | 是(含停用) | 否 | — | 否 | 否 | 否 | 否 |
| master/Tree*Page.vue | 是(过滤框 196) | 否 | — | — | 否 | 否 | 是(el-empty) | 否 |
| purchase/sales 4×List (DocListPage.vue) | 是(393) | 是(状态/日期/仓库/往来/合同/含作废) | 是(494) | **是** | 否 | 是(统一入口) | 是(文本) | 否 |
| stock/{In,Out,Transfer,Take}List | 同 DocListPage | 同 DocListPage | 是 | 是 | 否 | 是 | 是(文本) | 否 |
| stock/BalanceView.vue | 是(252) | 是(仓库/类型/数量区间/仅低于安全) | 是(339) | **是** | 否 | 是(结存+流水两处) | 是(文本) | 否 |
| stock/TakeForm.vue(行项) | 否 | 否 | 否 | — | 否 | 否 | 是(alert) | 否 |
| system/SystemView.vue | 是(278,330) | 是(模块/动作/字段/时间) | 是(321,365) | 否 | 否 | 否 | 部分(备份有) | 否 |

**不一致项（点名）**
1. **分页控件三种规格**：`ContractsView.vue:841` 与 `SystemView.vue:321` 无 `sizes`；`DocListPage.vue:494`、`BalanceView.vue:339` 有 `sizes`；`SystemView.vue:321/365` 还缺 `background`。分页显隐条件也不一：`UserView.vue:254`、`MasterTablePage.vue:310`、`DocListPage.vue:494` 用 `v-if="total > pageSize"`（一页内分页控件消失），`ContractsView.vue:836`、`BalanceView.vue:339` 用 `v-if="!isTree"` / `v-if="total > pageSize"`（前者恒显）。
2. **批量操作全缺**：12 个列表页 0 个有 `type="selection"` 或批量动作；所有行内动作挤在固定宽操作列（`DocListPage.vue:472` 宽 **320px** 内最多 9 个链接按钮：查看/编辑/提交/审核/驳回/下推/打印/反审核/作废），密集 ERP 场景下逐行点选效率低且视觉权重混乱。
3. **导出能力不对等**：仅合同台账有「选择导出列 + 记住选择」（`ContractsView.vue:158-206, 1015-1037`）；单据列表只有单一「导出」按钮（`DocListPage.vue:380-382`）；主数据/角色/用户/系统日志**全无导出**（台账类数据无法离线核对）。
4. **空态三种语言**：`template #empty` 文本（`DocListPage.vue:491`、`BalanceView.vue:336`、`TakeForm.vue:350`、`SystemView.vue:392`）／`el-empty` 插图（`DashboardView.vue:144`、`ContractsView.vue:1169`）／`el-alert` 说明（`TakeForm.vue:311`）；另有 `UserView.vue:208`、`RoleView.vue:182`、`ContractsView.vue:772` 主干表**完全没有**空态。
5. **URL 状态全缺**：全项目 `router/index.ts` 未定义任何 query 参数路由，页面也**从不调用** `useRoute().query`（仅 `Forbidden/Login/AppLayout` 用到 query）；因此筛选/分页/Tab 无法深链、分享，浏览器回退会直接离开页面。
6. **日期格式 3 种截断长度**：`slice(0,10)`（ContractsView:652、Dashboard:86、4 个 List、5 个 stock List）、`slice(0,19)`（BalanceView:153）、`slice(11,19)` 拼接（ContractsView:1207、DocListPage:541）；另有 `UserView.vue:239`、`SystemView.vue:304/351` **完全不格式化**直出原始串。
7. **货币格式 2 套**：`toLocaleString('zh-CN', …)`（ContractsView:656、Dashboard:91、DocListPage:256、MasterTablePage:229、DocItemsTable:86、purchase/OrderList:30、sales/OrderList:32）vs `toFixed(2)` 无千分位（BalanceView:149、`fmtPrice`/`amountOf` 体系）；且 `ContractsView.vue:956` 单独加 `￥` 前缀。
8. **金额/数量列无一处 `font-variant-numeric: tabular-nums`**：涉及 ContractsView:808/811/937、BalanceView:307/312/393、Dashboard:153、DocListPage:460、DocItemsTable:276 等全部数值列。
9. **编号列有无不一致**：`type="index" label="#"` 存在于 `DocListPage.vue:443`、`MasterTablePage.vue:280`、`BalanceView.vue:298`、`TakeForm.vue:314`；合同台账（ContractsView:772 起）、UserView、RoleView、SystemView、PartyDraftView 均无序号列。
10. **破行操作入口不一致**：合同台账用 `@row-dblclick`（ContractsView:773），库存明细用 `@row-click`（BalanceView:297），其余列表必须点行首单号链接（DocListPage:444-447）。
11. **主从表是否自动合计**：`DocFormPage` + `DocItemsTable` 有 `show-summary` 合计行（DocItemsTable:236）；合同弹窗自建行项表**无** `show-summary`，只有表外一个 `.totalbar`（ContractsView:902-948 + 954-957），两套「明细合计」交互。
12. **el-select 自由录入策略不统一**：`allow-create` 用在币种（purchase/OrderForm:74、sales/OrderForm:87）、结算方式（purchase/OrderForm:66）、入库供应商（InForm:60）、合同标签（ContractsView:1000）；其余档案类下拉一律严格选择。

---

## 3. 设计令牌缺失统计

`web/src/style.css` 仅 11 行（`font-family` + `background: #f5f7fa`），**无任何 `--var` 令牌**；无 Tailwind/SCSS 变量；所有数值散落在各组件的 `<style scoped>` 内联样式里。

### 高频硬编码颜色（Top 10）
| 值 | 次数 | 语义 | 证据（文件:行号） |
|---|---|---|---|
| `#909399` | 24 | 次要文字/gray | ContractsView.vue:1245,1251,1253；DashboardView.vue:272,273,274；BalanceView.vue:426,269；SystemView.vue:420,422,426,427；UserView.vue:327,330；PartyDraftView.vue:220,223；RoleView.vue:255；sales/RequestForm.vue:110；purchase/RequestForm.vue:194；TakeForm.vue:401,402；MasterTablePage.vue:371,374；DocListPage.vue:559,562；DocFormPage.vue:390,392；TreeMasterPage.vue:257；RelatedDocs.vue:145 |
| `#f56c6c` | 8 | 危险/负偏差 | ContractsView.vue:1255；DashboardView.vue:271；BalanceView.vue:429,431；TakeForm.vue:404；DocItemsTable.vue（hint 系 `#e6a23c`） |
| `#409eff` | 4 | 主色 | ContractsView.vue:1256；DashboardView.vue:268；AppLayout.vue:25 |
| `#67c23a` | 3 | 成功/正偏差 | BalanceView.vue:430；TakeForm.vue:403 |
| `#e6a23c` | 3 | 警告 | DashboardView.vue:270；BalanceView.vue:428；DocItemsTable.vue:319 |
| `#303133` | 2 | 主要文字 | DashboardView.vue:269,276 |
| `#fef0f0` | 2 | 危险行底色 | BalanceView.vue:432；TakeForm.vue:406 |
| `#c0c4cc` | 1 | 禁用/占位 | ContractsView.vue:1257 |
| `#606266` | 2 | 常规文字 | ContractsView.vue:1254；RelatedDocs.vue:143 |
| `#ecf5ff` / `#fafbfd` / `#f0f9eb` / `#e4e7ed` / `#fff` | 各 1 | 行底色/边框 | ContractsView.vue:1259,1258；TakeForm.vue:405；RoleView.vue:256；ContractsView.vue:1116 |

### 高频硬编码字号（Top 8）
| 值 | 次数 | 证据 |
|---|---|---|
| `12.5px` | 24 | UserView.vue:327,330；RoleView.vue:255；PartyDraftView.vue:220,223；SystemView.vue:420,422；BalanceView.vue:426；TakeForm.vue:401；purchase/RequestForm.vue:194；sales/RequestForm.vue:110；DashboardView.vue:273,274；DocListPage.vue:559,562；DocFormPage.vue:390,392；MasterTablePage.vue:371；TreeMasterPage.vue:257；RelatedDocs.vue:145 |
| `12px` | 6 | ContractsView.vue:1245,1251；TakeForm.vue:402；DocItemsTable.vue:319,320；TopBar.vue:86 |
| `13px` | 5 | ContractsView.vue:1253,1254；DashboardView.vue:272；RelatedDocs.vue:143；TopBar.vue:64 |
| `15px` | 12 | ContractsView 无；UserView.vue:326；RoleView.vue:254；PartyDraftView.vue:219；SystemView.vue:419；BalanceView.vue:425；DocListPage.vue:558；DocFormPage.vue:389；MasterTablePage.vue:370；TreeMasterPage.vue:256；AppLayout.vue:53 |
| `16px` | 1 | ContractsView.vue:1255 |
| `20px` | 1 | DashboardView.vue:276 |
| `28px` | 1 | DashboardView.vue:269 |
| `11.5px` | 1 | LoginView.vue:94（本模块外，佐证无标尺） |

### 高频硬编码间距（Top 8）
| 值 | 次数 | 证据 |
|---|---|---|
| `12px` | 24+ | `.mb/.mt/.mb12/.mt12/.pager{margin-top:12px}` 在 ContractsView.vue:1222,1223；DashboardView.vue:265,266,277；SystemView.vue:423,424,425；BalanceView.vue:422,427；TakeForm.vue:400；PartyDraftView.vue:221；UserView.vue:328；MasterTablePage.vue:373；DocListPage.vue:556,560,561；DocFormPage.vue:385,391；TreeMasterPage.vue:261；PushDialog.vue:285；ApproveDialog.vue:76 |
| `8px` | 14 | ContractsView.vue:1236,1243,1252；DashboardView.vue:274,278；PartyDraftView.vue:222；UserView.vue:329；BalanceView.vue:423；TakeForm.vue:402；TreeMasterPage.vue:258,262；DocFormPage.vue:388,391；DocListPage.vue:561；MasterTablePage.vue:374 |
| `4px` | 6 | ContractsView.vue:1243；DashboardView.vue:278；PartyDraftView.vue:222；UserView.vue:329 |
| `6px` | 6 | ContractsView.vue:1245,1247,1255；BalanceView.vue:269；TreeMasterPage.vue:259；MasterTablePage.vue:368 |
| `10px` | 4 | UserView.vue:327；RoleView.vue:255；SystemView.vue:420,422 |
| `width: 220px` 输入框 | 5 | ContractsView.vue:718,740；SystemView.vue:330；DocListPage.vue:393；MasterTablePage.vue:255 相邻的 200px |
| `width: 200px` 输入框 | 4 | MasterTablePage.vue:255；BalanceView.vue:252；RoleView.vue:171；DocListPage.vue:424 |
| `width: 180px` 输入框 | 4 | UserView.vue:183；SystemView.vue:278；MasterTablePage.vue:258；PushDialog.vue:227 |

**结论**：无令牌体系，`#909399`+`12.5px` 这一对「次要文字」样式被复制 24 次，`.mb{margin-bottom:12px}` 被复制 8 次；颜色/字号/间距任何一次品牌调整都需要改动 15+ 个文件。

---

## 4. 5 维评分与证据

### 1. 哲学一致性 · 6/10（Functional）
方向明确且被认真执行：全站 `el-card shadow="never"` + `size="small"` 表格 + 统一权限点命名（`DocListPage.vue:133-139`）+ 统一状态标签组件（`DocStatusTag.vue:17-26`）+ 破坏性操作一律 `ElMessageBox.confirm`/`prompt`（`ContractsView.vue:496-499`、`MasterTablePage.vue:196-199`）。但同一业务概念有两种范式：往来单位在合同里是「档案下拉 + 名称快照」（`ContractsView.vue:871-895`），在采购单里却是「可自由输入的币种/结算方式」（`purchase/OrderForm.vue:26-27,66,74`）；枚举与中文默认值硬编码在前端（`ContractsView.vue:213,215,393`）与后端字典并存；「上级id」把数据库列名直接给用户看（`OrgView.vue:15`、`ProductTypeView.vue:10`）。这些是同一件外衣下的三种风格，因此落在 6 而非 7。

### 2. 视觉层级 · 6/10（Functional）
大结构是清楚的：`title(15px/600) + subtitle(12.5px/#909399) + 卡片头 + 内容` 在 12 个页面逐字一致（`DocListPage.vue:558-559`、`MasterTablePage.vue:370-371`、`TreeMasterPage.vue:256-257`、`SystemView.vue:419-420`、`BalanceView.vue:425-426`）。但关键数字没有真正的层：合同台账把「金额 92px / 已付+比例 128px」压成同级小字并让比例降到 12px `#909399`（`ContractsView.vue:808-819,1245`），而首页同类数字被放大到 20–28px（`DashboardView.vue:269,276`）；`master/sales/RequestForm.vue:72-90` 把「客户 / 客户文本 / 客户快照」三个同源信息排成三行，权重无差别；`DocListPage.vue:472` 一个 320px 操作列里最多 9 个同权重链接按钮，是本模块最明显的「所有东西一起喊」。故为 6。

### 3. 细节执行 · 4/10（Broken）
典型 90/10 项几乎都没收：字号存在 15/13/12.5/12/11.5px 五档且 12.5px 出现 24 次（`UserView.vue:327,330`、`SystemView.vue:420,422`）；15 个硬编码色值分散（`ContractsView.vue:1253-1259`、`BalanceView.vue:428-432`、`DashboardView.vue:268-276`）；数值列无一处 `tabular-nums`（`ContractsView.vue:808`、`BalanceView.vue:307`、`DashboardView.vue:153`）；同一份格式化函数被复制 7 份且两种口径（`ContractsView.vue:656` vs `BalanceView.vue:149`），日期截断长度 3 种（`:652` vs `BalanceView.vue:153` vs `ContractsView.vue:1207`），并按 Guideline「Hardcoded date/number formats」应全部换 `Intl.*`；`ContractsView.vue:754` 仍用 Element Plus 已弃用的 `el-checkbox label` 作值；`ContractsView.vue:750` 重置不完整（漏 `include_deleted` 与 `page=1`）；`BalanceView.vue:297` 给所有行加 `cursor:pointer`；`SystemView.vue:242` 用 `Object.keys()` 当表格数据源。这些都属可见的「胶带与绳子」。

### 4. 功能性 · 6/10（Functional）
对「内网高频录单」这个真实用途，核心路径是通的：查询支持 Enter（`ContractsView.vue:718,737`、`DocListPage.vue:393`、`MasterTablePage.vue:255`、`BalanceView.vue:252`），下拉统一 `filterable`，行项校验精确到行（`ContractsView.vue:459-463`、`DocFormPage.vue:162-183`、`TakeForm.vue:187-201`），危险操作有确认（`:496`,`509`,`555`,`629`），数量精度跟随单位小数位（`DocItemsTable.vue:58-65,172-182`），物料/单位/类型支持「现场快建不跳转」（`DocItemsTable.vue:157-181`、`MasterTablePage.vue:336-350`），库存侧还有重算校验+按流水修复（`BalanceView.vue:191-214`）——这些是真正为高频使用设计的。扣分在效率与鲁棒性：**无批量操作**（所有列表 0 处 `type="selection"`）；**无任何 URL 状态**，筛选不可深链/分享、回退即丢（`router/index.ts:40-42` 无 query 支持）；无虚拟滚动（`ContractsView.vue:772`、`BalanceView.vue:296`、`DocListPage.vue:442` 均未用 `el-table-v2`/虚拟化，表头 12 列以上时窄屏只能横向滚）；错误处理在 500 无 `detail` 时静默（`api.ts:45` 仅在 `detail` 为字符串时提示），而下拉失败普遍静默降级为空（`purchase/OrderForm.vue:32-38`、`InForm.vue:26,29`），用户会看到「没有供应商」却不知道为什么。

### 5. 创新性 · 5/10（Competent and unmemorable）
整体是成熟的中后台范式（配置驱动壳 + `el-card` + `size="small"` 表格），符合生产交付的保守选择，不额外扣分。真正有想法的只有三处，且都能指向具体实现：**合同框架树视图**把父/子行做成可折叠的展示层而不改变筛选/导出语义（`ContractsView.vue:56-99,774-781,845` 并显式用 alert 说明语义边界）；**盘点单「账面冻结 + 差异行高亮 + 自动生成盘盈/盘亏」**（`TakeForm.vue:81-115,313,405-406`）；**库存重算校验并可一键按流水修复**（`BalanceView.vue:191-214,282-292`）。除此之外没有超出同类的交互或信息设计，故 5。

**综合**：5 / 6 / 4 / 6 / 5 —— 平均 5.2。可用，但「业务视图层」目前是**功能达标、一致性合格、细节执行不合格**：主要风险不是不能干活，而是 15+ 份复制粘贴的列表/表单模板让任何一次全局调整都退化成 15 次手改，并且数据密集页缺少批量操作与深链这两个高频效率杠杆。

---

## 5. Keep / Fix / Quick wins

### Keep（勿破坏）
1. **配置驱动壳的边界划分**：`DocListPage.vue` / `DocFormPage.vue` / `DocItemsTable.vue` / `MasterTablePage.vue` / `TreeMasterPage.vue` 把 12 个页面收敛成 5 个壳——这是全项目最值钱的架构决定，一致性矩阵中的整齐项全部来自它。后续修一致性应继续改壳，而不是逐页改。
2. **按权限点隐藏 + 后端硬校验的双层放行**：`DocListPage.vue:133-139,319-344`、`ContractsView.vue:10-11`、`auth.hasPerm` 全站贯穿，且 `canPush` 有详尽的「字段缺失时不隐藏」防线注释（`DocListPage.vue:334-342`）。这种「体验层可退化、边界在后端」的写法要保留。
3. **数量精度跟随单位小数位**：`DocItemsTable.vue:58-65,146-154,172-182` + `TakeForm.vue:69-79`，录入端与校验端同源，避免 0.5 个「个」这类脏数据。
4. **行内精确定位的中文错误提示**：「第 N 行：请选择物料档案」（`ContractsView.vue:459-463`）、「第 N 行：单位不支持小数」（`DocFormPage.vue:172-182`、`TakeForm.vue:197-200`）——直接告诉用户改哪一行，比通用 toast 有效得多。
5. **盘点/库存校验类只读保护**：账面数量生成即冻结（`TakeForm.vue:352-354`）、`BalanceView.vue:191-214` 修复前二次确认且明确「不改动流水与单据」。

### Fix（P0/P1，按「每分钟节省的视觉/效率成本」排序）
1. **P0｜给所有列表页加批量操作**：在 `DocListPage.vue`（共用壳，一次改动覆盖 8 个页面）与 `ContractsView.vue:772` 加 `type="selection"` + 批量提交/审核/导出/停用；当前 9 个链接按钮挤在 `DocListPage.vue:472` 的 320px 里，逐行点击是主要工时消耗点。
2. **P0｜收集 7 份重复格式化函数为 `src/utils/format.ts`**：`ContractsView.vue:651-657`、`DashboardView.vue:85-92`、`DocListPage.vue:253-261`、`MasterTablePage.vue:226-230`、`DocItemsTable.vue:69-87`、`purchase/OrderList.vue:27-35`、`sales/OrderList.vue:27-37`、`BalanceView.vue:138-154`；统一用 `Intl.DateTimeFormat('zh-CN')` / `Intl.NumberFormat('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})`，并给数值列加 `font-variant-numeric: tabular-nums`（`ContractsView.vue:808,811,937`、`BalanceView.vue:307,312,393,400`）。
3. **P0｜建设计令牌并替换硬编码**：先把 `#909399`（24 处）、`12.5px`（24 处）、`.mb{margin-bottom:12px}`（8 处）抽成 `web/src/style.css` 的 `--ctms-text-muted/--ctms-font-sm/--ctms-gap`，替换清单直接取第 3 节表格。这是唯一能阻止「改一次颜色动 15 个文件」的杠杆。
4. **P1｜筛选/分页/Tab 同步到 URL query**：至少覆盖 `ContractsView.vue:46-54`（query 对象）与 `DocListPage.vue:117-126`，用 `router.replace({ query })` + `onMounted` 回填；顺带修 `ContractsView.vue:750` 的重置完整性（补 `include_deleted:false` 与 `page.value=1`）。
5. **P1｜补空态与表格可用性**：`ContractsView.vue:772`、`UserView.vue:208`、`RoleView.vue:182`、`SystemView.vue:242` 加 `#empty`；统一空态语言（建议全站 `template #empty` 文本 + 一句下一步动作，参照 `PartyDraftView.vue:178` 的写法，它是全项目最好的空态）。
6. **P1｜弹窗/抽屉窄屏适配**：`ContractsView.vue:849(1080px)`、`:1015(760px)`、`:1040(720px)`、`:1130(640px)`，改为 `width="min(1080px, 92vw)"` 之类；`:span` 固定值（`DashboardView.vue:101-110`、`DocFormPage.vue:321-351`）加 `:xs/:sm` 断点。当前全项目仅 `ContractsView.vue:1240` 一个媒体查询。

### Quick wins（5–15 分钟/项）
1. `ContractsView.vue:776`：`<span class="fw-icon" @click.stop>` → `<el-button link @click.stop :aria-label="collapsedIds.includes(row.id) ? '展开子合同' : '折叠子合同'">`，一次修好「非按钮可点击」+「图标按钮缺 aria-label」+「缺键盘处理」三条规则。
2. `DashboardView.vue:260`：`el-alert @click` → 包一层 `<el-button link>` 或改用标题栏按钮，去掉 `style="cursor:pointer"`。
3. `ContractsView.vue:954-957` 与 `DocItemsTable.vue:236`：给合同行项表补 `show-summary` + `summary-method`（可直接复用 `DocItemsTable.vue:206-213` 的实现），取消表外 `.totalbar` 双轨。
4. `InList.vue:7-9` / `OutList.vue:7-9` / `TransferList.vue:9-11` / `purchase/RequestList.vue:33-35` / `sales/RequestList.vue:31-33`：删掉本地 `fmtDate`，改用共享 util（第 2 项完成后各删 3 行）。
5. `InList.vue:23-25`、`OutList.vue:23-25`、`TransferList.vue:25-27`、`TakeList.vue:22-24`：把四处逐字重复的「过账状态」`el-tag` 抽成 `<el-tag :type="detail.posted?'success':'info'">{{ detail.posted?'已过账':'未过账' }}</el-tag>` 的共享组件（或直接扩 `DocStatusTag.vue`）。
6. `SystemView.vue:321,365`：补 `background` 属性，与 `DocListPage.vue:494` 对齐；`UserView.vue:254`、`MasterTablePage.vue:310`、`DocListPage.vue:494` 去掉 `v-if="total > pageSize"`，改为恒显以消除「分页控件忽隐忽现」。
7. `ContractsView.vue:754`：`el-checkbox label="显示已停用"` → `el-checkbox v-model="query.include_deleted" value="true">显示已停用</el-checkbox>` 写法（Element Plus 2.6+ 正确用法）。
8. `purchase/OrderList.vue:40-44`、`sales/OrderList.vue:43-53`、`sales/RequestList.vue:38-42`、`purchase/RequestList.vue:40-44`：把「未匹配就显示 `ID {id}`」改成「已删除/无权限的{仓库|客户|部门}（#{id}）」，避免主键直出给业务用户。
