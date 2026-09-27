# 单据域组件审查（components/ 全域）

- 审查范围（11 个文件，全部逐行读完）：`web/src/components/MasterTablePage.vue`、`web/src/components/TreeMasterPage.vue`、`web/src/components/QuickCreateDialog.vue`、`web/src/components/doc/DocListPage.vue`、`web/src/components/doc/DocFormPage.vue`、`web/src/components/doc/DocItemsTable.vue`、`web/src/components/doc/DocStatusTag.vue`、`web/src/components/doc/PushDialog.vue`、`web/src/components/doc/ApproveDialog.vue`、`web/src/components/doc/RelatedDocs.vue`、`web/src/components/doc/ContractDetailDrawer.vue`
- 审查标尺：`D:\dsh\hetong\.dsh\skills\web-design-guidelines\references\guidelines.md`（Vercel Web Interface Guidelines）+ `critique` 技能 5 维框架
- 定位：内网 ERP（Vue3 + Element Plus + Vite），数据密集、长时间高频使用；评判偏效率、密度、一致性、可用性，不评价营销页式视觉表现力
- 说明：全程只读审查，未修改任何业务代码。行号均来自本次实际读取的文件内容。

---

## 1. 逐文件合规问题清单

格式：`相对路径:行号 - 问题（规则名）`。无问题的文件写 `✓ pass`。

### `web/src/components/MasterTablePage.vue`

```
web/src/components/MasterTablePage.vue:279 - 表格无 height/max-height、无固定表头；pageSize 可到 100，行数一多分页器与列头滚出视口（Large lists >50: virtualize；Flex/grid over JS measurement）
web/src/components/MasterTablePage.vue:281 - 列定义只给 min-width，数字/金额列无右对齐与 tabular-nums，账号/编码列无法逐位比对（font-variant-numeric: tabular-nums）
web/src/components/MasterTablePage.vue:168 - 必填校验只发 ElMessage.warning，无行内错误、不聚焦首个错误字段（Errors inline next to fields; focus first error on submit）
web/src/components/MasterTablePage.vue:314 - el-dialog 未设 overscroll-behavior: contain（overscroll-behavior: contain in modals/drawers/sheets）
web/src/components/MasterTablePage.vue:137 - 重置按钮无 type/primary 等语义区分，且 page 重置后立即 load；表头/筛选项布局用 inline form 逐项换行、无 grid（Flex/grid over JS measurement）
web/src/components/MasterTablePage.vue:295 - 操作列固定 220px 承载 3 个文字按钮，窄屏必挤（Avoid unwanted scrollbars）
web/src/components/MasterTablePage.vue:337 - 「＋」图标按钮无 aria-label，仅 title（Icon-only buttons need aria-label）
web/src/components/MasterTablePage.vue:348 - 「＋」图标按钮无 aria-label（Icon-only buttons need aria-label）
web/src/components/MasterTablePage.vue:229 - toLocaleString('zh-CN', …) 硬编码金额格式，重复第 5 份（Numbers/currency: use Intl.NumberFormat）
web/src/components/MasterTablePage.vue:284 - 行内自绘状态 el-tag，status→色/文案映射与 DocStatusTag、DocListPage 各一份（重复实现；semantic HTML before ARIA）
web/src/components/MasterTablePage.vue:292 - 长文本截断只依赖 show-overflow-tooltip，无文本容器 truncate/min-w-0 兜底（Text containers handle long content；Flex children need min-w-0）
web/src/components/MasterTablePage.vue:307 - 空态为纯文本「暂无数据」，未用 el-empty，也无「无结果 vs 无数据」区分（Handle empty states）
web/src/components/MasterTablePage.vue:341 - el-tree-select 无零选项兜底；ensureTypeTree 失败后下拉为空且无提示（Handle empty states）
web/src/components/MasterTablePage.vue:28 - permView 声明但全文未使用（7 个调用页都传了），查看权限实际未生效（dead prop / a11y-consistency）
web/src/components/MasterTablePage.vue:154 - 表单重置用手写 delete，未用 el-form 的 validate/resetFields（semantic HTML）
web/src/components/MasterTablePage.vue:374 - tip 文案 12px #909399 静态色，未随主题/暗色适配（Dark Mode & Theming）
```

### `web/src/components/TreeMasterPage.vue`

```
web/src/components/TreeMasterPage.vue:50 - load() 用 try/finally 无 catch，接口失败 = 未捕获 Promise rejection + 空树无错误态/重试（Handle empty states；Error messages include fix/next step）
web/src/components/TreeMasterPage.vue:197 - el-tree 无 max-height/虚拟化，default-expand-all 展开全部节点（Large lists >50: virtualize）
web/src/components/TreeMasterPage.vue:100 - 必填校验只 ElMessage.warning，无行内错误、不聚焦字段（focus first error）
web/src/components/TreeMasterPage.vue:196 - 过滤输入框缺 autocomplete/name（Inputs need autocomplete and meaningful name）
web/src/components/TreeMasterPage.vue:88 - 未选节点时仅 toast 提示，未禁用「新增子节点」按钮（Submit button stays enabled until request starts；hover/disabled 状态）
web/src/components/TreeMasterPage.vue:201 - 节点名无 truncate/max-width，长名称会把同排 el-tag 推出可视区（Text containers handle long content）
web/src/components/TreeMasterPage.vue:73 - 点击切换节点无未保存提示，右侧表单输入即被 fillForm 覆盖（Warn before navigation with unsaved changes）
web/src/components/TreeMasterPage.vue:242 - 允许停用有子节点的父节点，与第 345 行「父节点禁用、只能选叶子」的口径矛盾（一致性）
web/src/components/TreeMasterPage.vue:217 - 行内自绘状态标签，未复用 DocStatusTag/MasterTablePage 的 statusText（重复实现）
web/src/components/TreeMasterPage.vue:238 - 动作区 margin-top: 8px，与 6 个同类页面的 12px 页脚间距不一致（重复实现）
web/src/components/TreeMasterPage.vue:26 - permView 声明未使用（dead prop）
```

### `web/src/components/QuickCreateDialog.vue`

```
web/src/components/QuickCreateDialog.vue:64/66/70 - 必填校验用 ElMessage.warning，弹窗内无字段级错误（Errors inline next to fields）
web/src/components/QuickCreateDialog.vue:92 - 弹窗缺 overscroll-behavior: contain（overscroll-behavior: contain in modals）
web/src/components/QuickCreateDialog.vue:96 - 编码输入框缺 autocomplete="off" / spellCheck=false（Disable spellcheck on codes）
web/src/components/QuickCreateDialog.vue:102 - 小数位为数字字段但未标 required（表单语义）
web/src/components/QuickCreateDialog.vue:95/98/108/122/128/134 - 5 处 label 无 htmlFor 显式关联（依赖 el-form-item 隐式关联，脆弱）（Labels clickable）
web/src/components/QuickCreateDialog.vue:96/99/109/112/123/126 - placeholder 全部无「…」结尾与示例格式（Placeholders end with … and show example pattern）
web/src/components/QuickCreateDialog.vue:44 - open() 先置 visible 再 await 拉下拉数据，弹窗先空后填（Hydration/首次渲染；loading 态缺失）
web/src/components/QuickCreateDialog.vue:56 - 下拉加载失败静默，物料必填项无法选择且无提示（Handle empty states）
web/src/components/QuickCreateDialog.vue:61 - save() 无回车提交，无快捷键（keyboard handlers）
web/src/components/QuickCreateDialog.vue:92 - 弹窗与表单无 aria 属性（Form controls need label or aria-label）
```

### `web/src/components/doc/DocListPage.vue`

```
web/src/components/doc/DocListPage.vue:472 - 操作列固定 320px 在权限全开时渲染最多 9 个 link 按钮（Avoid unwanted scrollbars；Detail execution）
web/src/components/doc/DocListPage.vue:279 - 单一 actionLoading 同时驱动所有行的「提交」按钮 loading，操作哪一行不可辨（Functionality：行级反馈）
web/src/components/doc/DocListPage.vue:442 - 表格无固定高度/固定表头，20–100 行时列头与分页器滚出视口（Large lists >50；固定列/表头）
web/src/components/doc/DocListPage.vue:460 - 金额列 align="right" 但全局无 tabular-nums，多行金额无法按位比对（font-variant-numeric: tabular-nums）
web/src/components/doc/DocListPage.vue:494 - total ≤ pageSize 时整条分页器隐藏，看不到「共 N 条」也无法切每页条数（Vercel: pagination state 可见性）
web/src/components/doc/DocListPage.vue:196 - openDetail 先 visible=true 再 fetch，drawer 无错误分支，fetchDoc 失败即永久空白（Handle empty states；Error messages include fix/next step）
web/src/components/doc/DocListPage.vue:117 - 分页/筛选/状态未写入 URL query，刷新与分享回到初始态（URL reflects state）
web/src/components/doc/DocListPage.vue:502 - el-drawer 缺 overscroll-behavior: contain（overscroll-behavior: contain in modals/drawers）
web/src/components/doc/DocListPage.vue:390 - 筛选区用 inline form，8 个筛选项逐项换行无 grid（Flex/grid over JS measurement）
web/src/components/doc/DocListPage.vue:402 - start-placeholder="开始"/end-placeholder="结束" 无「…」（Placeholders end with …）
web/src/components/doc/DocListPage.vue:442 - 表格与抽屉无 aria 属性；空态为纯文本「暂无数据」未用 el-empty（Handle empty states）
web/src/components/doc/DocListPage.vue:256 - toLocaleString('zh-CN', …) 硬编码（Intl.NumberFormat）
web/src/components/doc/DocListPage.vue:259 - fmtDate 用 String().slice(0,10) 硬编码日期格式（Dates: use Intl.DateTimeFormat）
web/src/components/doc/DocListPage.vue:137 - can() 把 `${permPrefix}.${code}` 拼接散落在组件内，与 DocStatusTag 的状态枚举各一处（重复实现）
web/src/components/doc/DocListPage.vue:13 - 注释宣传 detail-extra 插槽与 view 事件，全项目 grep 无任何父页面使用（死插槽/死事件）
```

### `web/src/components/doc/DocFormPage.vue`

```
web/src/components/doc/DocFormPage.vue:374 - 「保存草稿」与「保存并提交」共用 saving，未锁定另一按钮，无 dirty 期间的二次提交防护（Submit button stays enabled until request starts；并发提交）
web/src/components/doc/DocFormPage.vue:271 - back() 直接 router.push，全项目无 beforeunload / onBeforeRouteLeave，未保存行项静默丢失（Warn before navigation with unsaved changes）
web/src/components/doc/DocFormPage.vue:108 - new Date().toISOString().slice(0,10) 取 UTC 日期，+8 时区 00:00–08:00 默认日期早一天（Dates: 正确本地时间）
web/src/components/doc/DocFormPage.vue:319 - el-form 无 rules/model/ref，校验全在 validate() 里发 ElMessage，无行内错误、不回填定位（Errors inline next to fields）
web/src/components/doc/DocFormPage.vue:162 - 行项错误以「第 N 行」toast 呈现，不滚动定位到该行，长表无法定位（focus first error on submit）
web/src/components/doc/DocFormPage.vue:296 - 路由进入即 v-loading 覆盖整页；失败后 detail 为空但 UI 保持「新增」骨架，无重试（Handle empty states）
web/src/components/doc/DocFormPage.vue:188 - 日期必填只 toast，未给 el-form-item 设 error 态（Errors inline next to fields）
web/src/components/doc/DocFormPage.vue:301 - 页面主标题用 span.title 而非 h1，全文无 heading 层级（Headings hierarchical）
web/src/components/doc/DocFormPage.vue:349 - 备注 textarea 无 autocomplete="off"（Inputs need autocomplete）
web/src/components/doc/DocFormPage.vue:25 - items 为 Record<string, any>[]，数量/单价精度规则以字符串拼接逐行重算（Prefer typed state；uncontrolled inputs cheap per keystroke）
web/src/components/doc/DocFormPage.vue:256 - Ctrl/Cmd+Enter 提交快捷键缺失（keyboard handlers）
```

### `web/src/components/doc/DocItemsTable.vue`

```
web/src/components/doc/DocItemsTable.vue:86 - fmtMoney 空值/非法值返回 '0.00'，而 MasterTablePage:227、DocListPage:254、RelatedDocs:22 返回 '—'，空与零不可辨（一致性；Typography 数字口径）
web/src/components/doc/DocItemsTable.vue:276 - 金额列右对齐但无 tabular-nums；数量/单价列既不右对齐也无等宽数字（font-variant-numeric: tabular-nums）
web/src/components/doc/DocItemsTable.vue:299 - 行删除按钮无确认、无 undo；新增行误加只能盲删（Destructive actions need confirmation or undo）
web/src/components/doc/DocItemsTable.vue:236 - 表格无 max-height，行数累积后 show-summary 合计行随之滚出视口（Functionality：合计不可见）
web/src/components/doc/DocItemsTable.vue:239 - 物料/备注列 min-width 230/140，加数量 140 + 单价 130 + 金额 120 在窄屏必横向溢出且列头不可见（固定列/横向溢出）
web/src/components/doc/DocItemsTable.vue:243 - 每个物料单元格都是 el-select，20 行 = 20 个选项容器，无行虚拟化（Large lists >50: virtualize）
web/src/components/doc/DocItemsTable.vue:113 - loadProducts 无参数时全量拉取产品选项（无分页/上限），首屏就是一次大响应（Large arrays without virtualization）
web/src/components/doc/DocItemsTable.vue:302 - 空态为纯文本 emptyText，未用 el-empty（Handle empty states）
web/src/components/doc/DocItemsTable.vue:241 - placeholder「输入编码/名称搜索」无示例格式（Placeholders show example pattern）
web/src/components/doc/DocItemsTable.vue:249 - 「＋」图标按钮仅 title 无 aria-label（Icon-only buttons need aria-label）
web/src/components/doc/DocItemsTable.vue:266 - integerHint 用橙色 warning 文案插入单元格，行高随提示抖动（CLS；detail execution）
```

### `web/src/components/doc/DocStatusTag.vue`

```
web/src/components/doc/DocStatusTag.vue:30 - 缺 aria-label / aria-hidden，纯色 tag 对屏幕阅读器仅有文字（Decorative icons need aria-hidden；Async updates need aria-live）
web/src/components/doc/DocStatusTag.vue:25 - 未知 status 时回退展示原始英文码，未记录/提示未知状态（兜底一致性）
web/src/components/doc/DocStatusTag.vue:17 - status→色/文案字典仅存在于本组件，DocListPage:320-328、MasterTablePage:90-96、TreeMasterPage:217 各写一份等价映射（重复实现）
web/src/components/doc/DocStatusTag.vue:25 - 未导出状态枚举供 canSubmit/canApprove 等消费，状态词汇跨文件分散（重复实现）
✓ 逻辑分支与未知值兜底本身健全（无其它问题）
```

### `web/src/components/doc/PushDialog.vue`

```
web/src/components/doc/PushDialog.vue:51 - new Date().toISOString().slice(0,10) 的 UTC 默认日期（+8 时区早一天）
web/src/components/doc/PushDialog.vue:104 - open() 先 visible=true 再 fetchDoc，拉取前弹窗已可见，失败无回滚/错误态（Handle empty states）
web/src/components/doc/PushDialog.vue:112 - loading 同时承担「详情加载」与「提交中」，初始加载失败后主按钮呈 loading 假象（Submit spinner during request 语义）
web/src/components/doc/PushDialog.vue:238 - 表格 max-height=360 但无 tabular-nums、无固定列，9 列 860px 弹窗内横向挤压（font-variant-numeric；横向溢出）
web/src/components/doc/PushDialog.vue:263 - 「本次下推」列在 :max="balanceOf(row)" 下仍全列渲染 input-number，行数多时无虚拟化/分页（Large lists >50）
web/src/components/doc/PushDialog.vue:238 - 表格 :max-height="360" 承载最多 200 条可勾选行（rows 无上限），勾选态与滚动位置易丢失（Large lists >50: virtualize）
web/src/components/doc/PushDialog.vue:155 - submit() 校验失败只 ElMessage.warning，不标记具体行/不滚动定位（focus first error on submit）
web/src/components/doc/PushDialog.vue:214 - el-dialog 缺 overscroll-behavior: contain（overscroll-behavior: contain in modals）
web/src/components/doc/PushDialog.vue:240 - type="selection" 列无表头全选语义说明，无障碍未处理（Checkboxes/radios: shared hit target；aria）
web/src/components/doc/PushDialog.vue:227 - placeholder 用模板字符串「请选择仓库」而无「…」（Placeholders end with …）
web/src/components/doc/PushDialog.vue:78 - fmtQty 与 DocItemsTable:69 同日同语义却两份实现，精度钳制写法不同（重复实现）
web/src/components/doc/PushDialog.vue:124 - setTimeout(...,0) 驱动 toggleRowSelection 的全选，依赖渲染时序（No layout reads in render；脆弱实现）
```

### `web/src/components/doc/ApproveDialog.vue`

```
web/src/components/doc/ApproveDialog.vue:56 - el-dialog 缺 overscroll-behavior: contain（overscroll-behavior: contain in modals）
web/src/components/doc/ApproveDialog.vue:47 - 原因必填只 toast，不聚焦 textarea、不标红（focus first error on submit）
web/src/components/doc/ApproveDialog.vue:61 - 用 maxlength+show-word-limit 替代错误反馈，必填态与备注态共用同一控件（Errors inline next to fields）
web/src/components/doc/ApproveDialog.vue:62 - placeholder「必填，请说明原因」无示例、无「…」（Placeholders show example pattern）
web/src/components/doc/ApproveDialog.vue:68 - 提交按钮无键盘快捷键（Cmd+Enter）（keyboard handlers）
web/src/components/doc/ApproveDialog.vue:60 - 表单与弹窗无 aria 属性；el-alert 无 aria-live（Async updates need aria-live）
web/src/components/doc/ApproveDialog.vue:57 - 提示语为长句警告，未给出「下一步是什么」的可执行指令（Error messages include fix/next step）
web/src/components/doc/ApproveDialog.vue:27 - 自实现 computed visible 双向绑定，与 QuickCreateDialog/PushDialog 直接用 ref+defineExpose 的方式不统一（重复实现）
```

### `web/src/components/doc/RelatedDocs.vue`

```
web/src/components/doc/RelatedDocs.vue:110 - 标题硬编码「关联单据（采购线）」，销售合同复用时线别错误（一致性）
web/src/components/doc/RelatedDocs.vue:113 - 标题硬编码「已下单金额汇总」，与 32-43 行同时映射 sales_order_amount/stock_out_amount 的多义口径矛盾（一致性）
web/src/components/doc/RelatedDocs.vue:96 - 404 与 500 一律静默为「接口暂不可用」，真实服务故障不可见、无重试（Error messages include fix/next step）
web/src/components/doc/RelatedDocs.vue:24 - toLocaleString('zh-CN', …) 硬编码金额（Intl.NumberFormat）
web/src/components/doc/RelatedDocs.vue:24 - fmtMoney 未处理 NaN（与 MasterTablePage:229 同函数却少一个分支），脏数据会渲染 "NaN"（重复实现 + 健壮性）
web/src/components/doc/RelatedDocs.vue:117 - 表格无 max-height、无 tabular-nums（Large lists；font-variant-numeric）
web/src/components/doc/RelatedDocs.vue:27 - fmtDate 字符串切片硬编码日期格式（Intl.DateTimeFormat）
web/src/components/doc/RelatedDocs.vue:80 - 汇总用 inline <b> + 红色样式，编号规则与金额列右对齐口径不一致（detail execution）
web/src/components/doc/RelatedDocs.vue:112 - summaryText() 在渲染中做对象归一化遍历，每次渲染重算（No layout reads in render；应 computed）
```

### `web/src/components/doc/ContractDetailDrawer.vue`

```
web/src/components/doc/ContractDetailDrawer.vue:23 - toLocaleString('zh-CN', …) 硬编码金额（Intl.NumberFormat）
web/src/components/doc/ContractDetailDrawer.vue:57 - 合同状态直接渲染英文 status 码，旁边列表页用 DocStatusTag，同页两种状态语汇（一致性）
web/src/components/doc/ContractDetailDrawer.vue:52 - el-drawer 缺 overscroll-behavior: contain（overscroll-behavior: contain in modals/drawers）
web/src/components/doc/ContractDetailDrawer.vue:53 - 两个 try 串行：fetchContract 失败后仍在 loading 中显示空白，无错误态（Handle empty states）
web/src/components/doc/ContractDetailDrawer.vue:68 - 行项表 max-height=240 无 tabular-nums、无固定列，数量列宽 90 不放等宽数字（font-variant-numeric）
web/src/components/doc/ContractDetailDrawer.vue:78 - 数量列 {{ row.qty ?? '—' }} 原样渲染，无按单位精度格式化与千分位（数字列口径不一）
web/src/components/doc/ContractDetailDrawer.vue:90 - 关联单据表 max-height=200，行数多时滚动区过窄；同样缺 tabular-nums（数字列口径）
web/src/components/doc/ContractDetailDrawer.vue:20 - fmtMoney 空值返回 '0.00'，与 RelatedDocs:22 返回 '—' 冲突（同模块内空值规则自相矛盾）
web/src/components/doc/ContractDetailDrawer.vue:52 - 抽屉缺 aria 属性；表格无 caption/summary 语义（semantic HTML before ARIA）
```

---

## 2. 组件级重复/可复用性分析

| # | 重复模式 | 出现位置（行号） | 抽象建议 | 抽取代价 |
|---|---|---|---|---|
| D1 | `fmtMoney` 金额格式化 | `web/src/components/MasterTablePage.vue:226-230`、`web/src/components/doc/DocListPage.vue:253-257`、`web/src/components/doc/DocItemsTable.vue:82-87`、`web/src/components/doc/RelatedDocs.vue:21-25`、`web/src/components/doc/ContractDetailDrawer.vue:19-24`；模块外另有 `web/src/views/ContractsView.vue:656`、`web/src/views/DashboardView.vue:91`、`web/src/views/purchase/OrderList.vue:30`、`web/src/views/sales/OrderList.vue:32` | 抽 `web/src/utils/format.ts`：`fmtMoney(v, { blank: '—' \| '0.00' })`，内部持有单例 `Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })` | **低**（纯函数、无状态、无 UI 耦合）。收益高：一次消除 9 份实现与 2 种空值口径；前置条件是先定死空值规则 |
| D2 | `fmtDate` / 日期默认值 | `web/src/components/doc/DocListPage.vue:259-261`、`web/src/components/doc/RelatedDocs.vue:27-29`、`web/src/components/doc/DocFormPage.vue:108`、`web/src/components/doc/PushDialog.vue:51`、`web/src/components/doc/PushDialog.vue:106` | 并入 D1：新增 `fmtDate()` 与 `todayLocal()`（替换 `toISOString().slice(0,10)`） | **低**。顺带修掉两处 UTC 日期 bug |
| D3 | 分页状态机（`page`/`pageSize`/`load`/`resetQuery`/`v-if="total > pageSize"`） | `web/src/components/MasterTablePage.vue:44-45,137-144,310-312`、`web/src/components/doc/DocListPage.vue:112-113,175-186,494-498`、`web/src/components/TreeMasterPage.vue:50-63` | 抽 `web/src/composables/usePagedList.ts`（page、pageSize、total、query、queryParams、load、reset） | **中**。每页省 10-15 行，但 `extraFilters` / `include_disabled` / `status` 口径各异需参数化；回归面覆盖 5 个主数据页 + 7 类单据列表 |
| D4 | 状态 → 颜色/文案映射 | `web/src/components/doc/DocStatusTag.vue:17-23`、`web/src/components/MasterTablePage.vue:90-96,284-289`、`web/src/components/TreeMasterPage.vue:204,217-219`；`web/src/components/doc/DocListPage.vue:320-328` 是同一状态枚举的另一份投影 | 把 `DOC_STATUS`（code → { text, type }）提到 `web/src/constants/docStatus.ts`，`DocStatusTag` 与三处列表共同消费；`canSubmit/canApprove` 也读同一枚举 | **低-中**。改动集中在渲染层，风险低；真实收益是"新增单据状态只改一处" |
| D5 | 筛选区（关键词 + 状态 + 日期区间 + 重置） | `web/src/components/MasterTablePage.vue:252-277`、`web/src/components/doc/DocListPage.vue:390-438`；模块外 `web/src/views/stock/BalanceView.vue`、`web/src/views/master/UserView.vue` | 抽 `FilterToolbar.vue`（自定义筛选项走 slot，统一 12px 行距 / Enter 提交 / 重置语义） | **中-高**。各页筛选集差异大，过度抽象会退化成"传 8 个 props"；建议只抽 CSS 与 Enter 提交约定，不抽 DOM 结构 |
| D6 | 卡片头（title + subtitle + 右上操作）及其样式 | `web/src/components/MasterTablePage.vue:239-250`（样式 `:369-374`）、`web/src/components/TreeMasterPage.vue:180-192`（样式 `:255-257`）、`web/src/components/doc/DocListPage.vue:372-388`（样式 `:556-559`）、`web/src/components/doc/DocFormPage.vue:297-312`（样式 `:387-390`） | 抽 `PageCardHeader.vue`（含 `.head/.title/.subtitle` 三件套） | **低-中**。省约 60 行重复 CSS，视觉一致性收益明显；需回归 4 个壳组件 |
| D7 | 详情抽屉 | `web/src/components/doc/DocListPage.vue:502-548`（内置）与 `web/src/components/doc/ContractDetailDrawer.vue:51-101` | 抽 `DocDetailDrawer.vue`（descriptions + 行项表 + 变更历史 + 具名插槽） | **中-高**。两者插槽契约与数据源不同；且 `DocListPage` 内置抽屉在生产中无任何父页面接管（`@view`、`detail-extra` grep 均 0 命中），建议先删内置抽屉、改由父页面提供，再做抽象 |
| D8 | `el-form` 命令式校验（无 `rules`/无 `validate()`） | `web/src/components/MasterTablePage.vue:166-172`、`web/src/components/TreeMasterPage.vue:100-106`、`web/src/components/QuickCreateDialog.vue:61-72`、`web/src/components/doc/DocFormPage.vue:157-228`、`web/src/components/doc/PushDialog.vue:155-179`、`web/src/components/doc/ApproveDialog.vue:46-52` | 不是"抽组件"而是补能力：每个表单加 `ref` + `rules` + `validate()`，配 `validateForm()` 统一聚焦首个错误 | **中**。改动面 6 个组件，但这是本模块最大的可用性缺口，收益最高 |
| D9 | 无标签内联控件（表格单元格 / 弹窗内 textarea） | `web/src/components/doc/DocItemsTable.vue:241,262,271,281,293`、`web/src/components/doc/PushDialog.vue:263,269`、`web/src/components/doc/ApproveDialog.vue:61` | 抽 `<CellInput>` / `<CellAmount>` 包装（内置 `aria-label`、`inputmode`、右对齐 + tabular-nums） | **中**。单元格是无 label 控件的重灾区，包装层可一次解决可访问性 + 数字口径两件事 |
| D10 | `el-pagination` 属性块（`layout` + 内联箭头 `@current-change`） | `web/src/components/MasterTablePage.vue:310-312`、`web/src/components/doc/DocListPage.vue:494-498`；模块外 `web/src/views/master/UserView.vue:254-255`、`web/src/views/system/SystemView.vue:321,365`、`web/src/views/stock/BalanceView.vue:339-343` | 抽 `<ListPager>`（统一 `page-sizes`） | **低**。每页省 3-6 行；顺带消除"`MasterTablePage`/`TreeMasterPage` 无 sizes、`DocListPage` 有 `[10,20,50,100]`"的不一致 |

---

## 3. 该模块的 5 维评分与证据

**综合均分 5.0 / 10**（生产 ERP 壳组件：功能覆盖完整、设计方向清楚，但"数据密集 + 长时间高频使用"场景下的细节欠债明显；按 critique 规则取**最差持续档位**，不做维度间平均拔高）

### 维度 1 · 哲学一致性 — 6 / 10（Functional）

**方向明确且一致**：全部是 Element Plus 卡片 + `size="small"` 密度 + 权限点驱动的按钮可见性；`web/src/components/doc/DocListPage.vue:141-159` 的 `queryParams(includePage)` 让列表与导出共用同一份筛选口径（注释直接指向 AC-V2-40），是本模块最好的"单一口径"实践；`web/src/components/doc/DocStatusTag.vue:17-23` 明确声明状态字典与后端 `app/models_doc.DOC_STATUS` 对齐。

**同一语义存在多套规则**：
- 空金额一会 `—`（`web/src/components/MasterTablePage.vue:227`、`web/src/components/doc/DocListPage.vue:254`、`web/src/components/doc/RelatedDocs.vue:22`）一会 `0.00`（`web/src/components/doc/DocItemsTable.vue:83`、`web/src/components/doc/ContractDetailDrawer.vue:20`）。
- 状态标签三套实现：`web/src/components/doc/DocStatusTag.vue:17`、`web/src/components/MasterTablePage.vue:284`、`web/src/components/TreeMasterPage.vue:217`。
- 状态码硬编码散落：`web/src/components/doc/DocListPage.vue:320-328`。
- 同组件内自相矛盾：`web/src/components/TreeMasterPage.vue:242` 允许停用有子节点的父节点，`:345` 又禁止父节点被选中（注释称"父节点禁用，只能选叶子"）。
- 合同状态在 `web/src/components/doc/ContractDetailDrawer.vue:57` 直接渲染英文 `status` 码，合同列表页用中文标签。

因此判 6 而非 7：方向统一，但"同一个数字/状态在相邻两个界面有不同说法"。

### 维度 2 · 视觉层级 — 6 / 10（Functional）

**正向证据**：标题/副标题层级清楚，`web/src/components/doc/DocFormPage.vue:301-303` 把「编辑采购申请单 + 单号 + 状态 tag」正确排在一行；金额列在 `web/src/components/doc/DocListPage.vue:460`、`web/src/components/doc/DocItemsTable.vue:276`、`web/src/components/doc/ContractDetailDrawer.vue:83`、`web/src/components/doc/RelatedDocs.vue:128` 均 `align="right"`，是金额可扫读的基础；`web/src/components/doc/DocFormPage.vue:314-317` 用两个 `el-alert` 显式压制「不可编辑」「已过账」两种危险状态，优先级处理正确。

**扣分证据**：
- **全模块 0 处 `font-variant-numeric: tabular-nums`**（全项目 grep 无命中），20 行金额/数量逐列比对时数字宽度跳动。
- `web/src/components/doc/DocListPage.vue:472` 操作列固定 320px 内平铺最多 9 个同权重 `link` 按钮（`:474-488`），行内没有主次。
- `web/src/components/MasterTablePage.vue:243-244` 标题 15px 与副标题 12.5px 仅差 2.5px 且同为灰色系，主次几乎不可辨。
- `web/src/components/doc/DocItemsTable.vue:266` 的橙色 `integerHint` 直接插在数量单元格内，在垂直方向形成第二优先级噪声。

判 6：金额对齐的骨架是对的，但数字列与操作列的"可扫读性"没做。

### 维度 3 · 细节执行 — 4 / 10（Broken → Functional 之间）

本模块最弱的一维，问题逐条可复现：

- **6 处表单全部用 `ElMessage.warning` 做校验提示**，无一处 `el-form` 行内错误、无一处聚焦首个错误字段：`web/src/components/MasterTablePage.vue:169`、`web/src/components/TreeMasterPage.vue:103`、`web/src/components/QuickCreateDialog.vue:64,66,70`、`web/src/components/doc/DocFormPage.vue:159,165,169,176,180,189`、`web/src/components/doc/PushDialog.vue:158,164,168,173,177`、`web/src/components/doc/ApproveDialog.vue:48`。对每天几十次录入的 ERP 这是持续性摩擦。
- **UTC 日期 bug**：`web/src/components/doc/DocFormPage.vue:108`、`web/src/components/doc/PushDialog.vue:51` 与 `:106` 用 `new Date().toISOString().slice(0, 10)` 取"今天"，东八区 00:00–08:00 会默认成前一天，直接产生错误单据日期。
- **空值与零不可辨**：`web/src/components/doc/DocItemsTable.vue:86` 与 `web/src/components/doc/ContractDetailDrawer.vue:20` 在空值/非法值时返回 `'0.00'`，与同模块 `web/src/components/doc/RelatedDocs.vue:22` 的 `'—'` 冲突。
- **`NaN` 会渲染到界面**：`web/src/components/doc/RelatedDocs.vue:24` 的 `fmtMoney` 是 `web/src/components/MasterTablePage.vue:229` 的孪生实现，却少了 `Number.isNaN(n) ? String(v) : …` 分支。
- **占位符与文案规范**：`web/src/components/doc/DocListPage.vue:402`、`web/src/components/doc/DocItemsTable.vue:241`、`web/src/components/doc/PushDialog.vue:219,227`、`web/src/components/doc/ApproveDialog.vue:62`、`web/src/components/QuickCreateDialog.vue:96,99` 的 placeholder 全部无「…」结尾、无示例格式。

判 4：不是"风格不够美观"，而是数字口径错误、默认日期错误、错误定位缺失三类硬缺陷叠加。

### 维度 4 · 功能性 — 4 / 10（Broken → Functional 之间）

**能用，但"长时间高频使用"的关键路径缺保护**：

- **静默丢数据**：`web/src/components/doc/DocFormPage.vue:271` 的 `back()` 直接 `router.push({ name: props.listRoute })`；全项目 `beforeunload` / `onBeforeRouteLeave` 零命中，`web/src/router/index.ts:299` 的全局守卫只做登录/强制改密/权限三类判断。录入几十行后误点「返回列表」即丢失，无任何提示。`web/src/components/TreeMasterPage.vue:73` 的 `onSelect` 同样直接覆盖右侧表单。
- **错误态缺失**：`web/src/components/doc/DocListPage.vue:196-200` 先置 `drawerVisible = true` 再 `fetchDoc`，失败后抽屉永久空白；`web/src/components/doc/ContractDetailDrawer.vue:53` 的 `v-loading` 挂在 `v-if="contract"` **之外**，失败只表现为空白；`web/src/components/TreeMasterPage.vue:50-63` 是 `try/finally` 无 `catch`，接口失败留下空树 + 未捕获 Promise rejection。
- **行级反馈不可辨**：`web/src/components/doc/DocListPage.vue:279` 的单一 `actionLoading` 同时驱动所有行的「提交」按钮 loading（`:477`），用户在 20 行里无法确认操作的是哪一行。
- **分页可见性**：`web/src/components/doc/DocListPage.vue:494` 与 `web/src/components/MasterTablePage.vue:310` 用 `v-if="total > pageSize"` 隐藏整条分页器，"共 N 条"随之消失，也失去了修改每页条数的入口。
- **规模与渲染**：`web/src/components/doc/DocListPage.vue:496` 的 `page-sizes` 含 100，理论单页可达 100 行（>50 阈值），却无虚拟化、无固定表头、无 `max-height`（`web/src/components/doc/DocListPage.vue:442`、`web/src/components/MasterTablePage.vue:279`、`web/src/components/doc/DocItemsTable.vue:236`），列头与合计行都会滚出视口；`web/src/components/doc/DocItemsTable.vue:243` 每行一个 `el-select`，20 行即 20 个选项容器。
- **提交互斥**：`web/src/components/doc/DocFormPage.vue:374-377` 两个保存按钮共用 `saving`，点击其一不会锁定另一个。

判 4：核心流程可用（权限门控、`v-loading`、状态机映射、下推剩余量校验都正确），但丢数据、丢错误、丢定位三类问题会随使用时长放大。

### 维度 5 · 创新性 — 5 / 10（Competent and unmemorable · 属"恰当的保守"）

**有真实业务价值的三处非模板解法，值得计分**：
- `web/src/components/QuickCreateDialog.vue`（配合 `web/src/components/doc/DocItemsTable.vue:160-181` 与 `web/src/components/MasterTablePage.vue:330-350`）把"新增主数据"收敛为不跳转的弹窗并回填当前行，注释 `web/src/components/QuickCreateDialog.vue:3-8` 明确对应 BR-V2.1-10"禁止跳转丢失未保存表单"。
- `web/src/components/doc/ContractDetailDrawer.vue:2-8` 以"不离开表单核对合同金额与行项"为设计前提，同样针对丢数据痛点。
- `web/src/components/doc/PushDialog.vue:83-85,136-153` 用"剩余可下推量"预填并逐行钳制（`:160-171`），把下推这类易错操作做成"勾选 + 可改量"，比常见的一键全推更安全。

**其余为默认形态组合**：11 个文件里 8 个（MasterTablePage / TreeMasterPage / DocListPage / DocFormPage / DocItemsTable / DocStatusTag / ApproveDialog / RelatedDocs）是 Element Plus 默认组件的直接拼装，未为"数据密集 + 高频"引入任何结构性改进——无键盘工作流（无 Ctrl+S / Cmd+Enter / 无 tab 流优化）、无批量操作、无行项粘贴导入、无列宽持久化、无筛选记忆。

判 5：按 critique 口径，"恰当的保守"不惩罚也不加分，本模块的创新集中在"防丢数据"这一条主线上，未形成第二处记忆点。

---

## 4. Keep / Fix / Quick wins 三张清单

### Keep（3-5 条 · 已成立的做法，重构中不要破坏）

1. `web/src/components/doc/DocItemsTable.vue:199-213` 的 `summaryMethod` 通过 `c.property === 'amount'` 语义定位合计列，并在注释里记录了旧硬编码 `i === 6` 的踩坑原因——保留这套"按语义定位、不留索引常量"的写法。
2. `web/src/components/QuickCreateDialog.vue` 全项目唯一的"现场快建 + 回填"入口（被 `web/src/components/MasterTablePage.vue:363` 与 `web/src/components/doc/DocItemsTable.vue:311` 复用），是模块内最有效的防数据丢失设计；抽公共件时不要拆散它的 `open()` / `created` 契约。
3. `web/src/components/doc/DocListPage.vue:141-159` 的 `queryParams(includePage)` 让列表与导出共用一份筛选口径（注释指向 AC-V2-40）；任何分页 composable 重构都必须保留这个单一出口。
4. `web/src/components/doc/DocFormPage.vue:366` 的 `#items` 具名插槽使 `web/src/views/stock/TakeForm.vue` 能整体替换行项区而不分叉表单壳——插槽契约是这套壳组件可复用的关键，扩展时保持向后兼容。
5. `web/src/components/doc/DocStatusTag.vue:25` 的 `MAP[props.status] ?? { text: props.status || '—', type: 'info' }` 未知值兜底：后端新增状态时列表不崩、不显示空白。
6. `web/src/components/doc/DocListPage.vue:330-344`（配套 `web/src/components/doc/PushDialog.vue:334-343` 的注释口径）`pushRemainField` 的防御性设计：仅在显式传入字段且字段明确为 0 时才隐藏「下推」，字段缺失时不吞入口——把"接口异常"与"业务规则"区分开了，值得保留。

### Fix（P0/P1 · 按"每分钟修复换回的可用性"排序）

1. `web/src/components/doc/DocFormPage.vue:271` + `:374-377` — 加 `onBeforeRouteLeave` 脏检查（提交前对 `items`/`header` 做初值快照比对）与提交期间双按钮互锁。这是全模块唯一会**静默丢数据**的路径，优先级最高。
2. `web/src/components/doc/DocFormPage.vue:108`、`web/src/components/doc/PushDialog.vue:51,106` — 用本地日期格式化（`todayLocal()`）替换 `toISOString().slice(0, 10)`，消除"默认单据日期早一天"。
3. `web/src/components/doc/DocItemsTable.vue:86`、`web/src/components/doc/ContractDetailDrawer.vue:20` — 空值改为 `'—'`，与 `web/src/components/doc/RelatedDocs.vue:22` / `web/src/components/doc/DocListPage.vue:254` 对齐；同时给 `web/src/components/doc/RelatedDocs.vue:24` 补 `Number.isNaN` 分支。
4. `web/src/components/doc/DocListPage.vue:279,472` — `actionLoading` 改为记录 `actionRow.id` 的行级 loading；操作列改为「查看 / 编辑 / 提交 / 审核」+ 一个「更多」下拉，把 320px 压回 200px 以内。
5. `web/src/components/MasterTablePage.vue:168`、`web/src/components/TreeMasterPage.vue:102`、`web/src/components/QuickCreateDialog.vue:64` — 给表单加 `ref` + `rules`，校验改走 `formRef.validate()`，在 catch 中 `scrollIntoView` 首个错误字段，替换 `ElMessage.warning`。
6. `web/src/components/doc/DocListPage.vue:196-200`、`web/src/components/doc/ContractDetailDrawer.vue:53`、`web/src/components/TreeMasterPage.vue:50-63` — 补错误态与重试按钮（"加载失败，点击重试"），并给 `TreeMasterPage.load()` 补 `catch`。
7. `web/src/components/MasterTablePage.vue:297-299` — 「查看」按钮在 `canEdit=false` 时走的仍是可编辑表单（仅按钮文案变化），需按 `editable` 降级为只读渲染，或明确提示不可编辑。
8. `web/src/components/doc/DocListPage.vue:472` 操作列补 `min-width` 下限 + 固定列宽预算，避免窄屏横向溢出（当前 `web/src/components/MasterTablePage.vue:295` 的 220px 与 `web/src/components/doc/DocItemsTable.vue:239-297` 的列宽预算都靠固定值硬撑）。

### Quick wins（3-5 条 · 5-15 分钟级 · 性价比最高）

1. 在 `web/src/style.css` 增加全局声明 `.el-table .cell { font-variant-numeric: tabular-nums; }`，一次覆盖 `web/src/components/doc/DocListPage.vue:460`、`web/src/components/doc/DocItemsTable.vue:276`、`web/src/components/doc/PushDialog.vue:252-259`、`web/src/components/doc/ContractDetailDrawer.vue:77-85`、`web/src/components/doc/RelatedDocs.vue:128`、`web/src/components/MasterTablePage.vue:281` 的所有数字列。
2. 给 6 处弹窗/抽屉统一补 `overscroll-behavior: contain`：`web/src/components/doc/DocListPage.vue:502`、`web/src/components/doc/ContractDetailDrawer.vue:52`、`web/src/components/MasterTablePage.vue:314`、`web/src/components/QuickCreateDialog.vue:92`、`web/src/components/doc/PushDialog.vue:214`、`web/src/components/doc/ApproveDialog.vue:56`。
3. 给图标按钮补 `aria-label`（保留 `title` 作为悬停说明）：`web/src/components/MasterTablePage.vue:337,348`、`web/src/components/doc/DocItemsTable.vue:249`。
4. 给内联控件补 `aria-label`（表格单元格无表头关联）：`web/src/components/doc/DocItemsTable.vue:241,262,271,281,293`、`web/src/components/doc/PushDialog.vue:263,269`、`web/src/components/doc/ApproveDialog.vue:61`。
5. 把 `web/src/components/doc/DocListPage.vue:494` 与 `web/src/components/MasterTablePage.vue:310` 的 `v-if="total > pageSize"` 去掉（或改 `v-if="total > 0"`），让"共 N 条"始终可见；同时给 `MasterTablePage.vue:310` 补 `:page-sizes` 与 `@size-change`，与 `DocListPage.vue:496` 对齐。
6. 把 `web/src/components/doc/RelatedDocs.vue:112` 的 `summaryText()` 提为 `computed`，消除每次渲染的对象归一化遍历。

---

## 5. 全局扫描结论（本次复核，含对既有结论的修正与扩展）

- `aria-label` / `aria-live` / `aria-hidden`：全项目 **0 命中**（确认原结论）。
- `prefers-reduced-motion`：**0 命中**（确认）。
- `font-variant-numeric` / `tabular-nums`：**0 命中**（原结论未提及，本次新增）。
- `overscroll-behavior`：**0 命中**（原结论未提及，本次新增）。
- `content-visibility` / `el-table-v2` / 任何虚拟化方案：**0 命中**；`max-height` 仅 5 处（`web/src/views/ContractsView.vue:1055`、`web/src/components/doc/ContractDetailDrawer.vue:68,90`、`web/src/components/doc/PushDialog.vue:238`、`web/src/views/stock/TakeForm.vue:313`），列表主表全部无高度约束。
- `toLocaleString('zh-CN', …)`：**实为 9 处**，比原结论多 4 处 —— `web/src/components/MasterTablePage.vue:229`、`web/src/components/doc/DocListPage.vue:256`、`web/src/components/doc/DocItemsTable.vue:86`、`web/src/components/doc/RelatedDocs.vue:24`、`web/src/components/doc/ContractDetailDrawer.vue:23`，外加 `web/src/views/ContractsView.vue:656`、`web/src/views/DashboardView.vue:91`、`web/src/views/purchase/OrderList.vue:30`、`web/src/views/sales/OrderList.vue:32`。
- `Intl.NumberFormat` / `Intl.DateTimeFormat`：**0 命中**（全部走 `toLocaleString` 或字符串切片）。
- 无 `web/src/utils/`、`web/src/composables/`、`web/src/hooks/`、`web/src/constants/` 目录（`glob` 无结果）；`web/src/style.css` 仅 11 行，无全局数字/焦点/暗色/动效约定。
- `beforeunload` / `onBeforeRouteLeave`：**0 命中**；`web/src/router/index.ts:299` 的全局守卫只处理「未登录 → /login」「拉取 /auth/me」「must_change_pwd 强制改密」「meta.perm 不满足 → /403」四件事，不含未保存离开保护。
- 死 prop 复核：`permView` 只在 `web/src/components/MasterTablePage.vue:28`、`web/src/components/TreeMasterPage.vue:26` 声明，组件体内从未引用；而 7 个调用页均传值（`web/src/views/master/CustomerView.vue:38`、`OrgView.vue:21`、`ProductTypeView.vue:16`、`ProductView.vue:45`、`SupplierView.vue:40`、`UomView.vue:25`、`WarehouseView.vue:26`）→ 查看权限实际未生效。
- 死插槽/死事件复核：`web/src/components/doc/DocListPage.vue:13`（注释）、`:100-105`（`view`/`push` 事件定义）、`:526`（`detail-extra` 插槽）所宣传的能力，全项目 grep `@view` 与 `detail-extra` 均 **0 命中**（`@push` 有 4 处命中：`web/src/views/purchase/RequestList.vue:63`、`purchase/OrderList.vue:62`、`sales/RequestList.vue:61`、`sales/OrderList.vue:75`）→ 内置详情抽屉在生产中永远走内部实现，父页面无法接管。

---

## 附：判定口径说明

- 规则名取自 `D:\dsh\hetong\.dsh\skills\web-design-guidelines\references\guidelines.md` 的原文条目（Accessibility / Focus States / Forms / Animation / Typography / Content Handling / Images / Performance / Navigation & State / Touch & Interaction / Safe Areas & Layout / Dark Mode & Theming / Locale & i18n / Hydration Safety / Hover & Interactive States / Content & Copy / Anti-patterns）。
- 5 维评分取自 `critique` 技能框架（Philosophy consistency / Visual hierarchy / Detail execution / Functionality / Innovation），每维 0-10，证据必须落到文件与行号；评分取"最差持续档位"，不做维度间平均拔高，不做 grade inflation。
- 本报告面向内网 ERP（数据密集、长时间高频使用），评判权重偏效率、密度、一致性、可用性，未把"营销页式视觉表现力"计入扣分项。
- 所有行号均为本次实际读取文件内容的行号，未做推测；跨文件引用的行号已标注对应文件名。
