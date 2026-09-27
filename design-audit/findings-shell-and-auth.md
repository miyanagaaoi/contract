# 框架与交互基线审查（shell / 路由 / store）

审查范围：`web/src/style.css`、`main.ts`、`App.vue`、`layout/AppLayout.vue`、`components/TopBar.vue`、`components/MenuTree.vue`、`views/LoginView.vue`、`ChangePasswordView.vue`、`ForbiddenView.vue`、`SettingsView.vue`、`router/index.ts`、`stores/auth.ts`

扩展取证（判定所必需）：`web/index.html`、`web/src/api.ts`、`web/package.json`、`web/vite.config.ts`、`app/permissions.py`、`deploy/nginx.conf`、`node_modules/element-plus@2.9.3` 实现。

标尺：Vercel Web Interface Guidelines 钉版 + critique 5 维框架。

---

## 1. 逐文件合规问题清单

### web/index.html ✓ 主要项通过
- `index.html:5` viewport 无 `maximum-scale`/`user-scalable=no` ✓；`lang="zh-CN"` ✓
- `index.html:3-7` 缺 `<meta name="theme-color">`，`html` 未声明 `color-scheme`（Dark Mode & Theming）※内网桌面影响极低，仅登记不计分

### web/src/style.css
- `style.css:9` 字体栈 `'Helvetica Neue',Helvetica` 打头，未声明 CJK 优先/无字体加载，中文字面随平台漂移（Typography）
- `style.css:11` 全局无 `font-variant-numeric: tabular-nums`，而数值列在 10 处 `toLocaleString('zh-CN')`（Typography）
- `style.css:11` 无 `prefers-reduced-motion` 兜底，EP 菜单展开/下拉过渡无降级（Animation）
- `style.css:11` 未声明 `color-scheme`，深色侧栏 + 浅色文档混搭（Dark Mode & Theming）
- `style.css:11` 无 `:root` 设计令牌（全 `web/src` 对 `var(--el-*)`/自定义变量命中 0）
- `style.css:10` `body` 背景 `#f5f7fa` 与 `AppLayout.vue:58` `.main` 重复，且登录/改密页被全屏渐变完全覆盖
- `style.css:1-6` 与 `App.vue:12-18` 非 scoped style 完全重复的全局 reset

### web/src/main.ts
- `main.ts:6,14-16` `import * as ElementPlusIconsVue` 后 `Object.entries` 全量全局注册 **294 个图标**，Rollup 无法 tree-shake，图标集整体进 entry chunk；`vite.config.ts` 无 `manualChunks`（Performance）
- `main.ts:5,20` zh-cn locale 注入 ✓；`main.ts:18-19` 插件顺序 ✓

### web/src/App.vue
- `App.vue:12-18` 非 scoped style 重复 `style.css:1-6` 的 reset（重复实现）
- `App.vue:9` 根组件仅 `router-view`，无 skip link / 无 `h1` 语义容器（Headings hierarchical / skip link）

### web/src/layout/AppLayout.vue
- **`AppLayout.vue:16`** `activeMenu = route.path`，而菜单 index 为列表路径（`app/permissions.py:149-152,161-169` 如 `/purchase/orders`），`router/index.ts:116-129,137-150,159-172` 等所有 `:id`/`new`/`:id/edit` 路由无前缀匹配 → **进详情/编辑页侧栏高亮全丢**（Navigation & State / Visual hierarchy）★
- `AppLayout.vue:24-25` `el-menu` 的 `background-color`/`text-color`/`active-text-color` 在 element-plus@2.9.3 已 `@deprecated`（`menu.mjs:63-74`），应改 CSS 变量
- `AppLayout.vue:24,48` `#1f2d3d` 在 props 与 `.aside` 两处硬编码
- `AppLayout.vue:21` `el-aside width="220px"` 写死，无折叠/无断点；三层面板（资料库>基础信息>商品类型）下第三层文本区约 150px（密度/Layout）
- `AppLayout.vue:22` `<div class="brand">` 承载应用名，整壳无 `h1`（Headings hierarchical）
- `AppLayout.vue:48` 深色侧栏无 `color-scheme`（Dark Mode & Theming）
- `AppLayout.vue:58` `.main padding:16px` 全文一档，卡片/表格/工具栏无层级差
- `AppLayout.vue:47-58` 本文件 0 个 `@media`（全 `web/src` 仅 `ContractsView.vue:1240` 一处）

### web/src/components/TopBar.vue
- **`TopBar.vue:70`** `outline: none` 且无 `:focus-visible` 替代；该 span 由 EP 渲染为 `role="button" tabindex=0`（`dropdown2.mjs:70-71`），**键盘用户看不到焦点**（Focus States / Anti-patterns）★
- `TopBar.vue:69` `cursor:pointer` 但无 `:hover` 反馈；全 `web/src` 对 `:hover` 命中为 0（Hover & Interactive States）
- `TopBar.vue:42` `<el-icon class="caret"><ArrowDown /></el-icon>` 装饰图标缺 `aria-hidden="true"`（Decorative icons）
- `TopBar.vue:40` 头像首字母 span 未 `aria-hidden`，读屏先读单字（Accessibility）
- `TopBar.vue:35` `.org` 为 flex 子项且无 `min-width:0`/truncate，超长 `org_name` 顶破顶栏（Content Handling）
- `TopBar.vue:36` `roleText` 用 `' / '` 拼接全部角色塞 `el-tag`，无 `max-width`/`+N` 折叠
- `TopBar.vue:72` `font-size:13.5px` 亚像素字号
- `TopBar.vue:47` 修改密码以 dropdown command + `router.push` 导航，非 `<a>`，失去中键/Ctrl+点击
- `TopBar.vue:21-23` 退出二次确认 ✓

### web/src/components/MenuTree.vue
- `MenuTree.vue:15,21` 装饰图标无 `aria-hidden="true"`（Decorative icons）
- `MenuTree.vue:15,21` `<component :is="node.icon">` 图标名来自后端字符串全局注册表，无兜底，新增未注册图标名静默空白（Content Handling）
- `MenuTree.vue:13,20` index 命名空间不一致：父级 `node.key`（"purchase"）、叶子 `node.path`（"/purchase/orders"）；`:path || key` 的兜底在 el-menu router 下会把无 path 的 key 当相对路径 push（Navigation & State）
- `MenuTree.vue:2-8` 菜单不写死、后端裁剪 ✓（Keep）

### web/src/views/LoginView.vue
- `LoginView.vue:55,59` `el-input` 无 `autocomplete` / `name` / `spellcheck=false`（Forms）
- `LoginView.vue:62` 内联错误 `<p class="err">` 无 `role="alert"`/`aria-live="polite"`（Async updates）
- `LoginView.vue:62` 未聚焦首个错误字段（Errors inline / focus first error）
- **`LoginView.vue:92`** `.err` `#f56c6c` on `#fff` @12.5px 对比度实测 **2.90:1**（Contrast，AA 需 4.5:1）★
- `LoginView.vue:91,94` `.sub` 12.5px / `.foot` 11.5px `#909399` on `#fff` 对比度 **3.08:1**（Contrast）★
- `LoginView.vue:64` 按钮 "登 录" 用字面空格做字距，与 `ChangePasswordView.vue:72` "保存" 不一致
- `LoginView.vue:55` placeholder 未以 `…` 结尾、无示例（Placeholders）
- `LoginView.vue:33` `route.query.redirect` 直接 `as string` 后 `replace`，绝对/外域值被吞成 `/`，无白名单
- `LoginView.vue:75` `min-height:100vh` 未用 `dvh`/安全区，无 `touch-action`
- `LoginView.vue:86` `box-shadow: 0 18px 40px rgba(0,0,0,0.25)` 营销页量级投影（Philosophy consistency）
- `LoginView.vue:2` 注释声明"错误不弹窗"，但 `api.ts:45-47` 对带 `detail` 的非 401 错误统一 `ElMessage.error`，500/网络异常时红字+弹窗双通道，注释与实现不一致

### web/src/views/ChangePasswordView.vue
- **`ChangePasswordView.vue:36-37`** `if (detail) ElMessage.error(detail)`：无 `detail` 的失败（超时/5xx/断网）**完全静默**，点保存无任何反馈（Error messages / Functionality）★
- `ChangePasswordView.vue:26,21-28` 校验失败用 `ElMessage.warning` 弹窗，`LoginView.vue:62` 用内联红字，同模块两套错误模式
- `ChangePasswordView.vue:37` 与 `api.ts:45-47` 重复弹同一错误（一次失败两个 toast）
- `ChangePasswordView.vue:43-46` `onLogout` 无二次确认，与 `TopBar.vue:21-23` 冲突（Destructive actions 一致性）
- `ChangePasswordView.vue:60,64,68` 密码框无 `autocomplete="current-password"`/`"new-password"`，无 `name`（Forms）
- **`ChangePasswordView.vue:97`** `.warn`（"首次登录必须先修改初始密码"）@`#e6a23c` on `#fff` 12.5px 对比度实测 **2.19:1**（Contrast）★
- `ChangePasswordView.vue:96` `.sub` 12.5px `#909399` 对比度 3.08:1
- `ChangePasswordView.vue:61,65,69` placeholder 未以 `…` 结尾；密码规则仅在 placeholder/副标题，无提交前实时校验
- `ChangePasswordView.vue:54` 规则以散文给出，无字段级提示与强度反馈
- `ChangePasswordView.vue:82` `min-height:100vh`
- `ChangePasswordView.vue:93` / `LoginView.vue:86` 相同投影，两页唯一被统一复用的视觉决策
- `ChangePasswordView.vue:95` 与 `LoginView.vue:89` `h1` 18px 一致 ✓

### web/src/views/ForbiddenView.vue
- `ForbiddenView.vue:13` 无 `h1`：页面标题是 `<div class="code">403</div>`（Headings hierarchical）
- `ForbiddenView.vue:19-20` 返回首页/上一页用 `el-button` + `router.replace`，非 `<a>`，丢失中键新标签
- `ForbiddenView.vue:36` `.det` 12.5px `#909399` on `#f5f7fa` 对比度实测 **2.87:1**（Contrast）
- `ForbiddenView.vue:34` `letter-spacing:4px` + 64px + 800 + 独有 `#5a6b7d`，营销式大字号页与工具壳不同语域（Philosophy consistency）
- `ForbiddenView.vue:27` `min-height:100vh`
- `ForbiddenView.vue:16` 回显所需权限点 ✓（Keep）

### web/src/views/SettingsView.vue
- `SettingsView.vue:16` active tab 仅存 `ref`，未同步 URL query，四类字典无法深链/刷新保持（URL reflects state）★
- **`SettingsView.vue:99-101`** `onMounted` 的 `Promise.all` 无 `catch`，任一接口失败即 unhandled rejection 且无提示（Error messages）★
- `SettingsView.vue:117,137,160,178` `el-table` 无 `v-loading`/骨架/空态区分，加载中与"无数据"视觉相同（Handle empty states）
- `SettingsView.vue:157,175` 工具栏 `el-input` 仅 placeholder，无 label/`aria-label`（Form controls need label）
- `SettingsView.vue:32,50,60,66,72,92` `catch` 再 `ElMessage.error(apiError(e))`，与 `api.ts:45-47` 拦截器重复弹同一错误
- `SettingsView.vue:145,183` 删主体/删行项类型无确认，而 `:70` 删标签有确认（Destructive actions 一致性）
- **`SettingsView.vue:42-43,83-88,150,186`** 表内本地编辑+手动保存，无 `beforeunload`/路由守卫，**切菜单即静默丢弃**（Warn before navigation with unsaved changes）★
- `SettingsView.vue:96` 兜底文案"操作失败"，无原因/无下一步（Error messages include fix/next step）
- `SettingsView.vue:107` 卡片标题用 `<b>系统设置</b>`，非 `h2`/`h3`
- `SettingsView.vue:195` `.gray` 13px `#909399` on `#fff` 对比度 3.08:1；类名以颜色命名
- `SettingsView.vue:108,156,157,174,175` 内联 style 与 `.mb/.mt`(193-195) 混用
- `SettingsView.vue:113,135,155,173` Tab 命名语域不一："合同类型（编号码）"/"我方公司（主体码）"/"标签管理"/"行项类型字典"
- `SettingsView.vue:144,163,182` "操作"列宽 80/140/80 三套值
- `SettingsView.vue:149` "＋ 增加主体"全角加号，与 `:158`/`:176` "新增" 两套新增范式
- `SettingsView.vue:180` `v-model="items[$index]"` 按索引双向绑定，结构脆弱
- `SettingsView.vue:26` `return ElMessage.warning(...)` 从 async void 返回值
- `SettingsView.vue:139,142` placeholder 未以 `…` 结尾
- `SettingsView.vue:105` `el-card shadow="never"` 与登录页重投影两种卡片语言

### web/src/router/index.ts
- **`router/index.ts:311-316`** `fetchMe` 的 `catch` 无差别清 token：内网瞬时断网/5xx 也被当未登录踢回登录页，**丢掉当前页与未保存输入**（Functionality）★★
- `router/index.ts:288` `{ path: '/:pathMatch(.*)*', redirect: '/' }`：未知深链静默跳首页
- `router/index.ts:312` 每次导航 `await fetchMe`（`stores/auth.ts:77` 靠 `loaded` 短路），守卫异步期无加载反馈，懒加载 chunk 首次跳转无指示
- `router/index.ts:312` `loaded` 一旦 true 永不再刷新，管理员改名/收权后当前会话菜单与 perm 保持陈旧（服务端仍强校验，风险限于体验）
- `router/index.ts:107` `/settings`→`/system` 保留旧入口 ✓；`:329-331` `document.title` 同步 ✓

### web/src/stores/auth.ts
- `stores/auth.ts:41,57-60` token 真源在 localStorage，state 仅初始化读一次；`api.ts:38` 在 401 时只 `removeItem` 不回写 store，若登录后首个 `/auth/me` 返回 401 会出现 store.token 有值、localStorage 无值的分裂态，`isLoggedIn` 仍为 true（State 一致性）
- `stores/auth.ts:50` `isLoggedIn` 仅判 token 非空，不判有效期
- `stores/auth.ts:41` localStorage 存 JWT，文件 5-6 行已显式声明为内网知情取舍 ✓ 不扣分
- `stores/auth.ts:63-66` 超管恒真 + `perms.includes` 单一判权入口 ✓；`:95-107` logout 全量清态 ✓

**汇总**：本次 11 个文件**无一 ✓ pass**。

**低价值项（已逐条比对，明确不计分）**：placeholder 缺 `…`、缺 `text-wrap: balance`、缺 `theme-color`、三处 `100vh` 未用 `dvh`、无 `touch-action`/`overscroll-behavior`/`-webkit-tap-highlight-color`。全项目 `transition:all` / `onPaste preventDefault` / `autoFocus` / `<div onClick>` / `user-scalable=no` 命中均为 **0** ✓。

---

## 2. 5 维评分与证据（0–10）

- **Philosophy consistency · 5/10** — 三套语域并存：工具壳（`AppLayout.vue:24-25` `#1f2d3d`/`#409eff`）+ 营销式登录卡（`LoginView.vue:79-86` 渐变 `#1f2d3d`→`#33475b` 叠 `0 18px 40px rgba(0,0,0,.25)`）+ 裸 EP 表单页（`SettingsView.vue:105` `shadow="never"`、`:107` `<b>` 标题）。方向有一半，另半页漂移。
- **Visual hierarchy · 5/10** — 外壳无 `h1`（`AppLayout.vue:22` 是 `div`），每页自造标题（`<b>` / 64px `div` / 18px `h1` 三套）；`TopBar.vue:35,36,72` 三处 13px 级灰字并列无主次；`AppLayout.vue:58` 全文一档 16px 内边距。
- **Detail execution · 4/10** — 亚像素字号 13.5/12.5/11.5px（`TopBar.vue:72`、`LoginView.vue:91-94`、`ChangePasswordView.vue:96`）；全站 0 个 `:root`/`var(--el-*)`，17 个裸 hex（`AppLayout.vue:24` 与 `:48` 同一 `#1f2d3d` 重复）；`App.vue:12-18` 重复 `style.css:1-6`；`SettingsView.vue:108/156` 内联 style 与 `.mb/.mt` 混用；"登 录"（`LoginView.vue:64`）与"＋"（`SettingsView.vue:149`）字符级粗糙。
- **Functionality · 5/10** — 主流程可用（`router/index.ts:322-325` 守卫、logout、字典 CRUD）。失分：详情/编辑页侧栏高亮全丢（`AppLayout.vue:16` vs `app/permissions.py:149`）；瞬时断网清 token 踢登录（`router/index.ts:314`）；保存失败静默（`ChangePasswordView.vue:37`）与加载无态（`SettingsView.vue:117`）；键盘焦点被抹（`TopBar.vue:70`）；登录错误不播报（`LoginView.vue:62`）。
- **Innovation · 4/10** — 无一处为"合同+进销存"业务做的设计决策：无命令面板、无键盘优先录入、数值列无 `tabular-nums`（`style.css:11`）、无密度切换、无保存视图，220px 侧栏（`AppLayout.vue:21`）都不可折叠。保守本身正确，但没有一个"赚到"的小动作。

**均值 4.6/10**，无一项达 7（strong = 偶发漂移），本模块是稳定的中等偏下。

---

## 3. Keep / Fix / Quick wins

### Keep（勿改坏）
1. 权限单一真源：`MenuTree.vue:2-8` + `router/index.ts:322-325` + `stores/auth.ts:63-66`，与 `app/permissions.py:304-308` 后端裁剪咬合。
2. `AppLayout.vue:31-35` `el-container direction="vertical"` 注释：把框架陷阱写进代码，最有价值的注释资产。
3. SPA 深链可用：`deploy/nginx.conf:20-22` `try_files` + `router/index.ts:329-331` `document.title`。
4. 破坏性确认范式：`TopBar.vue:21-23` 退出确认、`SettingsView.vue:70` 删除带 `usage_count` 影响面提示，应扩散到 `SettingsView.vue:145,183`。
5. `LoginView.vue:2,62` "错误内联不弹窗"决策 + `ForbiddenView.vue:16` 回显权限点，面向排障的信息设计方向正确。

### Fix（按成本排序）
1. `AppLayout.vue:16` `activeMenu` 改 `route.matched` / 路径前缀最长匹配。
2. `router/index.ts:311-316` 只对 401 清 token；网络类错误保留登录态并提示重试。
3. `TopBar.vue:70` 删 `outline:none` 或补 `.user:focus-visible{outline:2px solid #409eff;outline-offset:2px}`；顺带加 `:hover`。
4. 对比度成组修：正文 `#909399`→`#606266`(6.11:1)；`.err` `#f56c6c`(2.90:1)→`#b02a24`(6.55:1)；`.warn` `#e6a23c`(2.19:1)→`#9a6700`(4.87:1)；涉及 `LoginView.vue:91,92,94`、`ChangePasswordView.vue:96,97`、`ForbiddenView.vue:36`、`SettingsView.vue:195`。
5. `SettingsView.vue:99-101` 加 `catch` + 四张 `el-table`(117/137/160/178) 加 `v-loading` 与空态插槽。

### Quick wins
1. `AppLayout.vue:24-25` 弃用 3 个 deprecated props，改 `--el-menu-bg-color`/`--el-menu-text-color`/`--el-menu-active-color`，顺带消掉 `:48` 的 `#1f2d3d` 重复。
2. 补 4 处 a11y：`TopBar.vue:42`、`MenuTree.vue:15,21` 加 `aria-hidden="true"`；`LoginView.vue:62` 加 `role="alert" aria-live="polite"`。
3. 补表单语义：`LoginView.vue:55` `name`/`autocomplete="username"`/`spellcheck="false"`，`:59` `autocomplete="current-password"`；`ChangePasswordView.vue:60/64/68` 加 `current-`/`new-password`。
4. 字号收敛：删 13.5px（`TopBar.vue:72`）与 11.5px（`LoginView.vue:94`），统一 12/13/14/18；"登 录"→"登录" + `letter-spacing:0.35em`。
5. `SettingsView.vue:16` active 与 query 双向同步，一次同时解决深链与刷新保持。

---

## 4. 设计方向判断

这套 UI 呈现的是「Element Plus 默认后台模板 + 一点手工深色侧栏」的行政管理系统观感，且是**三套语域拼在一个产品里**：工具壳、营销式登录卡、裸 EP 表单页。核心问题不是不够花哨，而是**没有设计决策层**——所有视觉参数都是框架默认值或随手取的近似值。

- **配色**：全模块 17 个裸 hex（`#1f2d3d` `#c0c4cc` `#409eff` `#f5f7fa` `#e4e7ed` `#606266` `#303133` `#ecf5ff` `#d9ecff` `#909399` `#33475b` `#f56c6c` `#e6a23c` `#5a6b7d` `#f2f6fc` `#e4edf7` `#fff`），`web/src` 内 `:root`/`var(--*)` 命中 **0**。这不是"用 EP 主题"，而是把 EP 调色板手工抄了一遍（`#409eff`/`#909399`/`#606266`/`#e4e7ed`/`#f5f7fa` 全是 EP 语义色），导致主题一次不可改、深色侧栏与浅色文档混搭无 `color-scheme`（`style.css:11`）。
- **字体**：`style.css:9` 先西文后中文回退，字面随平台漂移；多档字号夹带 13.5/12.5/11.5px 亚像素档；数据密集页最需要的 `tabular-nums` 缺失，10 处 `toLocaleString('zh-CN')` 数字列因比例字形无法纵向对齐。
- **间距**：唯一被定义的间距是 `AppLayout.vue:58` 的 `padding:16px` 与 `SettingsView.vue:193-194` 的 12px，其余靠 EP 默认与内联 style；侧栏 220px 写死，`@media` 全 `src` 仅 1 处（`ContractsView.vue:1240`），三层面板下第三层约 150px。
- **层级**：外壳无 `h1`（`AppLayout.vue:22` 用 `div`），每页自造标题（`SettingsView.vue:107` `<b>`、`ForbiddenView.vue:34` 64px `div`、`LoginView.vue:89` 18px `h1`）；顶栏 13px 组织名 + small tag + 13.5px 用户名三件灰字并列，无第一层级。
- **密度**：接近"默认 EP"（14px 正文、small 表格），对数据密集偏松；真正的问题是密度不可调且状态不可见——SettingsView 四张表无 loading/空态/错误态，`AppLayout.vue:16` 让详情页丢菜单高亮，长会话持续失去位置感。

**结论**：地基（权限单源、深链、路由守卫、破坏性确认范式）是对的且值得保留；但**配色无令牌、排版无刻度、状态无反馈、焦点不可见**，四件事决定高频长时使用会持续磨人。修复顺序：导航态（`AppLayout.vue:16`）→ 错误与加载态（`router/index.ts:311`、`SettingsView.vue:99`）→ 焦点与对比度（`TopBar.vue:70`、各页 `#909399`/`#f56c6c`/`#e6a23c`）→ 令牌化（17 hex → CSS 变量）。**不建议为观感推翻 EP，建议把 EP 用对**（令牌层 + 状态层 + 可访问性层）。
