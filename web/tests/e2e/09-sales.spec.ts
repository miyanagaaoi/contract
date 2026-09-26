import { expect, test } from '@playwright/test'

import { addFirstItemRow, formItem, login, pickSelectOption, readCreatedDocNo, trackRuntimeErrors } from './helpers'

const ORDER_LIST = '/sales/orders'
const REQ_LIST = '/sales/requests'

test.describe('销售线', () => {
  test('销售订单列表加载，无运行时错误', async ({ page }) => {
    const errors = trackRuntimeErrors(page)
    await login(page, 'seller')
    await page.goto(ORDER_LIST)

    await expect(page.locator('.main')).toContainText('销售订单')
    const table = page.locator('.el-table').first()
    for (const label of ['单号', '单据日期', '状态', '客户', '金额', '经办人']) {
      await expect(table.getByRole('columnheader', { name: label, exact: true })).toBeVisible()
    }

    expect(errors).toEqual([])
  })

  test('销售员新建销售订单并保存草稿', async ({ page }) => {
    await login(page, 'seller')
    await page.goto(`${ORDER_LIST}/new`)
    await expect(page.locator('.main')).toContainText('新增销售订单')

    // 客户为必填（后端强制），先选客户档案
    await pickSelectOption(page, formItem(page, '客户').locator('input'))

    await addFirstItemRow(page, '2')
    await page.getByRole('button', { name: '保存草稿' }).click()
    const docNo = await readCreatedDocNo(page)
    await expect(page).toHaveURL(new RegExp(`${ORDER_LIST}$`))

    await page.getByPlaceholder('单号 / 来源单号 / 合同号 / 往来单位').fill(docNo)
    await page.getByRole('button', { name: '查询' }).click()
    await expect(page.locator('.el-table__row').filter({ hasText: docNo })).toContainText('草稿')
  })

  test('销售员没有采购菜单（权限裁剪）', async ({ page }) => {
    await login(page, 'seller')
    const aside = page.locator('.aside')
    await expect(aside).toContainText('销售管理')
    await expect(aside).not.toContainText('采购管理')
  })

  test('销售申请单列表可达，且可见导出与新增入口', async ({ page }) => {
    await login(page, 'admin')
    await page.goto(REQ_LIST)

    await expect(page.locator('.main')).toContainText('销售申请单')
    await expect(page.locator('.main')).toContainText('导出')
    await expect(page.getByRole('button', { name: '新增' })).toBeVisible()
  })
})
