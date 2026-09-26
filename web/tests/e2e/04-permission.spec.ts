import { expect, test } from '@playwright/test'

import { USERS, login, logout, mainArea, tokenOf } from './helpers'

/**
 * 权限体系的两道防线（`11-erp-requirements.md` AC-V2-01/03/06/41）：
 * 1) 前端：菜单按权限裁剪、路由守卫拦截、按钮按权限隐藏；
 * 2) 后端：接口层强制校验，前端绕过也拿不到数据。
 */
async function meOf(page: import('@playwright/test').Page) {
  const token = await tokenOf(page)
  const resp = await page.request.get('/api/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(resp.status()).toBe(200)
  return resp.json() as Promise<{
    user: { is_superadmin: boolean; username: string }
    perms: string[]
    menus: unknown[]
  }>
}

test.describe('权限与菜单裁剪', () => {
  test('管理员：菜单包含全部模块', async ({ page }) => {
    await login(page, 'admin')
    const aside = page.locator('.aside')
    await expect(aside).toContainText('合同管理')
    await expect(aside).toContainText('采购管理')
    await expect(aside).toContainText('销售管理')
    await expect(aside).toContainText('库存管理')

    await aside.getByText('资料库', { exact: true }).click()
    await expect(aside).toContainText('账号管理')
    await expect(aside).toContainText('组织架构')
  })

  test('只读账号：菜单被裁剪，且不含系统管理类入口', async ({ page }) => {
    await login(page, 'viewer')
    const aside = page.locator('.aside')
    await expect(aside).toContainText('合同管理')

    await aside.getByText('资料库', { exact: true }).click()
    await expect(aside).toContainText('客户信息')
    await expect(aside).not.toContainText('账号管理')
    await expect(aside).not.toContainText('角色管理')
    await expect(aside).not.toContainText('组织架构')
    await expect(aside).not.toContainText('系统管理')
  })

  test('只读账号：/api/auth/me 的权限点与菜单确实被后端裁剪', async ({ page }) => {
    await login(page, 'viewer')
    const me = await meOf(page)

    expect(me.user.is_superadmin).toBe(false)
    expect(me.perms).toContain('contract.view')
    expect(me.perms).not.toContain('master.user.view')
    expect(me.perms).not.toContain('system.dict.view')
    expect(JSON.stringify(me.menus)).not.toContain('账号管理')
    expect(JSON.stringify(me.menus)).not.toContain('系统管理')
  })

  test('只读账号：直接访问无权限路由 → 403 页并提示所需权限点', async ({ page }) => {
    await login(page, 'viewer')
    await page.goto('/master/users')

    await expect(page).toHaveURL(/\/403\?perm=master\.user\.view/)
    await expect(page.locator('.code')).toHaveText('403')
    await expect(page.locator('.det')).toContainText('master.user.view')
    // 返回首页可用
    await page.getByRole('button', { name: '返回首页' }).click()
    await expect(page).toHaveURL(/127\.0\.0\.1:5173\/$/)
  })

  test('只读账号：有查看权限的页面不出现新增/编辑按钮', async ({ page }) => {
    await login(page, 'viewer')
    await page.goto('/master/customers')

    await expect(mainArea(page)).toContainText('客户信息')
    await expect(page.locator('.el-card__header').getByRole('button', { name: '新增' })).toHaveCount(0)
    await expect(page.locator('.el-table__row').first().getByRole('button', { name: '编辑' })).toHaveCount(0)
  })

  test('后端强校验：只读账号直接调新增接口返回 403', async ({ page }) => {
    await login(page, 'viewer')
    const token = await tokenOf(page)

    const resp = await page.request.post('/api/master/customers', {
      headers: { Authorization: `Bearer ${token}` },
      data: { name: 'E2E越权客户' },
    })
    expect(resp.status()).toBe(403)
  })

  test('未带令牌访问接口 → 401', async ({ page }) => {
    await page.goto('/login')
    const resp = await page.request.get('/api/master/customers')
    expect(resp.status()).toBe(401)
  })

  test('切换账号后权限不会残留（退出→换号登录）', async ({ page }) => {
    await login(page, 'admin')
    await expect(page.locator('.aside')).toContainText('库存管理')
    await logout(page)

    await login(page, 'buyer')
    const aside = page.locator('.aside')
    await expect(aside).toContainText('采购管理')
    await expect(aside).not.toContainText('销售管理')
    await expect(page.locator('.header .user')).toContainText(USERS.buyer.realName)
  })
})
