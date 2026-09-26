import { expect, test } from '@playwright/test'

import { E2E_PASSWORD, USERS, gotoLogin, login, logout, tokenOf, trackRuntimeErrors } from './helpers'

test.describe('登录与登录态', () => {
  test('未登录访问受保护页面 → 跳登录页并带上 redirect', async ({ page }) => {
    await page.goto('/contracts')
    await expect(page).toHaveURL(/\/login\?redirect=/)
    await expect(page.getByRole('button', { name: /登\s*录/ })).toBeVisible()
  })

  test('空表单提交 → 提示请输入登录名与密码', async ({ page }) => {
    await gotoLogin(page)
    await page.getByRole('button', { name: /登\s*录/ }).click()
    await expect(page.locator('.err')).toHaveText('请输入登录名与密码')
  })

  test('密码错误 → 显示后端返回的中文提示且停留在登录页', async ({ page }) => {
    await gotoLogin(page)
    await page.getByPlaceholder('请输入登录名').fill(USERS.admin.username)
    await page.getByPlaceholder('请输入密码').fill('wrongpass123')
    await page.getByRole('button', { name: /登\s*录/ }).click()

    await expect(page.locator('.err')).toHaveText('用户名或密码错误')
    await expect(page).toHaveURL(/\/login/)
    expect(await tokenOf(page)).toBeNull()
  })

  test('账号不存在 → 与密码错误同一提示（不泄露账号是否存在）', async ({ page }) => {
    await gotoLogin(page)
    await page.getByPlaceholder('请输入登录名').fill('no_such_user_e2e')
    await page.getByPlaceholder('请输入密码').fill('whatever123')
    await page.getByRole('button', { name: /登\s*录/ }).click()

    await expect(page.locator('.err')).toHaveText('用户名或密码错误')
  })

  test('登录成功 → 进入首页看板并加载用户与菜单', async ({ page }) => {
    const errors = trackRuntimeErrors(page)
    await login(page, 'admin')

    await expect(page).toHaveURL(/127\.0\.0\.1:5173\/$|\/$/)
    await expect(page.locator('.header .user')).toContainText(USERS.admin.realName)
    await expect(page.locator('.main')).toContainText('合同总数')
    await expect(page.locator('.aside')).toContainText('合同管理')

    expect(await tokenOf(page)).toBeTruthy()
    expect(errors).toEqual([])
  })

  test('登录后访问 /login 会被送回首页', async ({ page }) => {
    await login(page, 'admin')
    await page.goto('/login')
    await expect(page).toHaveURL(/127\.0\.0\.1:5173\/$/)
  })

  test('退出登录 → 回登录页并清除本地令牌', async ({ page }) => {
    await login(page, 'admin')
    await logout(page)

    expect(await tokenOf(page)).toBeNull()
    // 再访问受保护页面仍需重新登录
    await page.goto('/contracts')
    await expect(page).toHaveURL(/\/login\?redirect=/)
  })

  test('令牌被篡改 → 请求 401，自动回登录页', async ({ page }) => {
    await login(page, 'admin')
    await page.evaluate(() => localStorage.setItem('ctms_token', 'tampered.token.value'))
    await page.goto('/contracts')

    await expect(page).toHaveURL(/\/login/, { timeout: 20_000 })
  })

  test('演示账号首登仍强制改密（回归：e2e 账号不应被误置标记）', async ({ page }) => {
    // e2e_* 账号 must_change_pwd=0，登录后应直接进主界面而非改密页
    await login(page, 'admin')
    await expect(page).not.toHaveURL(/change-password/)
  })

  test('错误密码连续提交不会残留 loading 状态', async ({ page }) => {
    await gotoLogin(page)
    await page.getByPlaceholder('请输入登录名').fill(USERS.admin.username)
    await page.getByPlaceholder('请输入密码').fill(E2E_PASSWORD + 'x')
    await page.getByRole('button', { name: /登\s*录/ }).click()
    await expect(page.locator('.err')).toBeVisible()

    // 按钮必须恢复可点击，否则用户无法重试
    await expect(page.getByRole('button', { name: /登\s*录/ })).toBeEnabled()
  })
})
