/** 诊断：经办人下拉为何显示 ID 且无法选择。 */
import { chromium } from '@playwright/test'

const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
const page = await ctx.newPage()

const apiLog = []
const bad = []
page.on('response', (r) => {
  const u = r.url()
  if (r.status() >= 400) bad.push(`${r.status()} ${u}`)
  if (u.includes('/api/master/options/') || u.includes('/api/auth/me')) apiLog.push(`${r.status()} ${u.replace('http://127.0.0.1:5173', '')}`)
})
const consoleErrors = []
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
page.on('pageerror', (e) => consoleErrors.push('[pageerror] ' + e.message))

await page.goto('http://127.0.0.1:5173/login')
await page.getByPlaceholder('请输入登录名').fill('e2e_buyer')
await page.getByPlaceholder('请输入密码').fill('e2e12345')
await page.getByRole('button', { name: /登\s*录/ }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 30000 })

await page.goto('http://127.0.0.1:5173/purchase/requests/new', { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)

const handlerItem = page.locator('.el-form-item').filter({
  has: page.locator('.el-form-item__label', { hasText: /^经办人$/ }),
})
console.log('--- API calls ---')
console.log(apiLog.join('\n') || '(none)')
console.log('--- 经办人 input 显示值 ---')
console.log(await handlerItem.locator('input').first().inputValue())

await handlerItem.locator('.el-select').first().click()
await page.waitForTimeout(900)
const items = await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').allInnerTexts()
console.log('--- 下拉选项数 = ' + items.length + ' ---')
console.log(items.slice(0, 6).join(' | '))
await page.screenshot({ path: 'D:/dsh/hetong/design-audit/shots/31-handler-select.png' })
console.log('--- console errors ---')
console.log(consoleErrors.slice(0, 8).join('\n') || '(none)')
console.log('--- 4xx/5xx responses ---')
console.log(bad.join('\n') || '(none)')
await browser.close()
