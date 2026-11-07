import { expect, test } from '@playwright/test'

import { login } from './helpers'

/**
 * 回归：询价单页面（含定标/打印比价单代码）能正常加载，无运行时错误。
 * 说明：询价菜单权限沿用 purchase.view，故用采购员账号。
 */
test('询价单页面可加载且无运行时错误', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })

  await login(page, 'buyer')
  await page.goto('/purchase/rfq')
  await expect(page.getByRole('button', { name: /新建询价单/ })).toBeVisible()
  await expect(page.locator('.el-table')).toBeVisible()
  expect(errors).toEqual([])
})
