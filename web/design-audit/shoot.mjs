/**
 * 设计审查取证脚本（只读，不修改业务代码）。
 *
 * 用途：登录真实运行中的 dev server，逐页截图并采集客观布局指标
 * （横向溢出、字号分布、可点击元素尺寸），供设计评审引用。
 *
 * 运行：node design-audit/shoot.mjs
 */
import { chromium } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'

const BASE = 'http://127.0.0.1:5173'
const OUT = 'D:/dsh/hetong/design-audit/shots'
const USER = 'e2e_admin'
const PASS = 'e2e12345'

mkdirSync(OUT, { recursive: true })

const ROUTES = [
  ['00-login', '/login', false],
  ['01-dashboard', '/', false],
  ['02-contracts', '/contracts', false],
  ['03-master-customers', '/master/customers', false],
  ['04-master-users', '/master/users', false],
  ['05-purchase-requests', '/purchase/requests', false],
  ['06-purchase-order-new', '/purchase/orders/new', false],
  ['07-sales-orders', '/sales/orders', false],
  ['08-stock-balances', '/stock/balances', false],
  ['09-stock-in-new', '/stock/in-orders/new', false],
  ['10-system', '/system', false],
  ['11-change-password', '/change-password', false],
]

const report = { shots: [], runtimeErrors: [], metrics: {} }

const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  locale: 'zh-CN',
  timezoneId: 'Asia/Shanghai',
})
const page = await ctx.newPage()

page.on('pageerror', (e) => report.runtimeErrors.push(`[pageerror] ${e.message}`))
page.on('console', (m) => {
  if (m.type() !== 'error') return
  const t = m.text()
  if (/Failed to load resource|net::ERR_|favicon/i.test(t)) return
  report.runtimeErrors.push(`[console] ${t}`)
})

async function measure(label) {
  const m = await page.evaluate(() => {
    const de = document.documentElement
    const main = document.querySelector('.main')
    const sizes = {}
    const colors = {}
    const clickable = []
    document.querySelectorAll('body *').forEach((el) => {
      const cs = getComputedStyle(el)
      const fs = cs.fontSize
      sizes[fs] = (sizes[fs] || 0) + 1
      const txt = (el.textContent || '').trim()
      if (txt && el.children.length === 0) colors[cs.color] = (colors[cs.color] || 0) + 1
    })
    document.querySelectorAll('button, .el-button, a, [role="button"], .el-menu-item').forEach((el) => {
      const r = el.getBoundingClientRect()
      if (r.width > 0 && r.height > 0 && (r.height < 28 || r.width < 28)) {
        clickable.push({
          sel: el.className && typeof el.className === 'string' ? el.className.slice(0, 60) : el.tagName,
          w: Math.round(r.width), h: Math.round(r.height),
          text: (el.textContent || '').trim().slice(0, 18),
        })
      }
    })
    const top = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n)
    return {
      docScrollW: de.scrollWidth,
      docClientW: de.clientWidth,
      overflowX: de.scrollWidth - de.clientWidth,
      mainScrollW: main ? main.scrollWidth : null,
      mainClientW: main ? main.clientWidth : null,
      fontSizes: top(sizes, 10),
      textColors: top(colors, 8),
      smallTargets: clickable.slice(0, 12),
      smallTargetCount: clickable.length,
      h1: document.querySelectorAll('h1').length,
      h2: document.querySelectorAll('h2').length,
      ariaLabels: document.querySelectorAll('[aria-label]').length,
      tables: document.querySelectorAll('.el-table').length,
      rowCount: document.querySelectorAll('.el-table__row').length,
    }
  })
  report.metrics[label] = m
}

async function shoot(name, full = false) {
  const p = `${OUT}/${name}.png`
  await page.screenshot({ path: p, fullPage: full })
  report.shots.push(name)
}

// 1) 登录页（未登录态）
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.waitForTimeout(500)
await shoot('00-login')

// 2) 登录
await page.getByPlaceholder('请输入登录名').fill(USER)
await page.getByPlaceholder('请输入密码').fill(PASS)
await page.getByRole('button', { name: /登\s*录/ }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 30000 })
await page.waitForTimeout(1200)

// 3) 逐页截图 + 采集
for (const [name, route] of ROUTES) {
  if (route === '/login') continue
  try {
    await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle', timeout: 30000 })
    await page.waitForTimeout(900)
    await shoot(name)
    await measure(name)
  } catch (e) {
    report.runtimeErrors.push(`[nav ${route}] ${e.message}`)
  }
}

// 4) 宽屏整页截图（看全局密度）
try {
  await page.goto(`${BASE}/contracts`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
  await shoot('20-contracts-full', true)
} catch { /* ignore */ }

// 5) 窄屏适配：1280 / 1024
for (const w of [1280, 1024]) {
  await page.setViewportSize({ width: w, height: 800 })
  for (const [name, route] of [['21-dashboard', '/'], ['22-contracts', '/contracts'], ['23-request-new', '/purchase/requests/new']]) {
    try {
      await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle', timeout: 30000 })
      await page.waitForTimeout(800)
      await shoot(`${name}-${w}`)
      await measure(`${name}-${w}`)
    } catch (e) {
      report.runtimeErrors.push(`[nav ${w} ${route}] ${e.message}`)
    }
  }
}

await browser.close()
writeFileSync('D:/dsh/hetong/design-audit/report.json', JSON.stringify(report, null, 2), 'utf8')
console.log(JSON.stringify({
  shots: report.shots.length,
  errors: report.runtimeErrors,
  overflow: Object.fromEntries(Object.entries(report.metrics).map(([k, v]) => [k, v.overflowX])),
  smallTargets: Object.fromEntries(Object.entries(report.metrics).map(([k, v]) => [k, v.smallTargetCount])),
}, null, 2))
