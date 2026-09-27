/** 诊断脚本：查看采购申请单表头的字段/按钮布局（用于对齐"合同详情按钮"的位置诉求）。 */
import { chromium } from '@playwright/test'

const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
const page = await ctx.newPage()
await page.goto('http://127.0.0.1:5173/login')
await page.getByPlaceholder('请输入登录名').fill('e2e_buyer')
await page.getByPlaceholder('请输入密码').fill('e2e12345')
await page.getByRole('button', { name: /登\s*录/ }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 30000 })
await page.goto('http://127.0.0.1:5173/purchase/requests/new', { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)

// 选一个关联合同，让「查看合同详情」进入可用态
const contractItem = page.locator('.el-form-item').filter({ hasText: '关联合同' })
await contractItem.locator('.el-select').first().click()
await page.waitForTimeout(700)
const opt = page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first()
if (await opt.count()) await opt.click()
await page.waitForTimeout(900)

await page.screenshot({ path: 'D:/dsh/hetong/design-audit/shots/30-requestform-header.png' })

const layout = await page.evaluate(() => [...document.querySelectorAll('.el-form-item')].map((el) => {
  const label = el.querySelector('.el-form-item__label')?.textContent?.trim() ?? ''
  const btns = [...el.querySelectorAll('button')].map((b) => b.textContent.trim()).filter(Boolean).join(' | ')
  const box = el.getBoundingClientRect()
  return { label, btns, y: Math.round(box.y), w: Math.round(box.width) }
}).filter((r) => r.label || r.btns))
console.log(JSON.stringify(layout, null, 1))
await browser.close()
