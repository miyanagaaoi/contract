/**
 * 登录令牌的唯一读写入口（T0-5）。
 *
 * 背景（审查发现的两个真实缺陷）：
 * 1. **双真源**：`stores/auth.ts:41` 在 state 初始化时读一次 localStorage，
 *    而 `api.ts:22-29` 每次请求又自己去读一遍；`api.ts:38` 在 401 时只
 *    `localStorage.removeItem` 而**不回写 store** —— 于是会出现
 *    `store.token` 有值、localStorage 无值的分裂态，`isLoggedIn` 仍为 true。
 * 2. **循环依赖陷阱**：`stores/auth.ts` 已经依赖 `api.ts`。若在 `api.ts` 的
 *    拦截器里反向 `import { useAuthStore }` 就会构成循环依赖。
 *
 * 因此令牌访问必须下沉到本模块：`api.ts` 与 `stores/auth.ts` 都只依赖它，
 * 由订阅机制保证 store 与 localStorage 永远同步。
 */

export const TOKEN_KEY = 'ctms_token'

type TokenListener = (token: string) => void

const listeners = new Set<TokenListener>()

function notify(token: string): void {
  for (const fn of listeners) {
    try {
      fn(token)
    } catch {
      // 单个订阅者异常不应影响令牌写入本身
    }
  }
}

/** 读取当前令牌（始终以 localStorage 为准；空串代表未登录） */
export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    // 隐私模式 / 存储被禁用时降级为未登录态
    return ''
  }
}

/** 写入令牌；传空串等价于清除。写入后通知所有订阅者 */
export function setToken(token: string): void {
  const next = token || ''
  try {
    if (next) localStorage.setItem(TOKEN_KEY, next)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // 存储不可用时仍然通知订阅者，保证内存态一致
  }
  notify(next)
}

/** 清除令牌（401、退出登录、账号被停用） */
export function clearToken(): void {
  setToken('')
}

/**
 * 订阅令牌变化，返回取消订阅函数。
 *
 * 用途：Pinia store 用它在 401 拦截器清除令牌后同步自己的 state，
 * 消除「store 有值 / 本地无值」的分裂态。
 */
export function onTokenChange(fn: TokenListener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}
