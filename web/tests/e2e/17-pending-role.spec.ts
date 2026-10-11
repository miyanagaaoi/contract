import { expect, test, type APIRequestContext } from '@playwright/test'

import { E2E_PASSWORD, USERS, uniqueName } from './helpers'

/**
 * V2.5：飞书扫码自动建号后的「待分配角色」动线。
 *
 * 背景：未绑定的飞书账号扫码登录时会自动建号，但**不给任何角色**。
 * 若不放行一个专用页面，这类用户点任何菜单都只会撞上 403（一片"无权限"）。
 * 本用例固定三件事：
 *
 * 1) 零角色 → 登录后被守卫送到 `/pending`（不是 403，也不是空白主界面）；
 * 2) 管理员分配角色后，页面**无需重新登录**自动进入系统（10 秒轮询）；
 * 3) 该页面是独立全屏页（没有侧栏），避免"空菜单"造成的误解。
 *
 * 说明：这里用「管理员新建的无角色账号 + 密码登录」复现同一状态 —— 自动建号的账号
 * 同样是"零角色"，而真实飞书授权页属外部依赖（登录需人工扫码），不适合放进 E2E。
 * 后端自动建号本身由 `app/tests/test_v2_4_feishu.py` 的接口/服务层用例覆盖。
 */
async function adminToken(request: APIRequestContext): Promise<string> {
  const resp = await request.post('/api/auth/login', {
    data: { username: USERS.admin.username, password: E2E_PASSWORD },
  })
  expect(resp.status(), await resp.text()).toBe(200)
  return (await resp.json()).token
}

test.describe('待分配角色（飞书自动建号后的落点）', () => {
  test('零角色账号落到 /pending，管理员分配角色后自动进入系统', async ({ page }) => {
    const token = await adminToken(page.request)
    const headers = { Authorization: `Bearer ${token}` }
    const username = uniqueName('e2e_pending').toLowerCase()

    // ---- 1. 管理员建一个**不带角色**的账号（等价于飞书自动建号的状态）----
    const created = await page.request.post('/api/system/users', {
      headers,
      data: { username, real_name: 'E2E待分配', password: E2E_PASSWORD, role_ids: [] },
    })
    expect(created.status(), await created.text()).toBe(200)
    const createdBody = await created.json()
    const uid = createdBody.id as number
    expect(createdBody.awaiting_role).toBe(true)

    // 待分配清单（账号管理页「角色分配：待分配角色」筛选）能查到它
    const listed = await page.request.get('/api/system/users', {
      headers, params: { awaiting_role: 'true', keyword: username },
    })
    expect(listed.status()).toBe(200)
    const listedItem = (await listed.json()).items.find((u: { id: number }) => u.id === uid)
    expect(listedItem?.awaiting_role).toBe(true)

    // ---- 2. 该账号登录：先强制改密（管理员新建账号的口径），随后落到 /pending ----
    await page.goto('/login')
    await page.getByPlaceholder('请输入登录名').fill(username)
    await page.getByPlaceholder('请输入密码').fill(E2E_PASSWORD)
    await page.getByRole('button', { name: /^登\s*录$/ }).click()

    await expect(page).toHaveURL(/\/change-password/, { timeout: 20_000 })
    const newPassword = 'pending12345'
    await page.getByPlaceholder('请输入原密码').fill(E2E_PASSWORD)
    await page.getByPlaceholder('至少 8 位，含字母与数字').fill(newPassword)
    await page.getByPlaceholder('再次输入新密码').fill(newPassword)
    await page.getByRole('button', { name: '保存' }).click()

    await expect(page).toHaveURL(/\/pending/, { timeout: 20_000 })
    await expect(page.locator('.box h1')).toContainText('等待分配角色')
    // 独立全屏页：没有侧栏（否则用户会看到一片空菜单，以为系统坏了）
    await expect(page.locator('.aside')).toHaveCount(0)

    // 后端口径：确实是"待分配角色"，且权限点为空
    const me = await page.request.get('/api/auth/me', {
      headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('ctms_token'))}` },
    })
    expect(me.status()).toBe(200)
    const meBody = await me.json()
    expect(meBody.pending_roles).toBe(true)
    expect(meBody.perms).toEqual([])

    // ---- 3. 管理员分配角色 → 页面轮询后自动进入系统（不重新登录）----
    const roles = await page.request.get('/api/system/roles', { headers })
    const roleId = (await roles.json()).items
      .find((r: { code: string }) => r.code === 'viewer')?.id
    expect(roleId).toBeTruthy()

    const assigned = await page.request.put(`/api/system/users/${uid}`, {
      headers, data: { role_ids: [roleId] },
    })
    expect(assigned.status(), await assigned.text()).toBe(200)
    expect((await assigned.json()).awaiting_role).toBe(false)

    // 端口无关的断言：只要回到站点根（首页看板），不绑定具体 dev 端口
    await expect(page).toHaveURL((url) => url.pathname === '/', { timeout: 30_000 })
    await expect(page.locator('.header .user')).toContainText('E2E待分配')
    await expect(page.locator('.aside')).toContainText('合同管理')

    // ---- 收尾：停用（账号不做物理删除，保留审计）----
    const disabled = await page.request.put(`/api/system/users/${uid}/status`, {
      headers, data: { enabled: false },
    })
    expect(disabled.status()).toBe(200)
  })
})
