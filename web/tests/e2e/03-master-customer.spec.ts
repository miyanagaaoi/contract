import { expect, test } from '@playwright/test'

import { expectMessage, formItem, login, mainArea, trackRuntimeErrors, uniqueName } from './helpers'

/**
 * 主数据（以「客户信息」为代表）走的是配置驱动的通用页 `MasterTablePage`，
 * 覆盖它的列表 / 检索 / 新增 / 编辑 / 启停用 / 删除即可代表客户、供应商、
 * 计量单位、仓库、物料 5 类档案的公共行为。
 */
test.describe('主数据 · 客户信息', () => {
  test('列表加载：表头齐全且无运行时错误', async ({ page }) => {
    const errors = trackRuntimeErrors(page)
    await login(page, 'admin')
    await page.goto('/master/customers')

    await expect(mainArea(page)).toContainText('客户信息')
    const table = page.locator('.el-table').first()
    for (const label of ['编码', '客户名称', '简称', '联系人', '联系电话', '等级', '授信额度', '状态']) {
      await expect(table.locator('th', { hasText: label })).toBeVisible()
    }
    await expect(page.locator('.el-table__empty-text')).toHaveCount(0)

    expect(errors).toEqual([])
  })

  test('关键词检索能命中演示数据', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/master/customers')

    await page.getByPlaceholder('名称 / 编码 / 简称 / 联系人').fill('华东机械')
    await page.getByRole('button', { name: '查询' }).click()

    await expect(page.locator('.el-table__body')).toContainText('华东机械')
  })

  test('新增 → 编辑 → 停用 → 启用 → 删除（含提示文案）', async ({ page }) => {
    const name = uniqueName('E2E客户')
    await login(page, 'admin')
    await page.goto('/master/customers')

    // ---- 新增 ----
    await page.locator('.el-card__header').getByRole('button', { name: '新增' }).click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '新增客户信息' })
    await expect(dialog).toBeVisible()
    await formItem(page, '客户名称').locator('input').fill(name)
    await dialog.getByRole('button', { name: '保存' }).click()
    await expectMessage(page, `已新增「${name}」`)

    // ---- 检索到新客户 ----
    await page.getByPlaceholder('名称 / 编码 / 简称 / 联系人').fill(name)
    await page.getByRole('button', { name: '查询' }).click()
    const row = page.locator('.el-table__row').filter({ hasText: name })
    await expect(row).toHaveCount(1)
    // 编码应自动生成（CUS 前缀），不是空值
    await expect(row.locator('td').nth(1)).not.toHaveText('—')

    // ---- 编辑（改简称）----
    const shortName = 'E2E简称'
    await row.getByRole('button', { name: '编辑' }).click()
    const editDialog = page.locator('.el-dialog').filter({ hasText: '编辑客户信息' })
    await expect(editDialog).toBeVisible()
    await formItem(page, '简称').locator('input').fill(shortName)
    await editDialog.getByRole('button', { name: '保存' }).click()
    await expectMessage(page, `已保存「${name}」`)
    await expect(page.locator('.el-table__row').filter({ hasText: name })).toContainText(shortName)

    // ---- 停用 ----
    await page.locator('.el-table__row').filter({ hasText: name })
      .getByRole('button', { name: '停用' }).click()
    await page.locator('.el-message-box__btns button', { hasText: '确定' }).click()
    await expectMessage(page, '已停用')
    await expect(page.locator('.el-table__row').filter({ hasText: name })).toContainText('停用')

    // ---- 启用 ----
    await page.locator('.el-table__row').filter({ hasText: name })
      .getByRole('button', { name: '启用' }).click()
    await page.locator('.el-message-box__btns button', { hasText: '确定' }).click()
    await expectMessage(page, '已启用')

    // ---- 删除 ----
    await page.locator('.el-table__row').filter({ hasText: name })
      .getByRole('button', { name: '删除' }).click()
    await page.locator('.el-message-box__btns button', { hasText: '删除' }).click()
    await expectMessage(page, '已删除')

    await page.getByRole('button', { name: '查询' }).click()
    await expect(page.locator('.el-table__row').filter({ hasText: name })).toHaveCount(0)
  })

  test('必填校验：客户名称为空时给出中文提示且不发起保存', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/master/customers')

    await page.locator('.el-card__header').getByRole('button', { name: '新增' }).click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '新增客户信息' })
    await dialog.getByRole('button', { name: '保存' }).click()

    await expectMessage(page, '请填写「客户名称」')
    await expect(dialog).toBeVisible()
  })

  test('重置按钮清空检索条件', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/master/customers')

    const keyword = page.getByPlaceholder('名称 / 编码 / 简称 / 联系人')
    await keyword.fill('不存在的客户XYZ')
    await page.getByRole('button', { name: '查询' }).click()
    await expect(page.locator('.el-table__row')).toHaveCount(0)

    await page.getByRole('button', { name: '重置' }).click()
    await expect(keyword).toHaveValue('')
    await expect(page.locator('.el-table__row').first()).toBeVisible()
  })
})
