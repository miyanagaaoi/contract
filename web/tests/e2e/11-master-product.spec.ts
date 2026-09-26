import { expect, test } from '@playwright/test'

import { formItem, login } from './helpers'

/**
 * V2.1 / T-V2.1-18 · 19：物料档案的商品类型树状选择与主数据快速新增。
 *
 * 对应 `22-v2.1-requirements.md`：
 * - AC-V2.1-19：商品类型以**树状展开**选择（父类型不可挂载物料）；
 * - AC-V2.1-20：商品类型 / 计量单位右侧有「快速新增」，弹窗保存后**回填当前表单**。
 */
test.describe('物料档案（V2.1 / N14·N15）', () => {
  test('新增物料：商品类型为树状选择，且商品类型/计量单位均有快速新增', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/master/products')
    await expect(page.locator('.main')).toContainText('物料档案')

    await page.getByRole('button', { name: '新增' }).click()
    const dialog = page.locator('.el-dialog:visible').filter({ hasText: '新增物料档案' })
    await expect(dialog).toBeVisible()

    // N14：商品类型用树状选择控件（Element Plus 的 el-tree-select 渲染为 el-select + 树面板）
    const typeItem = formItem(page, '商品类型', dialog)
    await expect(typeItem.locator('.el-select')).toBeVisible()

    // N15：两个字段都带「＋」快速新增按钮
    const addTypeBtn = typeItem.getByRole('button', { name: '＋' })
    await expect(addTypeBtn).toBeVisible()
    const uomItem = formItem(page, '计量单位', dialog)
    await expect(uomItem.getByRole('button', { name: '＋' })).toBeVisible()

    // 点击「＋」→ 弹出商品类型快建弹窗（无需离开物料表单）
    await addTypeBtn.click()
    await expect(page.locator('.el-dialog:visible').filter({ hasText: '新增商品类型' }))
      .toBeVisible()
    // 原物料表单仍在（未跳转、未丢内容）——BR-V2.1-10
    await expect(dialog).toBeVisible()
  })

  test('商品类型快建：名称为空时给出中文提示', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/master/products')

    await page.getByRole('button', { name: '新增' }).click()
    const dialog = page.locator('.el-dialog:visible').filter({ hasText: '新增物料档案' })
    await formItem(page, '商品类型', dialog).getByRole('button', { name: '＋' }).click()

    const quick = page.locator('.el-dialog:visible').filter({ hasText: '新增商品类型' })
    await expect(quick).toBeVisible()
    await quick.getByRole('button', { name: '保存并回填' }).click()
    await expect(page.locator('.el-message').last()).toContainText('名称必填')
  })
})
