import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

/**
 * E2E 前置：幂等创建/重置 `e2e_*` 测试账号。
 *
 * 走 Python 侧的 `app/tools/seed_e2e_users.py`，复用后端同一套 ORM 与密码哈希，
 * 避免在 Node 里重复实现 pbkdf2 细节。脚本本身幂等：只新增 `e2e_*` 账号，
 * 不触碰任何既有业务账号。
 */
export default function globalSetup(): void {
  const here = path.dirname(fileURLToPath(import.meta.url))
  const webRoot = path.resolve(here, '../..')
  const repoRoot = path.resolve(webRoot, '..')
  const python = path.join(repoRoot, 'app', '.venv', 'Scripts', 'python.exe')
  const script = path.join(repoRoot, 'app', 'tools', 'seed_e2e_users.py')

  if (!existsSync(python)) {
    throw new Error(`未找到后端虚拟环境：${python}（请先执行 setup.bat）`)
  }
  if (!existsSync(script)) {
    throw new Error(`未找到 E2E 账号脚本：${script}`)
  }

  // 输出以 UTF-8 解码，避免 Windows 控制台默认 GBK 造成中文乱码
  const out = execFileSync(python, [script], {
    cwd: repoRoot,
    encoding: 'utf8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  })
  process.stdout.write(`[e2e] 测试账号就绪\n${out}\n`)
}
