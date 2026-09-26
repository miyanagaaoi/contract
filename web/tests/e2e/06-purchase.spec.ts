import { expect, test, type Page } from '@playwright/test'

import { expectMessage, formItem, login, logout, pickSelectOption, readCreatedDocNo, trackRuntimeErrors } from './helpers'

const REQ_LIST = '/purchase/requests'

/** 在单据列表按单号定位行 */
function rowOf(page: Page, docNo: string) {
  return page.locator('.el-table__row').filter({ hasText: docNo })
}

/** 新建一张采购申请单（选物料 + 数量），返回单号；submit=true 时同时提交 */
async function createPurchaseRequest(page: Page, qty = '3', submit = true): Promise<string> {
  await page.goto(`${REQ_LIST}/new`)
  await expect(page.locator('.main')).toContainText('新增采购申请单')

  const itemsTable = page.locator('.el-table').last()
  await page.getByRole('button', { name: '添加行' }).click()
  await expect(itemsTable.locator('.el-table__row')).toHaveCount(1)

  const itemRow = itemsTable.locator('.el-table__row').first()
  // 物料：远程下拉，组件挂载时已预加载选项；第 2 列为物料（第 1 列是序号）
  await itemRow.locator('td').nth(1).locator('.el-select').click()
  await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first().click()

  // 数量（第 5 列为「数量」）
  await itemRow.locator('td').nth(4).locator('input').fill(qty)

  await formItem(page, '用途说明').locator('textarea').fill('E2E 自动化采购申请')

  await page.getByRole('button', { name: submit ? '保存并提交' : '保存草稿' }).click()
  const docNo = await readCreatedDocNo(page)
  await expect(page).toHaveURL(new RegExp(`${REQ_LIST}$`))
  return docNo
}

test.describe('采购流程', () => {
  test('列表加载：表头、筛选与新增入口齐全，无运行时错误', async ({ page }) => {
    const errors = trackRuntimeErrors(page)
    await login(page, 'buyer')
    await page.goto(REQ_LIST)

    await expect(page.locator('.main')).toContainText('采购申请单')
    const table = page.locator('.el-table').first()
    for (const label of ['单号', '单据日期', '状态', '供应商', '金额', '经办人', '关联合同', '来源单号']) {
      await expect(table.getByRole('columnheader', { name: label, exact: true })).toBeVisible()
    }
    await expect(page.getByRole('button', { name: '新增' })).toBeVisible()

    expect(errors).toEqual([])
  })

  test('采购员：能提交但不能审核（列表无审核按钮）', async ({ page }) => {
    await login(page, 'buyer')
    await page.goto(REQ_LIST)
    await expect(page.getByRole('button', { name: '审核' })).toHaveCount(0)
  })

  test('采购员创建并提交申请单 → 主管审核通过 → 下推生成采购单', async ({ page }) => {
    // ---------- 1) 采购员录入并提交 ----------
    await login(page, 'buyer')
    const docNo = await createPurchaseRequest(page)

    await page.getByPlaceholder('单号 / 来源单号 / 合同号 / 往来单位').fill(docNo)
    await page.getByRole('button', { name: '查询' }).click()
    await expect(rowOf(page, docNo)).toHaveCount(1)
    await expect(rowOf(page, docNo)).toContainText('待审核')

    // ---------- 2) 管理员审核 ----------
    await logout(page)
    await login(page, 'admin')
    await page.goto(REQ_LIST)
    await page.getByPlaceholder('单号 / 来源单号 / 合同号 / 往来单位').fill(docNo)
    await page.getByRole('button', { name: '查询' }).click()
    await expect(rowOf(page, docNo)).toHaveCount(1)

    await rowOf(page, docNo).getByRole('button', { name: '审核' }).click()
    const approveDialog = page.locator('.el-dialog:visible').filter({ hasText: '审核通过' })
    await expect(approveDialog).toContainText(docNo)
    await approveDialog.getByRole('button', { name: '确定审核通过' }).click()
    await expectMessage(page, '操作成功')

    // ---------- 3) 下推采购单 ----------
    await page.getByRole('button', { name: '查询' }).click()
    const approvedRow = rowOf(page, docNo)
    await expect(approvedRow).toContainText('已审核')
    await approvedRow.getByRole('button', { name: '下推' }).click()

    const pushDialog = page.locator('.el-dialog:visible').filter({ hasText: '下推生成采购单' })
    await expect(pushDialog).toBeVisible()
    await expect(pushDialog).toContainText(docNo)

    // 下推必须指定供应商（后端强制）
    await pickSelectOption(page, formItem(page, '供应商', pushDialog).locator('input'))
    await pushDialog.getByRole('button', { name: '确认下推' }).click()

    await expect(page).toHaveURL(/\/purchase\/orders\/\d+\/edit$/)
    await expect(page.locator('.main')).toContainText('编辑采购单')

    // ---------- 4) V2.1 / N7·N8：全部下推完毕后申请单自动「已完成」，且不再显示「下推」 ----------
    await page.goto(REQ_LIST)
    await page.getByPlaceholder('单号 / 来源单号 / 合同号 / 往来单位').fill(docNo)
    await page.getByRole('button', { name: '查询' }).click()
    const doneRow = rowOf(page, docNo)
    await expect(doneRow).toContainText('已完成')
    await expect(doneRow.getByRole('button', { name: '下推' })).toHaveCount(0)
  })

  test('业务规则：非管理员不能审核自己创建的单据（V2.1 修订 AC-V2-15）', async ({ page }) => {
    // ⚠️ V2.1 起 `sysadmin`（即 e2e_admin）**可以**自审，因此拒绝路径必须改用
    // "有审核权但非管理员"的账号（e2e_pm / purchase_manager），否则该用例会静默失效。
    await login(page, 'pm')
    const docNo = await createPurchaseRequest(page)

    await page.goto(REQ_LIST)
    await page.getByPlaceholder('单号 / 来源单号 / 合同号 / 往来单位').fill(docNo)
    await page.getByRole('button', { name: '查询' }).click()

    await rowOf(page, docNo).getByRole('button', { name: '审核' }).click()
    const approveDialog = page.locator('.el-dialog:visible').filter({ hasText: '审核通过' })
    await approveDialog.getByRole('button', { name: '确定审核通过' }).click()

    // 后端 422 → 拦截器以错误提示展示，单据状态保持「待审核」
    await expect(page.locator('.el-message--error').last()).toContainText('不能审核自己创建的单据')
    await approveDialog.getByRole('button', { name: '取消' }).click()
    await page.getByRole('button', { name: '查询' }).click()
    await expect(rowOf(page, docNo)).toContainText('待审核')
  })

  test('V2.1 / AC-V2.1-06：管理员可审核自己提交的申请单', async ({ page }) => {
    await login(page, 'admin')
    const docNo = await createPurchaseRequest(page)

    await page.goto(REQ_LIST)
    await page.getByPlaceholder('单号 / 来源单号 / 合同号 / 往来单位').fill(docNo)
    await page.getByRole('button', { name: '查询' }).click()

    await rowOf(page, docNo).getByRole('button', { name: '审核' }).click()
    const approveDialog = page.locator('.el-dialog:visible').filter({ hasText: '审核通过' })
    await approveDialog.getByRole('button', { name: '确定审核通过' }).click()

    await expectMessage(page, '操作成功')
    await page.getByRole('button', { name: '查询' }).click()
    await expect(rowOf(page, docNo)).toContainText('已审核')
  })

  test('草稿单可编辑、可提交，必填校验拦截空行项', async ({ page }) => {
    await login(page, 'buyer')

    // 没有任何行项时保存 → 前端拦截并提示
    await page.goto(`${REQ_LIST}/new`)
    await page.getByRole('button', { name: '保存草稿' }).click()
    await expectMessage(page, '请至少添加一行行项')

    // 补行项后保存草稿成功
    await page.getByRole('button', { name: '添加行' }).click()
    const itemsTable = page.locator('.el-table').last()
    await itemsTable.locator('.el-table__row').first().locator('td').nth(1).locator('.el-select').click()
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first().click()
    await page.getByRole('button', { name: '保存草稿' }).click()
    const docNo = await readCreatedDocNo(page)

    // 草稿状态可编辑，且可提交
    await page.getByPlaceholder('单号 / 来源单号 / 合同号 / 往来单位').fill(docNo)
    await page.getByRole('button', { name: '查询' }).click()
    await expect(rowOf(page, docNo)).toContainText('草稿')
    await expect(rowOf(page, docNo).getByRole('button', { name: '编辑' })).toBeVisible()

    await rowOf(page, docNo).getByRole('button', { name: '提交' }).click()
    await expectMessage(page, '提交成功')
    await page.getByRole('button', { name: '查询' }).click()
    await expect(rowOf(page, docNo)).toContainText('待审核')
  })

  test('详情抽屉展示行项与变更历史', async ({ page }) => {
    await login(page, 'admin')
    await page.goto(REQ_LIST)
    await page.locator('.el-table__row').first().getByRole('button', { name: '查看' }).click()

    const drawer = page.locator('.el-drawer:visible')
    await expect(drawer).toContainText('采购申请单详情')
    await expect(drawer).toContainText('行项明细')
    await expect(drawer).toContainText('变更历史')
  })

  test('行项合计行金额为数值，不出现 [object Object]（V2.1 / AC-V2.1-03）', async ({ page }) => {
    await login(page, 'buyer')
    await page.goto(`${REQ_LIST}/new`)

    const itemsTable = page.locator('.el-table').last()
    await page.getByRole('button', { name: '添加行' }).click()
    const itemRow = itemsTable.locator('.el-table__row').first()

    // 选物料（第 2 列）；数量 3、单价 5 → 合计应为 15.00
    await itemRow.locator('td').nth(1).locator('.el-select').click()
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first().click()
    await itemRow.locator('td').nth(4).locator('input').fill('3')
    await itemRow.locator('td').nth(5).locator('input').fill('5')
    await itemRow.locator('td').nth(5).locator('input').blur()

    const footer = itemsTable.locator('.el-table__footer')
    await expect(footer).toContainText('合计')
    // 回归防线：曾因 `fmtMoney(totalAmount)` 漏写 `.value`（传入 computed ref 对象）
    // 导致合计行渲染为 "[object Object]"；详见 23-v2.1-system-design.md §3。
    await expect(footer).not.toContainText('[object Object]')
    await expect(footer).toContainText('15.00')
  })

  test('V2.1：未选关联合同时「提取合同明细 / 查看合同详情」为禁用态', async ({ page }) => {
    await login(page, 'buyer')
    await page.goto(`${REQ_LIST}/new`)

    // N2：提取合同明细入口存在，但未选合同时不可点
    await expect(page.getByRole('button', { name: '提取合同明细' })).toBeDisabled()
    // N5：合同详情抽屉入口同理
    await expect(page.getByRole('button', { name: '查看合同详情' })).toBeDisabled()
    await expect(page.locator('.main')).toContainText('请先选择关联合同')
  })
})
