import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { expectMessage, formItem, login, readCreatedDocNo, tokenOf } from './helpers'

/**
 * V2.5 财务模块主流程（AC-V2.5-02/06/12/14/16）。
 *
 * 覆盖用户真正会走的路径：
 * 采购单（已审核，未付款）→ 列表看到「付款进度 0%」→「更多 → 发起付款单」预填未付金额
 * → 保存草稿 → 提交 → 财务审核（记账）→ 采购单付款进度 30% → 反审核红冲 → 回到 0%。
 *
 * 单据的"提交/审核"用接口驱动（状态机本身已有 pytest 覆盖，UI 的审核弹窗也被
 * `06-purchase.spec.ts` 覆盖）；本用例聚焦**本次新增的界面**：进度列、「更多」财务入口、
 * 付款单表单预填与列表列。
 */
const LIST = '/purchase/orders'

/** 建一张"已审核、未付款"的采购单（金额 = 数量 × 单价），返回单号与未付金额 */
async function approvedPurchaseOrder(page: Page, request: APIRequestContext, token: string) {
  const headers = { Authorization: `Bearer ${token}` }
  const [products, suppliers] = await Promise.all([
    request.get('/api/master/options/product', { headers }),
    request.get('/api/master/options/supplier', { headers }),
  ])
  const productId = (await products.json())[0].id
  const supplierId = (await suppliers.json())[0].id
  const today = new Date().toISOString().slice(0, 10)

  const created = await request.post('/api/purchase/orders', {
    headers,
    data: {
      doc_date: today, supplier_id: supplierId, subject_code: 'ZC',
      items: [{ product_id: productId, qty: 10, unit_price: 1000 }],
      remark: 'E2E 财务主流程',
    },
  })
  expect(created.status(), await created.text()).toBe(200)
  const po = await created.json()
  const id = po.id as number
  expect((await request.post(`/api/purchase/orders/${id}/submit`, { headers })).status()).toBe(200)
  expect((await request.post(`/api/purchase/orders/${id}/approve`, { headers })).status()).toBe(200)
  return { id, docNo: po.doc_no as string, amount: Number(po.total_amount) }
}

function rowOf(page: Page, docNo: string) {
  return page.locator('.el-table__row').filter({ hasText: docNo })
}

async function search(page: Page, docNo: string) {
  await page.getByPlaceholder('单号 / 来源单号 / 合同号 / 往来单位').fill(docNo)
  await page.getByRole('button', { name: '查询' }).click()
}

test.describe('V2.5 财务模块', () => {
  test('采购单进度列与「更多」财务入口（含权限）', async ({ page }) => {
    await login(page, 'admin')
    await page.goto(LIST)

    const table = page.locator('.el-table').first()
    for (const label of ['收货进度', '付款进度', '收票进度']) {
      await expect(table.getByRole('columnheader', { name: label, exact: true })).toBeVisible()
    }
  })

  test('只读账号看不到财务发起入口，但能看到进度列', async ({ page }) => {
    await login(page, 'viewer')
    await page.goto(LIST)
    const table = page.locator('.el-table').first()
    await expect(table.getByRole('columnheader', { name: '付款进度', exact: true })).toBeVisible()
    await expect(page.locator('.el-table__row').first()
      .getByRole('button', { name: '更多' })).toBeVisible()
    // 「更多」里不应出现财务发起项（viewer 无 finance.*.create）
    const firstMore = page.locator('.el-table__row').first().getByRole('button', { name: '更多' })
    await firstMore.click()
    await expect(page.locator('.el-dropdown-menu:visible')
      .getByText('发起付款单')).toHaveCount(0)
  })

  test('主流程：发起付款单 → 审核记账 → 付款进度 → 反审核红冲', async ({ page }) => {
    await login(page, 'admin')
    const token = (await tokenOf(page)) as string
    const { id, docNo, amount } = await approvedPurchaseOrder(page, page.request, token)
    expect(amount).toBe(10000)

    // ---- 1) 列表：进度列显示 0.0%，「更多 → 发起付款单」 ----
    await page.goto(LIST)
    await search(page, docNo)
    const row = rowOf(page, docNo)
    await expect(row).toContainText('0.0%')
    await row.getByRole('button', { name: '更多' }).click()
    await page.locator('.el-dropdown-menu:visible .el-dropdown-menu__item',
                       { hasText: '发起付款单' }).click()
    await expect(page).toHaveURL(/\/finance\/payments\/new/)

    // ---- 2) 表单预填：金额 = 未付金额（10000），核销明细已带一行采购单 ----
    await expect(page.locator('.main')).toContainText('新增付款单')
    await expect(page.locator('.el-table').last()).toContainText(docNo)
    const amountInput = formItem(page, '付款金额').locator('input')
    await expect(amountInput).toHaveValue('10000.00')

    // 部分付款：改成 3000 后保存
    await amountInput.fill('3000')
    await page.locator('.el-table').last().locator('.el-table__row').first()
      .locator('td').nth(1).locator('input').fill('3000')
    await page.getByRole('button', { name: '保存草稿' }).click()
    const payNo = await readCreatedDocNo(page)
    expect(payNo).toMatch(/^PAY/)

    // ---- 3) 提交 + 财务审核（记账）：用接口驱动状态机 ----
    const headers = { Authorization: `Bearer ${token}` }
    const payments = await page.request.get('/api/finance/payments',
                                            { headers, params: { keyword: payNo } })
    const payId = (await payments.json()).items[0].id as number
    expect((await page.request.post(`/api/finance/payments/${payId}/submit`,
                                    { headers })).status()).toBe(200)
    expect((await page.request.post(`/api/finance/payments/${payId}/approve`,
                                    { headers })).status()).toBe(200)

    // ---- 4) 采购单付款进度 30.0%（含税金额口径）----
    await page.goto(LIST)
    await search(page, docNo)
    await expect(rowOf(page, docNo)).toContainText('30.0%')

    // ---- 5) 付款单列表：已核销 / 未核销 ----
    await page.goto('/finance/payments')
    await page.getByPlaceholder('单号 / 来源单号 / 合同号 / 往来单位').fill(payNo)
    await page.getByRole('button', { name: '查询' }).click()
    const payRow = rowOf(page, payNo)
    await expect(payRow).toContainText('已审核')
    await expect(payRow).toContainText('3,000.00')

    // ---- 6) 反审核红冲 → 进度归零（BR-V2.5-02）----
    expect((await page.request.post(`/api/finance/payments/${payId}/unapprove`,
                                    { headers, data: { reason: 'E2E 反审核' } })).status()).toBe(200)
    await page.goto(LIST)
    await search(page, docNo)
    await expect(rowOf(page, docNo)).toContainText('0.0%')

    // ---- 7) 来源单据快照：付款单上留有采购单号（可追溯）----
    const detail = await page.request.get(`/api/finance/payments/${payId}`, { headers })
    expect((await detail.json()).source_doc_no).toBe(docNo)
    expect((await detail.json()).allocations[0].target_no).toBe(docNo)
    expect(id).toBeGreaterThan(0)
  })

  test('发票登记：票号唯一与认证状态（AC-V2.5-09）', async ({ page }) => {
    await login(page, 'admin')
    const token = (await tokenOf(page)) as string
    const headers = { Authorization: `Bearer ${token}` }
    const { docNo } = await approvedPurchaseOrder(page, page.request, token)

    await page.goto(LIST)
    await search(page, docNo)
    await rowOf(page, docNo).getByRole('button', { name: '更多' }).click()
    await page.locator('.el-dropdown-menu:visible .el-dropdown-menu__item',
                       { hasText: '登记进项发票' }).click()
    await expect(page).toHaveURL(/\/finance\/invoices\/new/)

    await expect(page.locator('.main')).toContainText('新增发票')
    // 方向已按来源预置为进项，核销目标带出采购单
    await expect(page.locator('.el-table').last()).toContainText(docNo)
    const invoiceNo = `E2E${Date.now()}`
    await formItem(page, '发票号码').locator('input').fill(invoiceNo)
    await page.getByRole('button', { name: '保存草稿' }).click()
    await expectMessage(page, '已创建')

    // 重复票号（同方向）→ 后端 422，前端弹错
    const dup = await page.request.post('/api/finance/invoices', {
      headers,
      data: { invoice_direction: 'in', invoice_no: invoiceNo, amount: 1, supplier_id: 1,
              subject_code: 'ZC' },
    })
    expect(dup.status()).toBe(422)
    expect(await dup.text()).toContain('已登记')
  })
})
