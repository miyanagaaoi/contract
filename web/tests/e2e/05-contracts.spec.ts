import { expect, test } from '@playwright/test'

import { expectMessage, formItem, login, mainArea, pickSelectOption, trackRuntimeErrors, uniqueName } from './helpers'

test.describe('合同台账', () => {
  test('列表加载：表头与统计文案齐全，无运行时错误', async ({ page }) => {
    const errors = trackRuntimeErrors(page)
    await login(page, 'admin')
    await page.goto('/contracts')

    await expect(mainArea(page)).toContainText('合同台账（共')
    const table = page.locator('.el-table').first()
    // 注意：「已付」「付款比例」已合并为「已付（比例）」；标签并入「合同名称 / 标签」列
    for (const label of ['合同编号', '合同名称 / 标签', '类型', '甲方', '乙方', '金额', '已付（比例）', '状态', '经办人', '操作']) {
      await expect(table.getByRole('columnheader', { name: label, exact: true })).toBeVisible()
    }
    await expect(page.locator('.el-table__row').first()).toBeVisible()

    expect(errors).toEqual([])
  })

  test('关键词检索与重置', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/contracts')

    await page.getByPlaceholder('编号/名称/甲乙方').fill('PUR-DEMO')
    await page.getByRole('button', { name: '查询' }).click()
    await expect(page.locator('.el-table__row').first()).toContainText('PUR-DEMO')

    await page.getByRole('button', { name: '重置' }).click()
    await expect(page.getByPlaceholder('编号/名称/甲乙方')).toHaveValue('')
  })

  test('框架树视图切换不报错', async ({ page }) => {
    const errors = trackRuntimeErrors(page)
    await login(page, 'admin')
    await page.goto('/contracts')

    // el-radio-button 的真实 input 被 span 覆盖，需点外层 label
    await page.locator('.el-radio-button', { hasText: '框架树' }).click()
    await expect(mainArea(page)).toContainText('框架树视图（共')
    await page.locator('.el-radio-button', { hasText: '平铺' }).click()
    await expect(mainArea(page)).toContainText('合同台账（共')

    expect(errors).toEqual([])
  })

  test('导出对话框：可选择导出列并可取消', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/contracts')

    await page.getByRole('button', { name: '导出 Excel（当前筛选）' }).click()
    const dialog = page.locator('.el-dialog:visible')
    await expect(dialog).toContainText('选择导出项')
    await expect(dialog).toContainText('将导出')
    await expect(dialog.getByRole('button', { name: '全选' })).toBeVisible()
    await expect(dialog.getByRole('button', { name: '恢复默认' })).toBeVisible()

    await dialog.getByRole('button', { name: '取消' }).click()
    await expect(dialog).toHaveCount(0)
  })

  test('新增合同 → 详情 → 编辑 → 停用 → 恢复（完整生命周期）', async ({ page }) => {
    const name = uniqueName('E2E合同')
    await login(page, 'admin')
    await page.goto('/contracts')

    // ---------- 新增 ----------
    await page.getByRole('button', { name: '＋ 新增合同' }).click()
    const dialog = page.locator('.el-dialog:visible').filter({ hasText: '新增合同' })
    await expect(dialog).toBeVisible()

    await formItem(page, '合同名称', dialog).locator('input').fill(name)

    // 类型：必须选一个支持自动编号的有效类型，否则后端会拒绝（"该类型暂不支持自动编号"）
    await pickSelectOption(page, formItem(page, '类型', dialog).locator('input'))
    // 我方公司
    await pickSelectOption(page, formItem(page, '我方公司', dialog).locator('input'))

    // 签订日期（决定自动编号的年份）；用 Enter 确认日期面板，避免 Esc 关闭整个弹窗
    const signDate = formItem(page, '签订日期', dialog).locator('input')
    await signDate.fill('2026-03-05')
    await signDate.press('Enter')

    // 甲/乙方：采购类类型下乙方为档案下拉，其余类型为纯文本
    for (const [label, text] of [['甲方', 'E2E甲方公司'], ['乙方', 'E2E乙方公司']] as const) {
      const cell = formItem(page, label, dialog)
      if (await cell.locator('.el-select').count()) {
        await pickSelectOption(page, cell.locator('input'))
      } else {
        await cell.locator('input').fill(text)
      }
    }

    await formItem(page, '合同金额', dialog).locator('input').fill('12345.67')
    await dialog.getByRole('button', { name: '保存' }).click()
    await expectMessage(page, '已新增合同')

    // ---------- 检索到新合同 ----------
    await page.getByPlaceholder('编号/名称/甲乙方').fill(name)
    await page.getByRole('button', { name: '查询' }).click()
    const row = page.locator('.el-table__row').filter({ hasText: name })
    await expect(row).toHaveCount(1)
    await expect(row).toContainText('12,345.67')
    // 自动编号应已生成
    await expect(row.locator('td').nth(1)).not.toBeEmpty()

    // ---------- 详情 ----------
    await row.getByRole('button', { name: '详情' }).click()
    const drawer = page.locator('.el-drawer:visible')
    await expect(drawer).toContainText(name)
    await expect(drawer).toContainText('变更历史')
    await drawer.locator('.el-drawer__close-btn').click()

    // ---------- 编辑 ----------
    const newName = `${name}-改`
    await row.getByRole('button', { name: '编辑' }).click()
    const editDialog = page.locator('.el-dialog:visible').filter({ hasText: '编辑合同' })
    await expect(editDialog).toBeVisible()
    await formItem(page, '合同名称', editDialog).locator('input').fill(newName)
    await editDialog.getByRole('button', { name: '保存' }).click()
    await expectMessage(page, '已保存')

    // ---------- 停用（软删除，需填原因）----------
    await page.getByPlaceholder('编号/名称/甲乙方').fill(newName)
    await page.getByRole('button', { name: '查询' }).click()
    const row2 = page.locator('.el-table__row').filter({ hasText: newName })
    await row2.getByRole('button', { name: '停用' }).click()
    await page.locator('.el-message-box input').fill('E2E 自动化测试停用')
    // 该确认框的确认按钮文案是「停用」（ElMessageBox.prompt 的 confirmButtonText）
    await page.locator('.el-message-box__btns button', { hasText: '停用' }).click()
    await expectMessage(page, '已停用')
    // 默认隐藏已停用合同
    await expect(page.locator('.el-table__row').filter({ hasText: newName })).toHaveCount(0)

    // ---------- 恢复 ----------
    await page.getByText('显示已停用', { exact: true }).click()
    await expect(page.locator('.el-table__row').filter({ hasText: newName })).toHaveCount(1)
    await page.locator('.el-table__row').filter({ hasText: newName })
      .getByRole('button', { name: '恢复' }).click()
    // 恢复用的是 ElMessageBox.confirm，中文 locale 下确认按钮为「确定」
    await page.locator('.el-message-box__btns button', { hasText: '确定' }).click()
    await expectMessage(page, '已恢复')
  })

  test('合同名称必填：留空保存给出中文提示且不关弹窗', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/contracts')

    await page.getByRole('button', { name: '＋ 新增合同' }).click()
    const dialog = page.locator('.el-dialog:visible').filter({ hasText: '新增合同' })
    await dialog.getByRole('button', { name: '保存' }).click()

    await expectMessage(page, '合同名称必填')
    await expect(dialog).toBeVisible()
  })
})
