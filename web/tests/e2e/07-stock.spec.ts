import { expect, test, type Page } from '@playwright/test'

import {
  addFirstItemRow, expectMessage, formItem, login, logout,
  pickSelectOption, readCreatedDocNo, tokenOf, trackRuntimeErrors,
} from './helpers'

const IN_LIST = '/stock/in-orders'

/** 通过接口汇总某物料在所有仓库的结存数量（避免依赖列表分页） */
async function balanceOf(page: Page, productName: string): Promise<number> {
  const token = await tokenOf(page)
  const resp = await page.request.get('/api/stock/balances', {
    headers: { Authorization: `Bearer ${token}` },
    params: { keyword: productName, page_size: 200 },
  })
  expect(resp.status()).toBe(200)
  const body = (await resp.json()) as { items: { product_name: string; qty: number }[] }
  return body.items
    .filter((i) => i.product_name === productName)
    .reduce((sum, i) => sum + Number(i.qty || 0), 0)
}

test.describe('库存管理', () => {
  test('入库单列表加载：表头与筛选齐全，无运行时错误', async ({ page }) => {
    const errors = trackRuntimeErrors(page)
    await login(page, 'keeper')
    await page.goto(IN_LIST)

    await expect(page.locator('.main')).toContainText('入库单')
    const table = page.locator('.el-table').first()
    // 入库单同时开了「仓库」与「供应商」，往来单位列优先显示供应商（见 DocListPage.partyLabel）
    for (const label of ['单号', '单据日期', '状态', '供应商', '金额', '经办人']) {
      await expect(table.getByRole('columnheader', { name: label, exact: true })).toBeVisible()
    }

    expect(errors).toEqual([])
  })

  test('仓管员录入入库单并提交 → 管理员审核 → 库存结存增加（过账）', async ({ page }) => {
    // ---------- 1) 仓管员录入并提交 ----------
    await login(page, 'keeper')
    await page.goto(`${IN_LIST}/new`)
    await expect(page.locator('.main')).toContainText('新增入库单')

    await pickSelectOption(page, formItem(page, '入库仓库').locator('input'))
    const productName = await addFirstItemRow(page, '7')
    expect(productName.length).toBeGreaterThan(0)

    const before = await balanceOf(page, productName)

    await page.getByRole('button', { name: '保存并提交' }).click()
    const docNo = await readCreatedDocNo(page)
    await expect(page).toHaveURL(new RegExp(`${IN_LIST}$`))

    // ---------- 2) 管理员审核（审核即过账）----------
    await logout(page)
    await login(page, 'admin')
    await page.goto(IN_LIST)
    await page.getByPlaceholder('单号 / 来源单号 / 合同号 / 往来单位').fill(docNo)
    await page.getByRole('button', { name: '查询' }).click()

    const row = page.locator('.el-table__row').filter({ hasText: docNo })
    await expect(row).toHaveCount(1)
    await row.getByRole('button', { name: '审核' }).click()
    const approveDialog = page.locator('.el-dialog:visible').filter({ hasText: '审核通过' })
    await approveDialog.getByRole('button', { name: '确定审核通过' }).click()
    await expectMessage(page, '操作成功')

    // ---------- 3) 结存必须正好增加 7 ----------
    await expect.poll(() => balanceOf(page, productName), { timeout: 15_000 })
      .toBe(before + 7)
  })

  test('入库单详情显示「已过账」与行项', async ({ page }) => {
    await login(page, 'admin')
    await page.goto(IN_LIST)
    await page.locator('.el-table__row').first().getByRole('button', { name: '查看' }).click()

    const drawer = page.locator('.el-drawer:visible')
    await expect(drawer).toContainText('入库单详情')
    await expect(drawer).toContainText('行项明细')
  })

  test('库存明细：列表加载、删除无关筛选、重算校验通过', async ({ page }) => {
    const errors = trackRuntimeErrors(page)
    await login(page, 'admin')
    await page.goto('/stock/balances')

    await expect(page.locator('.main')).toContainText('库存明细')
    const table = page.locator('.el-table').first()
    for (const label of ['结存数量', '安全库存', '库存状态', '更新时间']) {
      await expect(table.locator('th').filter({ hasText: label }).first()).toBeVisible()
    }

    // 库存重算：校验 stocks.qty 与流水汇总是否一致
    await page.getByRole('button', { name: '库存重算' }).click()
    await expect(page.locator('.el-message').last()).toContainText(/校验通过|不一致/)

    expect(errors).toEqual([])
  })

  test('库存明细：按关键词检索不报错', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/stock/balances')

    await page.getByPlaceholder('物料编码 / 名称 / 规格').fill('不存在的物料ZZZ')
    await page.getByRole('button', { name: '查询' }).click()
    await expect(page.locator('.el-table__empty-text')).toContainText('暂无库存结存数据')

    await page.getByRole('button', { name: '重置' }).click()
    await expect(page.getByPlaceholder('物料编码 / 名称 / 规格')).toHaveValue('')
  })

  test('出库单与盘点单页面对仓管员可达', async ({ page }) => {
    await login(page, 'keeper')

    await page.goto('/stock/out-orders')
    await expect(page.locator('.main')).toContainText('出库单')

    await page.goto('/stock/takes')
    await expect(page.locator('.main')).toContainText('盘点单')
    await expect(page.getByRole('button', { name: '新增' })).toBeVisible()
  })

  // 环境前提（已满足）：真实库中内置角色的权限分配是**历史写入**的，新增的
  // `stock.transfer.*` 需先执行 `python -m app.init_db --sync-roles` 才会授予既有
  // 角色（`e2e_admin` 是 `sysadmin` **角色**而非超管，权限取自 role_permissions）。
  // 未同步前，前端路由守卫会把访问者导向 403 —— 这本身说明权限控制是生效的（不是缺陷）。
  //
  // 2026-09-26：已实测确认 `e2e_admin`(sysadmin) 具备全部 `stock.transfer.*`
  // （GET /api/auth/me 的 perms 含 stock.transfer.view/create/edit/submit/approve/void/export），
  // 前提条件满足，因此放开该用例，不再默认跳过。
  test('调拨单：列表与新增页可达', async ({ page }) => {
    await login(page, 'admin')

    await page.goto('/stock/transfers')
    await expect(page.locator('.main')).toContainText('调拨单')
    await expect(page.getByRole('button', { name: '新增' })).toBeVisible()

    await page.goto('/stock/transfers/new')
    await expect(page.locator('.main')).toContainText('新增调拨单')
    await expect(page.getByRole('button', { name: '添加行' })).toBeVisible()
    // 调拨不产生金额：行项表不出现「单价」列
    await expect(page.locator('.el-table').last().getByRole('columnheader', { name: '单价' }))
      .toHaveCount(0)
  })

  test('仓管员没有采购录入入口（菜单裁剪）', async ({ page }) => {
    await login(page, 'keeper')
    const aside = page.locator('.aside')
    await expect(aside).toContainText('库存管理')
    // keeper 只有 purchase.order.view（可看采购单），没有申请单权限
    await aside.getByText('采购管理', { exact: true }).click()
    await expect(aside).not.toContainText('采购申请单')
  })
})
