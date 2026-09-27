/**
 * 未保存离开确认的注册表（T1-1）。
 *
 * 为什么需要这个模块：Vue Router 的 `onBeforeRouteLeave` **只能写在路由组件里**，
 * 而本项目承载录单逻辑的 `DocFormPage` / `DocItemsTable` 是被各表单页复用的
 * **子组件**——在子组件里调用它不会报错，但守卫不会生效（开发模式仅一条警告）。
 *
 * 因此改为「全局守卫 + 组件注册」：
 * - 表单壳挂载时 `registerUnsavedGuard(...)`，卸载时 `unregisterUnsavedGuard()`；
 * - `router/index.ts` 的全局 `beforeEach` 调用 `confirmLeave()`，
 *   返回 false 即取消本次导航。
 *
 * 同一时刻只允许一个表单壳注册（页面内不会同时存在两个录入表单）。
 */

type UnsavedGuard = () => Promise<boolean> | boolean

let activeGuard: UnsavedGuard | null = null

/** 表单壳挂载时注册；重复注册以最后一次为准 */
export function registerUnsavedGuard(guard: UnsavedGuard): void {
  activeGuard = guard
}

export function unregisterUnsavedGuard(): void {
  activeGuard = null
}

/**
 * 询问是否允许离开当前页面。
 *
 * 无注册者（绝大多数列表页/看板）直接放行，因此对全局导航零影响。
 */
export async function confirmLeave(): Promise<boolean> {
  if (!activeGuard) return true
  try {
    return await activeGuard()
  } catch {
    // 守卫自身异常不应阻断导航（例如确认框被卸载）
    return true
  }
}
