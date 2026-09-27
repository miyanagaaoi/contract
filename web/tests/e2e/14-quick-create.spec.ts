import { expect, test } from '@playwright/test'

import { login } from './helpers'

/**
 * 快速新增物料（回归：接口 404）。
 *
 * 缺陷背景：`QuickCreateDialog` 的 PATH 写作 `/products` / `/product-types` / `/uoms`，
 * 而 `http` 的 baseURL 是 `/api` → 请求落到 `/api/products`；后端真实路由是
 * `/api/master/products`（见 app/routers/master.py）→ **保存必然 404**，
 * 且弹窗内的「商品类型 / 计量单位」下拉因同样原因恒为空（404 被 catch 静默吞掉）。
 *
 * 该缺陷长期未被发现：11-master-product.spec.ts 只覆盖了「名称为空」的前端校验分支，
 * 从未真正提交过请求。本用例锁定「下拉能取到数据」这一最低限度证据。
 */
test.describe('快速新增物料', () => {
  test('弹窗内的计量单位下拉能加载数据（回归 404）', async ({ page }) => {
    await login(page, 'buyer')
    await page.goto('/purchase/requests/new')
    await expect(page.locator('.main')).toContainText('新增采购申请单')

    // 添加一行，点物料列旁的「＋」（title=快速新增物料）
    await page.getByRole('button', { name: '添加行' }).click()
    const row = page.locator('.el-table').last().locator('.el-table__row').first()
    await row.getByRole('button', { name: '＋' }).click()

    const quick = page.locator('.el-dialog:visible').filter({ hasText: '新增物料档案' })
    await expect(quick).toBeVisible()

    // 计量单位下拉必须有选项；路径写错时该请求 404、下拉恒为空
    await quick.locator('.el-form-item').filter({ hasText: '计量单位' }).locator('.el-select').click()
    await expect(page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first())
      .toBeVisible({ timeout: 10_000 })
  })
})
