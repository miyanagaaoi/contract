import { expect, test } from '@playwright/test'

import { login } from './helpers'

/**
 * 经办人下拉（回归：函数未导入导致的静默失败）。
 *
 * 缺陷背景：`DocFormPage.vue` 调用 `fetchMasterOptions('user')` 却**从未 import 它**，
 * 运行时抛 `ReferenceError` 并被同一行的 `catch { handlerOptions = [] }` 静默吞掉。
 * 后果是共用表单壳（8 类单据）的经办人下拉恒为空：
 * - 默认值只能回退渲染成裸 ID（如 `1`），而不是「系统管理员（admin）」；
 * - 用户也无法改选其他账号。
 *
 * 断言「显示登录名而不是 ID」即可锁定该缺陷：ID 是纯数字，不含 `e2e_buyer`。
 */
test.describe('经办人下拉', () => {
  test('默认显示当前账号名称，且可改选其他账号', async ({ page }) => {
    await login(page, 'buyer')
    await page.goto('/purchase/requests/new')
    await expect(page.locator('.main')).toContainText('新增采购申请单')

    const item = page.locator('.el-form-item').filter({
      has: page.locator('.el-form-item__label', { hasText: /^经办人$/ }),
    })

    // 1) 默认值是「姓名（登录名）」，不是裸 ID
    await expect(item).toContainText('e2e_buyer')

    // 2) 下拉能取到多个账号（漏 import 时选项恒为 0）
    await item.locator('.el-select').first().click()
    const opts = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    await expect(opts.first()).toBeVisible({ timeout: 10_000 })
    expect(await opts.count()).toBeGreaterThan(1)

    // 3) 改选另一个账号后，显示值随之变化
    const other = opts.filter({ hasNotText: 'e2e_buyer' }).first()
    const otherText = (await other.innerText()).trim()
    await other.click()
    await expect(item).toContainText(otherText.split('（')[0])
  })
})
