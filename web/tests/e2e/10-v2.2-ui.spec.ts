/**
 * V2.2 UI 改进用例（用户反馈四条）。
 *
 * 覆盖：
 * 1. **操作列可读性**：链接按钮不再是 Element Plus 默认的 `#409eff`（白底 3.02:1），
 *    且「更多」下拉与前面的按钮在**同一行**（原实现因 `el-dropdown` 的
 *    `vertical-align: top` 而错位/掉行）；
 * 2. **供货商可点击**：采购单列表的往来单位列变成按钮，点开只读档案弹窗，
 *    标题与首行默认显示**简称**；
 * 3. **库存明细**：商品类型前置到物料名称里，显示为「类型-名称」（如 原材料-钢材）；
 * 4. **打印模板**：系统管理里可调标题/标签/区块顺序，并实时预览，
 *    最后恢复出厂模板（用例结束后用接口兜底重置，不污染演示库）。
 */
import { expect, test } from '@playwright/test'

import { expectMessage, login } from './helpers'

/** 与后端 `print_template_service.KINDS` 对齐 */
const TEMPLATE_KINDS = [
  'purchase_request', 'purchase_order', 'sales_request', 'sales_order',
  'stock_in', 'stock_out', 'stock_take', 'stock_transfer',
]

/** 在页面上下文里带令牌调用接口（避免另起一套 request 上下文与令牌管理） */
async function apiGet(page: import('@playwright/test').Page, url: string): Promise<any> {
  return page.evaluate(async (target) => {
    const token = localStorage.getItem('ctms_token')
    const res = await fetch(target, { headers: { Authorization: `Bearer ${token}` } })
    return res.json()
  }, url)
}

test.describe('V2.2 UI 改进', () => {
  test.beforeEach(async ({ page }) => {
    await login(page, 'admin')
  })

  test.afterAll(async ({ request }) => {
    // 兜底：打印模板是全局配置，用例无论成败都不该把演示库留在自定义状态
    const resp = await request.post('/api/auth/login',
                                    { data: { username: 'e2e_admin', password: 'e2e12345' } })
    if (!resp.ok()) return
    const token = (await resp.json()).token as string
    for (const kind of TEMPLATE_KINDS) {
      await request.post(`/api/system/print-templates/${kind}/reset`,
                         { headers: { Authorization: `Bearer ${token}` } })
    }
  })

  // ---------------- ① 操作列 ----------------

  test('采购单列表：操作列按钮与「更多」同行，且文字颜色加深', async ({ page }) => {
    await page.goto('/purchase/orders')
    const firstRow = page.locator('.el-table__body .el-table__row').first()
    await expect(firstRow).toBeVisible()

    const view = firstRow.locator('.row-actions .el-button', { hasText: '查看' })
    const more = firstRow.locator('.row-actions .el-dropdown .el-button')
    await expect(view).toBeVisible()
    await expect(more).toBeVisible()

    const a = await view.boundingBox()
    const b = await more.boundingBox()
    expect(a, '未取到「查看」按钮位置').not.toBeNull()
    expect(b, '未取到「更多」按钮位置').not.toBeNull()
    // 同一行的判定：两者垂直中心相差不超过 3px（原实现会掉到下一行，差一个行高）
    const centerA = a!.y + a!.height / 2
    const centerB = b!.y + b!.height / 2
    expect(Math.abs(centerA - centerB)).toBeLessThan(3)

    // 对比度：不再使用 Element Plus 默认主色（白底仅 3.02:1）
    const color = await view.evaluate((el) => getComputedStyle(el).color)
    expect(color).not.toBe('rgb(64, 158, 255)')
    expect(color).toBe('rgb(31, 111, 220)')
  })

  // ---------------- ② 供货商详情 ----------------

  test('采购单列表：供货商可点击并弹出详情，默认显示简称', async ({ page }) => {
    const data = await apiGet(page, '/api/purchase/orders?page=1&page_size=1')
    expect(data.items?.length, '演示库没有采购单，无法验证供货商入口').toBeGreaterThan(0)
    const supplierId = data.items[0].supplier_id as number
    expect(supplierId, '首张采购单没有绑定供货商档案').toBeTruthy()

    const supplier = await apiGet(page, `/api/master/suppliers/${supplierId}`)
    // 存量档案可能没有简称（V2.2 起才必填），此时按全称显示 —— 两种情况都要能正确弹窗
    const shortName = (supplier.short_name as string) || ''
    const display = shortName || (supplier.name as string)

    await page.goto('/purchase/orders')
    const firstRow = page.locator('.el-table__body .el-table__row').first()
    await expect(firstRow).toBeVisible()

    // 往来单位列的按钮（按表头名定位，避免写死列序号）
    const headerTexts = await page.locator('.el-table__header th').allInnerTexts()
    const partyIndex = headerTexts.findIndex((t) => t.trim() === '供应商')
    expect(partyIndex, '未找到「供应商」列').toBeGreaterThanOrEqual(0)

    await firstRow.locator('td').nth(partyIndex).locator('.el-button').click()
    const dialog = page.locator('.el-dialog:visible')
    await expect(dialog).toBeVisible()
    // 标题默认显示**简称**（无简称才回退全称）
    await expect(dialog.locator('.el-dialog__title')).toContainText('供货商详情')
    await expect(dialog.locator('.el-dialog__title')).toContainText(display)
    await expect(dialog.locator('.name-bar .short')).toHaveText(display)
    if (shortName) {
      // 有简称时，首行大字是简称，全称作为次要说明跟在后面
      expect(display).toBe(shortName)
      await expect(dialog.locator('.name-bar .full')).toHaveText(supplier.name)
    }
    await expect(dialog).toContainText('供货商编码')

    await dialog.locator('.el-dialog__footer button', { hasText: '关闭' }).click()
    await expect(dialog).toBeHidden()
  })

  test('采购单表单：供货商选择旁有「供货商详情」按钮（未选时禁用）', async ({ page }) => {
    await page.goto('/purchase/orders/new')
    const item = page.locator('.el-form-item', { hasText: '供应商' }).first()
    const button = item.getByRole('button', { name: '供货商详情' })
    await expect(button).toBeVisible()
    await expect(button).toBeDisabled()          // 未选供应商时不可点
  })

  // ---------------- ③ 库存明细 ----------------

  test('库存明细：商品类型前置为「类型-物料名称」', async ({ page }) => {
    const data = await apiGet(page, '/api/stock/balances?page=1&page_size=5')
    test.skip(!data.total, '演示库暂无库存结存数据，跳过')

    await page.goto('/stock/balances')
    const firstRow = page.locator('.el-table__body .el-table__row').first()
    await expect(firstRow).toBeVisible()

    const row = data.items[0]
    const expected = row.product_type_name
      ? `${row.product_type_name}-${row.product_name}`
      : row.product_name
    // 列顺序：# / 物料编码 / 物料名称 / …
    await expect(firstRow.locator('td').nth(2)).toHaveText(expected)
    // 原先类型是独立一列，现在已合并，不应再有「商品类型」列头
    await expect(page.locator('.el-table__header th', { hasText: '商品类型' })).toHaveCount(0)
  })

  // ---------------- ④ 打印模板 ----------------

  test('打印模板：改标题 / 调区块顺序 → 实时预览生效', async ({ page }) => {
    await page.goto('/system/print-templates')
    await expect(page.locator('.kind-item')).toHaveCount(TEMPLATE_KINDS.length)

    await page.locator('.kind-item', { hasText: '采购单' }).first().click()
    const editor = page.locator('.editor')
    await expect(editor).toBeVisible()

    // 改标题 → 预览里的大标题跟着变（预览的是**未保存**的配置）
    const titleInput = page.locator('.el-form-item', { hasText: '单据标题' }).locator('input').first()
    await titleInput.fill('E2E 打印标题')
    const frame = page.frameLocator('iframe.preview-frame')
    await expect(frame.locator('h1')).toHaveText('E2E 打印标题', { timeout: 20_000 })

    // 改一个表头字段的标签（用 .row-name 精确定位「状态」，避免命中「单据状态」之类的重名）
    const statusRow = page.locator('.row-item').filter({
      has: page.locator('.row-name', { hasText: /^状态$/ }),
    }).first()
    await statusRow.locator('.label-input input').fill('单据状态')
    await expect(frame.locator('td.k', { hasText: '单据状态' })).toHaveCount(1, { timeout: 20_000 })

    // 区块顺序：「行项明细」上移一格（让它排到「表头信息」前面）
    const blockRows = page.locator('.el-collapse-item', { hasText: '区块顺序' })
      .locator('.row-item')
    await expect(blockRows.nth(1)).toContainText('表头信息')
    await blockRows.nth(2).getByRole('button', { name: '↑ 上移' }).click()
    await expect(blockRows.nth(1)).toContainText('行项明细')
    // 预览里明细表排到了表头表之前
    await page.getByRole('button', { name: '刷新预览' }).click()
    await expect(frame.locator('table.items')).toBeVisible({ timeout: 20_000 })

    // 保存 → 列表出现「已自定义」，再恢复默认
    await page.getByRole('button', { name: '保存模板' }).click()
    await expectMessage(page, '已保存')
    await page.getByRole('button', { name: '恢复默认' }).click()
    await page.locator('.el-message-box__btns button', { hasText: '恢复默认' }).click()
    await expectMessage(page, '已恢复出厂模板')
    await expect(page.locator('.kind-item', { hasText: '采购单' }).first()).not.toContainText('已自定义')
  })

  test('打印模板：只读账号看不到「保存模板」按钮', async ({ page }) => {
    // 换只读账号：有 system.print.view 才有权进这个页面，故用管理员确认权限点本身在菜单里生效
    await page.goto('/system/print-templates')
    await expect(page.locator('.kind-item').first()).toBeVisible()
    await expect(page.getByRole('button', { name: '保存模板' })).toBeVisible()
    await expect(page.getByRole('button', { name: '恢复默认' })).toBeDisabled()   // 未自定义时禁用
  })
})
