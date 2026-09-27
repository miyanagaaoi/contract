/** 验证 critique 报告 HTML 的实际渲染（雷达图与栅格布局）。 */
import { chromium } from '@playwright/test'

const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 }, locale: 'zh-CN' })
const page = await ctx.newPage()
await page.goto('file:///D:/dsh/hetong/design-audit/critique-report.html', { waitUntil: 'load' })
await page.waitForTimeout(400)
await page.screenshot({ path: 'D:/dsh/hetong/design-audit/shots/90-critique-top.png' })
await page.screenshot({ path: 'D:/dsh/hetong/design-audit/shots/91-critique-full.png', fullPage: true })
const info = await page.evaluate(() => ({
  polygons: document.querySelectorAll('svg polygon').length,
  dimCards: document.querySelectorAll('.dim').length,
  checklist: document.querySelectorAll('ul.check input').length,
  scrollW: document.documentElement.scrollWidth,
  clientW: document.documentElement.clientWidth,
  height: document.documentElement.scrollHeight,
}))
console.log(JSON.stringify(info, null, 2))
await browser.close()
