import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login', name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: '登录', public: true },
    },
    {
      path: '/change-password', name: 'change-password',
      component: () => import('@/views/ChangePasswordView.vue'),
      meta: { title: '修改密码' },
    },
    {
      path: '/403', name: 'forbidden',
      component: () => import('@/views/ForbiddenView.vue'),
      meta: { title: '无权限', public: true },
    },
    {
      path: '/', name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { title: '首页看板', perm: 'dashboard.view' },
    },
    {
      path: '/contracts', name: 'contracts',
      component: () => import('@/views/ContractsView.vue'),
      meta: { title: '合同台账', perm: 'contract.view' },
    },
    {
      path: '/settings', name: 'settings',
      component: () => import('@/views/SettingsView.vue'),
      meta: { title: '系统设置', perm: 'system.dict.view' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

/**
 * 全局前置守卫（V2.0）：
 * 1) 未登录 → /login（带 redirect）
 * 2) 未加载用户信息 → 拉取 /auth/me（401 时回登录页）
 * 3) must_change_pwd → 强制 /change-password
 * 4) meta.perm 不在权限集内 → /403
 */
router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    if (to.path === '/login' && auth.isLoggedIn) return { path: '/' }
    return true
  }

  if (!auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  try {
    await auth.fetchMe()
  } catch {
    auth.setToken('')
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (auth.user?.must_change_pwd && to.path !== '/change-password') {
    return { path: '/change-password' }
  }

  const perm = to.meta.perm as string | undefined
  if (perm && !auth.hasPerm(perm)) {
    return { path: '/403', query: { perm } }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · CTMS` : 'CTMS'
})

export default router
