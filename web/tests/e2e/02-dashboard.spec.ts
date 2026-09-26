import { expect, test } from '@playwright/test'

import { login, mainArea, trackRuntimeErrors } from './helpers'

test.describe('首页看板', () => {
  test('统计卡与待办区正常渲染，无运行时错误', async ({ page }) => {
    const errors = trackRuntimeErrors(page)
    await login(page, 'admin')

    const main = mainArea(page)
    await expect(main).toContainText('合同总数（有效）')
    await expect(main).toContainText('框架合同')
    await expect(main).toContainText('质保即将到期')
    await expect(main).toContainText('质保已到期（未处理）')
    await expect(main).toContainText('待我审核')

    // 统计卡数字必须是数字（不能出现 undefined / NaN）
    const nums = await page.locator('.card .num').allInnerTexts()
    expect(nums.length).toBeGreaterThanOrEqual(4)
    for (const n of nums) {
      expect(n.trim()).toMatch(/^-?\d+(\.\d+)?$/)
    }

    expect(errors).toEqual([])
  })

  test('库存预警区块对管理层账号可用或无数据提示', async ({ page }) => {
    await login(page, 'admin')
    const main = mainArea(page)
    // 有权限时应展示库存预警卡片；无数据时展示空态文案，二者必有其一
    await expect(main).toContainText(/库存预警|暂无/)
  })

  test('点击统计跳转不产生死链（路由可达）', async ({ page }) => {
    await login(page, 'admin')
    await page.locator('.aside').getByText('合同管理', { exact: true }).click()
    await expect(page).toHaveURL(/\/contracts$/)
    await expect(mainArea(page)).toContainText('合同')
  })
})
