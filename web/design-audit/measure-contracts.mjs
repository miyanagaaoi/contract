/** 诊断脚本：测量合同台账各列实际宽度与横向溢出量（不修改任何文件）。 */
import { chromium } from '@playwright/test'

const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai',
})
const page = await ctx.newPage()
await page.goto('http://127.0.0.1:5173/login')
await page.getByPlaceholder('请输入登录名').fill('e2e_admin')
await page.getByPlaceholder('请输入密码').fill('e2e12345')
await page.getByRole('button', { name: /登\s*录/ }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 30000 })
await page.goto('http://127.0.0.1:5173/contracts', { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)

const m = await page.evaluate(() => {
  const table = document.querySelector('.el-table')
  const wrap = table.querySelector('.el-scrollbar__wrap')
  const ths = [...table.querySelectorAll('.el-table__header th')]
  const tableW = Math.round(table.getBoundingClientRect().width)
  return {
    tableW,
    contentW: wrap.scrollWidth,
    overflow: wrap.scrollWidth - tableW,
    colTotal: ths.reduce((s, th) => s + Math.round(th.getBoundingClientRect().width), 0),
    cols: ths.map((th) => `${th.innerText.trim() || '(空)'}=${Math.round(th.getBoundingClientRect().width)}`),
    filterCardH: Math.round((document.querySelector('.el-card')?.getBoundingClientRect().height) ?? 0),
  }
})
console.log(JSON.stringify(m, null, 2))
await browser.close()
