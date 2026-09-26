import { expect, test } from '@playwright/test'

import { login } from './helpers'

/**
 * 主布局回归（防止顶栏再次退化为「只占内容宽度、缩在左上角」）。
 *
 * 背景：`el-container` 只有在**直接子节点**是 `ElHeader`/`ElFooter` 时才纵向排列；
 * `AppLayout` 的顶栏封装在自定义组件 `<TopBar />` 里，必须显式写
 * `direction="vertical"`。一旦被去掉，容器会变成 row —— 顶栏宽度塌陷成内容宽度，
 * 主区被挤到顶栏右侧，页面整体错位。
 */
test.describe('主布局：顶栏宽度与页面自适应', () => {
  test('顶栏横向铺满右侧区域，主区紧随其下', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/contracts')

    const viewport = page.viewportSize()!
    const aside = (await page.locator('.aside').boundingBox())!
    const header = (await page.locator('.header').boundingBox())!
    const main = (await page.locator('.main').boundingBox())!

    // 顶栏从侧栏右边缘开始，一直铺到视口右边
    expect(Math.round(header.x)).toBe(Math.round(aside.x + aside.width))
    expect(Math.round(header.x + header.width)).toBe(viewport.width)
    expect(Math.round(header.height)).toBe(60)

    // 主区与顶栏同宽、位于顶栏正下方，且撑满剩余高度
    expect(Math.round(main.width)).toBe(Math.round(header.width))
    expect(Math.round(main.x)).toBe(Math.round(header.x))
    expect(Math.round(main.y)).toBe(Math.round(header.y + header.height))
    expect(Math.round(main.y + main.height)).toBe(viewport.height)
  })

  test('顶栏左侧信息与右侧用户区分别贴向两端', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/contracts')

    const header = (await page.locator('.header').boundingBox())!
    const left = (await page.locator('.header .left').boundingBox())!
    const user = (await page.locator('.header .user').boundingBox())!

    // 左侧贴近左内边距、右侧用户区贴近右内边距（Element Plus 默认 padding 20px）
    expect(left.x - header.x).toBeLessThan(40)
    expect(header.x + header.width - (user.x + user.width)).toBeLessThan(40)
  })

  test('1024 窄视口下顶栏仍铺满且左右内容不重叠', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 })
    await login(page, 'admin')
    await page.goto('/contracts')

    const viewport = page.viewportSize()!
    const header = (await page.locator('.header').boundingBox())!
    const left = (await page.locator('.header .left').boundingBox())!
    const user = (await page.locator('.header .user').boundingBox())!

    expect(Math.round(header.x + header.width)).toBe(viewport.width)
    expect(left.x + left.width).toBeLessThanOrEqual(user.x)
  })

  test('合同台账：表格不横向溢出、行高单行、操作列紧凑', async ({ page }) => {
    // 自包含：显式用 1440 桌面宽度断言列宽刚好装下（列总计按该宽度校准）
    await page.setViewportSize({ width: 1440, height: 900 })
    await login(page, 'admin')
    await page.goto('/contracts')
    await expect(page.locator('.el-table__row').first()).toBeVisible()

    const metrics = await page.evaluate(() => {
      const table = document.querySelector('.el-table')!
      const wrap = table.querySelector('.el-scrollbar__wrap') as HTMLElement | null
      const tds = [...table.querySelectorAll('.el-table__body tbody tr:first-child td')] as HTMLElement[]
      const ths = [...table.querySelectorAll('.el-table__header th')] as HTMLElement[]
      const box = (el: Element | null | undefined) => {
        if (!el) return null
        const r = el.getBoundingClientRect()
        return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }
      }
      return {
        // 内容总宽 vs 表格容器宽：前者更大即出现横向滚动条
        contentW: wrap?.scrollWidth ?? 0,
        tableW: Math.round(table.getBoundingClientRect().width),
        rowH: box(tds[0])?.h ?? 0,
        opW: box(ths[ths.length - 1])?.w ?? 0,
        formBox: box(document.querySelector('.filter-form')),
        actionsBox: box(document.querySelector('.filter-actions')),
      }
    })

    // 列宽必须装得下，不再出现横向滚动条
    expect(metrics.contentW).toBeLessThanOrEqual(metrics.tableW + 1)
    // 每行必须是单行高度（多标签、按钮换行都会把行撑高）
    expect(metrics.rowH).toBeLessThan(44)
    // 操作列保持紧凑，避免 fixed 列大面积遮挡金额列
    expect(metrics.opW).toBeLessThanOrEqual(180)
    // 筛选区按钮组与筛选项顶部对齐（原来 float:right 会错位）
    expect(Math.abs((metrics.actionsBox?.y ?? 0) - (metrics.formBox?.y ?? 0))).toBeLessThan(24)
  })
})
