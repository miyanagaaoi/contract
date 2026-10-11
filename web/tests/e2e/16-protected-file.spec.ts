import { expect, test, type Locator, type Page } from '@playwright/test'

import { expectMessage, login, trackRuntimeErrors, uniqueName } from './helpers'

/**
 * V2.2 缺陷回归：受保护文件（附件预览/下载、台账导出、导入模板）必须**带令牌**取回。
 *
 * 根因：这些文件接口都由 HTTPBearer 鉴权，令牌只存在于 axios 请求头
 * （`@/utils/token` → localStorage）。旧实现用 `window.open('/api/...')` 让浏览器
 * 直接导航，导航请求**不带 Authorization**，后端一律回 401「未登录，请先登录」——
 * 表现为"上传附件后点预览提示未登录"。
 *
 * 修复后统一走 blob：先由 axios 取回二进制，再用 blob URL 渲染（预览）或
 * `a[download]` 保存（下载）。因此本用例断言的是"弹出的是 blob: 窗口 / 确实产生下载"，
 * 而不是"打开了一个 /api/... 地址"。
 */

/** 1×1 透明 PNG：图片预览走 `window.open` + blob URL 渲染路径 */
const PNG_1PX = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==',
  'base64',
)

/** 打开合同列表第一行的详情抽屉（演示库已有数据；不依赖具体编号） */
async function openFirstContractDetail(page: Page) {
  await page.goto('/contracts')
  const row = page.locator('.el-table__row').first()
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: '详情' }).click()
  const drawer = page.locator('.el-drawer:visible')
  await expect(drawer).toContainText('附件')
  return drawer
}

/** 上传一个附件并等待列表出现该行 */
async function uploadAttachment(
  page: Page,
  drawer: Locator,
  file: { name: string; mimeType: string; buffer: Buffer },
) {
  await drawer.locator('input[type="file"]').setInputFiles(file)
  await expectMessage(page, '上传成功')
  const attRow = drawer.locator('.el-table__row').filter({ hasText: file.name })
  await expect(attRow).toHaveCount(1)
  return attRow
}

/** 删除附件行（确认框中文 locale 下确认按钮为「确定」） */
async function removeAttachment(page: Page, attRow: Locator) {
  await attRow.getByRole('button', { name: '删除' }).click()
  await page.locator('.el-message-box__btns button', { hasText: '确定' }).click()
  await expectMessage(page, '已删除')
}

test.describe('受保护文件：附件预览/下载与导出', () => {
  test('附件预览：按 blob 打开图片，不再提示「未登录，请先登录」', async ({ page }) => {
    const errors = trackRuntimeErrors(page)
    await login(page, 'admin')
    const drawer = await openFirstContractDetail(page)

    const fileName = `${uniqueName('E2E附件')}.png`
    const attRow = await uploadAttachment(page, drawer, {
      name: fileName, mimeType: 'image/png', buffer: PNG_1PX,
    })

    const popupPromise = page.waitForEvent('popup')
    await attRow.getByRole('button', { name: '预览' }).click()
    const popup = await popupPromise
    // 修复前：窗口地址是 /api/attachments/{id}/download?inline=1，页面里是 401 的 JSON
    await expect.poll(() => popup.url(), { timeout: 15_000 }).toMatch(/^blob:/)
    await expect(page.locator('.el-message').filter({ hasText: '未登录' })).toHaveCount(0)
    await popup.close()

    // 对照（根因证据）：浏览器直接导航**不带** Authorization —— 旧实现 `window.open('/api/...')`
    // 走的正是这条路径，后端只会回 401。有这条断言，上面的 `blob:` 断言才不算"接口本来就放行"。
    const direct = await page.request.get('/api/attachments/1/download')
    expect(direct.status()).toBe(401)
    expect((await direct.json()).detail).toBe('未登录，请先登录')

    await removeAttachment(page, attRow)
    await expect(drawer.locator('.el-table__row').filter({ hasText: fileName })).toHaveCount(0)
    expect(errors).toEqual([])
  })

  test('附件下载：不可预览类型走带令牌的 blob 保存，文件名保持原样', async ({ page }) => {
    await login(page, 'admin')
    const drawer = await openFirstContractDetail(page)

    const fileName = `${uniqueName('E2E附件')}.txt`
    const attRow = await uploadAttachment(page, drawer, {
      name: fileName, mimeType: 'text/plain', buffer: Buffer.from('E2E 附件下载用例', 'utf8'),
    })

    const downloadPromise = page.waitForEvent('download')
    await attRow.getByRole('button', { name: '下载' }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe(fileName)
    await download.delete()

    await removeAttachment(page, attRow)
    await expect(page.locator('.el-message').filter({ hasText: '未登录' })).toHaveCount(0)
  })

  test('合同台账导出 Excel：点击导出即下载（不再 401）', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/contracts')

    await page.getByRole('button', { name: '导出 Excel（当前筛选）' }).click()
    const dialog = page.locator('.el-dialog:visible')
    await expect(dialog).toContainText('选择导出项')

    const downloadPromise = page.waitForEvent('download')
    await dialog.getByRole('button', { name: '导出（当前筛选）' }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(/^合同台账_\d{4}-\d{2}-\d{2}\.xlsx$/)
    await download.delete()

    await expect(page.locator('.el-dialog:visible')).toHaveCount(0)
    await expect(page.locator('.el-message').filter({ hasText: '未登录' })).toHaveCount(0)
  })

  test('导入模板下载：带令牌取回（不再 401）', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/contracts')

    await page.getByRole('button', { name: '导入', exact: true }).click()
    const dialog = page.locator('.el-dialog:visible').filter({ hasText: '批量导入合同' })
    await expect(dialog).toBeVisible()

    const downloadPromise = page.waitForEvent('download')
    await dialog.getByRole('button', { name: /下载系统导入模板/ }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(/\.xlsx$/)
    await download.delete()

    await expect(page.locator('.el-message').filter({ hasText: '未登录' })).toHaveCount(0)
  })
})
