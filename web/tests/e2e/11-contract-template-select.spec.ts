import { expect, test } from '@playwright/test'

import { login } from './helpers'

/**
 * 回归：新增合同页的「合同模板」下拉必须能加载并选中模板。
 * 背景（CR-056）：曾因页面调用了未导入的 fetchContractTemplates，运行时 ReferenceError
 * 被 catch 静默吞掉，导致下拉为空、无法选中模板。
 */
test('新增合同可选中合同模板', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))

  await login(page)
  await page.goto('/contracts')
  await page.getByRole('button', { name: /新增合同/ }).first().click()
  await page.waitForTimeout(800)

  const dialog = page.locator('.el-dialog').last()
  const select = dialog.locator('.el-form-item', { hasText: '合同模板' }).locator('.el-select').first()
  await select.click()

  const option = page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first()
  await expect(option).toBeVisible({ timeout: 10_000 })
  const label = (await option.textContent()) || ''
  expect(label.length).toBeGreaterThan(0)
  await option.click()

  // 选中后：下拉框显示所选模板，且模板字段表单出现
  await expect(select).toContainText(label.split('（')[0])
  await expect(dialog.getByText('正文预览')).toBeVisible()
  expect(errors).toEqual([])
})
