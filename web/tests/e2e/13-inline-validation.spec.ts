import { expect, test } from '@playwright/test'

import { login } from './helpers'

/**
 * 行项校验行内化（T3-6）。
 *
 * 背景：原先遇到**第一个**错误就 `ElMessage.warning` 并 return —— toast 一闪即逝，
 * 用户改完第一个再提交才发现第二个，长表单要来回好几轮。
 *
 * 现在改为：一次性收集**全部**行错误 → 顶部持久提示条（列出每一行的问题）
 * + 失败行高亮。断言必须验证「持久」（alert 仍可见）而非「瞬时」（toast 消失）。
 *
 * 注意：`row-class-name` 而非新增列——行项表的 td 索引被 helpers.ts 依赖。
 */
const REQ_NEW = '/purchase/requests/new'

test.describe('行项校验行内化', () => {
  test('校验失败：错误持久显示在表单内、并高亮具体错误行', async ({ page }) => {
    await login(page, 'buyer')
    await page.goto(REQ_NEW)
    await expect(page.locator('.main')).toContainText('新增采购申请单')

    // 加一行但不选物料 → 直接保存
    await page.getByRole('button', { name: '添加行' }).click()
    await expect(page.locator('.el-table__row').first()).toBeVisible()
    await page.getByRole('button', { name: '保存草稿' }).click()

    // 1) 顶部提示条：持久呈现，且精确到行
    const alert = page.locator('.el-alert').filter({ hasText: '行项校验未通过' })
    await expect(alert).toBeVisible()
    await expect(alert).toContainText('第 1 行：请选择物料')

    // 2) 错误行高亮（用 row-class，不动列结构）
    await expect(page.locator('.el-table__row.row-error')).toHaveCount(1)

    // 3) 修好之后提示自动消失，且能正常保存
    const itemsTable = page.locator('.el-table').last()
    await itemsTable.locator('.el-table__row').first().locator('td').nth(1).locator('.el-select').click()
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first().click()
    await page.getByRole('button', { name: '保存草稿' }).click()

    await expect(page.locator('.el-message').filter({ hasText: '已创建' }).last()).toBeVisible()
    await expect(page.locator('.el-alert').filter({ hasText: '行项校验未通过' })).toHaveCount(0)
    await expect(page.locator('.el-table__row.row-error')).toHaveCount(0)
  })
})
