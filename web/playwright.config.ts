import { defineConfig, devices } from '@playwright/test'

/**
 * CTMS 前端 E2E 测试配置（Playwright）。
 *
 * 约定：
 * - 后端 FastAPI 固定 `127.0.0.1:8000`，前端 Vite `127.0.0.1:5173`（`/api` 代理到后端）；
 * - 两个服务由本配置的 `webServer` 自动拉起，已在本机运行时直接复用（`reuseExistingServer`）；
 * - `globalSetup` 会幂等创建 `e2e_*` 测试账号（见 `app/tools/seed_e2e_users.py`）；
 * - 数据库是单一的 SQLite 演示库，用例之间**串行**执行（`workers: 1`）避免互相干扰。
 */
export default defineConfig({
  testDir: './tests/e2e',
  globalSetup: './tests/e2e/global-setup.ts',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'tests/e2e-report' }],
    ['json', { outputFile: 'tests/e2e-report/results.json' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    viewport: { width: 1440, height: 900 },
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      // 直接调用本机已安装的 Google Chrome（channel: 'chrome'），无需 `playwright install`。
      // 如需改用 Playwright 自带浏览器：删掉 channel，并执行 `npx playwright install chromium`。
      // 注意：`devices['Desktop Chrome']` 自带 viewport 1280x720，会覆盖上面的 use.viewport，
      // 这里显式写回 1440x900，保证「配置里声明的视口」与实际运行一致。
      name: 'chrome',
      use: {
        ...devices['Desktop Chrome'],
        channel: 'chrome',
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
  webServer: [
    {
      // ⚠️ 路径相对 `cwd`（仓库根）而非 `web/`：原先写作 `..\\app\\.venv\\...`，
      // 在 cwd=根目录时会解析成 `<盘的上级>\\app\\.venv\\...`（不存在）而启动失败。
      // 该缺陷长期被 `reuseExistingServer: true` 掩盖——只要有遗留服务在跑就不会暴露。
      command: 'app\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000',
      cwd: '..',
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: true,
      timeout: 120_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
})
