import { expect, type Page } from '@playwright/test'

/** E2E 账号（由 `app/tools/seed_e2e_users.py` 幂等维护） */
export const E2E_PASSWORD = 'e2e12345'

export const USERS = {
  admin: { username: 'e2e_admin', realName: 'E2E管理员' },
  viewer: { username: 'e2e_viewer', realName: 'E2E只读' },
  buyer: { username: 'e2e_buyer', realName: 'E2E采购员' },
  // V2.1：有审核权但**非管理员**（用于验证"创建人不可自审"仍对普通角色生效）
  pm: { username: 'e2e_pm', realName: 'E2E采购主管' },
  keeper: { username: 'e2e_keeper', realName: 'E2E仓管员' },
  seller: { username: 'e2e_seller', realName: 'E2E销售员' },
} as const

export type UserKey = keyof typeof USERS

/** 生成带时间戳的唯一名称，避免多次运行互相干扰 */
export function uniqueName(prefix: string): string {
  const now = new Date()
  const stamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`
    + `${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`
  return `${prefix}-${stamp}-${Math.floor(Math.random() * 1000)}`
}

/**
 * 收集页面运行时错误。
 *
 * 只保留 JS 未捕获异常与 Vue 运行时报错；静态资源 404 / 网络失败属于环境噪声，
 * 不计入（否则后端未启动的瞬时错误会淹没真实缺陷）。
 */
export function trackRuntimeErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`))
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
    const text = msg.text()
    if (/Failed to load resource|net::ERR_|favicon/i.test(text)) return
    errors.push(`[console] ${text}`)
  })
  return errors
}

/** 打开登录页并等待表单就绪 */
export async function gotoLogin(page: Page): Promise<void> {
  await page.goto('/login')
  await expect(page.getByRole('button', { name: /登\s*录/ })).toBeVisible()
}

/** 以指定账号登录（UI 路径），成功后停在首页看板 */
export async function login(page: Page, key: UserKey = 'admin'): Promise<void> {
  const user = USERS[key]
  await gotoLogin(page)
  await page.getByPlaceholder('请输入登录名').fill(user.username)
  await page.getByPlaceholder('请输入密码').fill(E2E_PASSWORD)
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 20_000 })
  await expect(page.locator('.header .user')).toContainText(user.realName)
}

/** 通过顶栏下拉退出登录 */
export async function logout(page: Page): Promise<void> {
  await page.locator('.header .user').hover()
  await page.locator('.el-dropdown-menu__item', { hasText: '退出登录' }).click()
  await page.locator('.el-message-box__btns button', { hasText: '退出' }).click()
  await page.waitForURL(/\/login/, { timeout: 20_000 })
}

/** 主区文本（断言页面主体内容） */
export function mainArea(page: Page) {
  return page.locator('.main')
}

/** 从 localStorage 读取登录令牌 */
export async function tokenOf(page: Page): Promise<string | null> {
  return page.evaluate(() => localStorage.getItem('ctms_token'))
}

/**
 * 按 label 精确定位 Element Plus 表单项（避免「联系人」误命中「联系电话」）。
 * 页面存在多个同名 label 时（如搜索区与弹窗都有「类型」），传入 `scope` 限定范围。
 */
export function formItem(page: Page, label: string, scope?: ReturnType<Page['locator']>) {
  const root = scope ?? page
  return root.locator('.el-form-item').filter({
    has: page.locator('.el-form-item__label', { hasText: new RegExp(`^${label}$`) }),
  })
}

/**
 * 打开 el-select 并选中下拉中的第 n 项（默认第一项）。
 *
 * 注意：Element Plus 的 `el-select` 下拉挂在 body 上，关闭时有约 200~300ms 的
 * 过渡动画，期间旧下拉仍匹配 `:visible`。若不等动画结束就点开下一个 select，
 * 点击会被残留的下拉浮层遮挡（表现为选项 "element is not visible" 超时）。
 *
 * 这里**不能**用 Esc 收起下拉：`el-dialog` 默认 `close-on-press-escape`，
 * Esc 会把整个弹窗一起关掉（曾导致"新增合同"弹窗被误关闭）。因此改为等待
 * 下拉自然隐藏。
 */
export async function pickSelectOption(
  page: Page, trigger: ReturnType<Page['locator']>, index = 0,
): Promise<void> {
  await waitDropdownsClosed(page)
  await trigger.click()
  const item = page.locator('.el-select-dropdown:visible .el-select-dropdown__item').nth(index)
  await item.click()
  await waitDropdownsClosed(page)
}

/** 等待所有 el-select 下拉关闭（无下拉时立即返回） */
export async function waitDropdownsClosed(page: Page): Promise<void> {
  await expect(page.locator('.el-select-dropdown:visible'))
    .toHaveCount(0, { timeout: 5_000 })
    .catch(() => { /* 关不掉时不阻塞用例，交给后续断言报错 */ })
}

/** 断言最新的全局提示（ElMessage）文案 */
export async function expectMessage(page: Page, text: string | RegExp) {
  await expect(page.locator('.el-message').last()).toContainText(text)
}

/**
 * 从 ElMessage 提示里取出刚创建的单号（如「已创建 CG2026090001」）。
 *
 * 保存并提交会连续弹出「已创建 xxx」「已提交审核」两条提示，页面上还可能残留更早
 * 的提示，因此必须按「已创建」过滤，不能直接取最后一条。
 */
export async function readCreatedDocNo(page: Page): Promise<string> {
  const msg = page.locator('.el-message').filter({ hasText: '已创建' }).last()
  await expect(msg).toBeVisible({ timeout: 10_000 })
  const text = await msg.innerText()
  const hit = /已创建\s*(\S+)/.exec(text)
  expect(hit, `未能从提示「${text}」中解析单号`).not.toBeNull()
  return hit![1]
}

/** 新增一行单据行项：选第一个物料，返回物料名称（不含编码） */
export async function addFirstItemRow(page: Page, qty = '1'): Promise<string> {
  const itemsTable = page.locator('.el-table').last()
  await page.getByRole('button', { name: '添加行' }).click()
  const row = itemsTable.locator('.el-table__row').first()
  await row.locator('td').nth(1).locator('.el-select').click()
  await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first().click()
  if (qty) await row.locator('td').nth(4).locator('input').fill(qty)
  const label = (await row.locator('td').nth(1).innerText()).trim()
  return label.split('（')[0].trim()
}
