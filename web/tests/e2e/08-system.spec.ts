import { expect, test } from '@playwright/test'

import { login, mainArea, trackRuntimeErrors } from './helpers'

const TABS = ['数据字典', '系统参数', '编号规则', '操作日志', '变更历史', '备份', '关于']

test.describe('系统管理', () => {
  test('全部页签可达，关于页显示版本与权限点数量', async ({ page }) => {
    const errors = trackRuntimeErrors(page)
    await login(page, 'admin')
    await page.goto('/system')

    await expect(mainArea(page)).toContainText('系统管理')
    for (const name of TABS) {
      await expect(page.getByRole('tab', { name })).toBeVisible()
    }

    await page.getByRole('tab', { name: '关于' }).click()
    await expect(mainArea(page)).toContainText('版本')
    await expect(mainArea(page)).toContainText('权限点数量')
    await expect(mainArea(page)).toContainText('数据库类型')

    expect(errors).toEqual([])
  })

  test('系统参数页签：参数表单可保存（值保持不变，验证接口连通）', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/system')
    await page.getByRole('tab', { name: '系统参数' }).click()

    await expect(page.getByRole('button', { name: '保存参数' })).toBeVisible()
    await page.getByRole('button', { name: '保存参数' }).click()
    await expect(page.locator('.el-message').last()).toContainText(/保存|成功/)
  })

  test('编号规则页签：展示各单据前缀与下一个编号', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/system')
    await page.getByRole('tab', { name: '编号规则' }).click()

    // el-tab-pane 用 v-show 切换，隐藏页签的表格仍在 DOM 中，必须限定 :visible
    const table = page.locator('.el-table:visible').first()
    for (const label of ['单据/档案', '前缀', '序号长度', '重置策略', '下一个编号']) {
      await expect(table.locator('th').filter({ hasText: label }).first()).toBeVisible()
    }
    await expect(page.getByRole('button', { name: '保存编号规则' })).toBeVisible()
  })

  test('操作日志：可按关键词查询', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/system')
    await page.getByRole('tab', { name: '操作日志' }).click()

    await page.getByRole('button', { name: '查询' }).click()
    const table = page.locator('.el-table:visible').first()
    await expect(table.locator('.el-table__row').first()).toBeVisible()
    await expect(table.getByRole('columnheader', { name: '操作人', exact: true })).toBeVisible()
  })

  test('变更历史：可查询合同字段变更', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/system')
    await page.getByRole('tab', { name: '变更历史' }).click()

    await page.getByRole('button', { name: '查询' }).click()
    const table = page.locator('.el-table:visible').first()
    for (const label of ['合同编号', '合同名称', '字段', '旧值', '新值', '操作人']) {
      await expect(table.locator('th').filter({ hasText: label }).first()).toBeVisible()
    }
  })

  test('备份页签：列出备份文件并提供生成入口', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/system')
    await page.getByRole('tab', { name: '备份' }).click()

    await expect(page.getByRole('button', { name: '生成备份' })).toBeVisible()
    await expect(page.getByRole('button', { name: '刷新列表' })).toBeVisible()
    await expect(page.locator('.el-table:visible').first()
      .getByRole('columnheader', { name: '备份文件', exact: true })).toBeVisible()
  })
})
