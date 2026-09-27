import { expect, test } from '@playwright/test'

import { login } from './helpers'

/**
 * 未保存离开保护（T1-1）。
 *
 * 背景：`DocFormPage` 是全项目唯一会**静默丢数据**的路径——录入几十行行项后
 * 误点「返回列表」，此前不会有任何提示。
 *
 * 实现要点（决定了断言的写法）：确认走的是「全局路由守卫 + 组件注册」
 * （`@/utils/unsaved` + `router/index.ts` 的 `beforeEach`），**不是**
 * `onBeforeRouteLeave`——因为表单壳是被页面复用的子组件，而该守卫只对
 * 路由组件生效。
 *
 * 因此这里必须用 **SPA 内导航**（点击侧栏菜单）触发守卫；
 * `page.goto()` 是整页加载，不会经过路由守卫，也就测不出拦截。
 */
const REQ_NEW = '/purchase/requests/new'

test.describe('未保存离开保护', () => {
  test('未编辑时导航不被拦截', async ({ page }) => {
    await login(page, 'buyer')
    await page.goto(REQ_NEW)
    await expect(page.locator('.main')).toContainText('新增采购申请单')

    await page.locator('.aside').getByText('首页看板', { exact: true }).click()

    // 无确认框，直接回到看板
    await expect(page).toHaveURL(/127\.0\.0\.1:5173\/$/)
    await expect(page.locator('.el-message-box')).toHaveCount(0)
  })

  test('录入行项后离开 → 先确认；取消留在本页，确认才离开', async ({ page }) => {
    await login(page, 'buyer')
    await page.goto(REQ_NEW)
    await expect(page.locator('.main')).toContainText('新增采购申请单')

    // 添加一行行项 → 脏标记置位
    await page.getByRole('button', { name: '添加行' }).click()
    await expect(page.locator('.el-table__row').first()).toBeVisible()

    // 第一次导航：取消
    const box = page.locator('.el-message-box')
    await page.locator('.aside').getByText('首页看板', { exact: true }).click()
    await expect(box).toBeVisible()
    await box.getByRole('button', { name: '留在本页' }).click()
    await expect(page).toHaveURL(/\/purchase\/requests\/new$/)
    await expect(page.locator('.main')).toContainText('新增采购申请单')

    // 第二次导航：确认离开
    await page.locator('.aside').getByText('首页看板', { exact: true }).click()
    await expect(box).toBeVisible()
    await box.getByRole('button', { name: '离开' }).click()
    await expect(page).toHaveURL(/127\.0\.0\.1:5173\/$/)
  })

  test('保存成功后离开不再拦截', async ({ page }) => {
    await login(page, 'buyer')
    await page.goto(REQ_NEW)
    await expect(page.locator('.main')).toContainText('新增采购申请单')

    await page.getByRole('button', { name: '添加行' }).click()
    const itemsTable = page.locator('.el-table').last()
    const itemRow = itemsTable.locator('.el-table__row').first()
    await itemRow.locator('td').nth(1).locator('.el-select').click()
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first().click()
    await itemRow.locator('td').nth(4).locator('input').fill('1')

    await page.getByRole('button', { name: '保存草稿' }).click()
    await expect(page.locator('.el-message').filter({ hasText: '已创建' }).last()).toBeVisible()

    // 保存成功 = 内容已落库 → 脏标记清除，导航不再需要确认
    await page.locator('.aside').getByText('首页看板', { exact: true }).click()
    await expect(page).toHaveURL(/127\.0\.0\.1:5173\/$/)
    await expect(page.locator('.el-message-box')).toHaveCount(0)
  })
})
