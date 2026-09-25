import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

/**
 * 路由表（T-V2-15）。
 *
 * - 主区页面统一挂在 `AppLayout` 下（侧栏 + 顶栏 + 主区）；
 * - 登录 / 改密 / 403 为独立全屏页；
 * - `meta.perm` 与后端 `app/permissions.py` 的权限点一致，供路由守卫与菜单裁剪使用；
 * - 旧路径 `/settings` 重定向到 `/system`（AC-V2-38：原设置功能全部保留，入口收敛到系统管理）。
 */
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
      path: '/', component: () => import('@/layout/AppLayout.vue'),
      children: [
        {
          path: '', name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: '首页看板', perm: 'dashboard.view' },
        },
        {
          path: 'contracts', name: 'contracts',
          component: () => import('@/views/ContractsView.vue'),
          meta: { title: '合同台账', perm: 'contract.view' },
        },

        // ---- 资料库：往来单位 ----
        {
          path: 'master/customers', name: 'master-customers',
          component: () => import('@/views/master/CustomerView.vue'),
          meta: { title: '客户信息', perm: 'master.customer.view' },
        },
        {
          path: 'master/suppliers', name: 'master-suppliers',
          component: () => import('@/views/master/SupplierView.vue'),
          meta: { title: '供应商信息', perm: 'master.supplier.view' },
        },
        {
          path: 'master/party-drafts', name: 'master-party-drafts',
          component: () => import('@/views/master/PartyDraftView.vue'),
          meta: { title: '历史档案认领', perm: 'contract.edit' },
        },

        // ---- 资料库：基础信息 ----
        {
          path: 'master/product-types', name: 'master-product-types',
          component: () => import('@/views/master/ProductTypeView.vue'),
          meta: { title: '商品类型', perm: 'master.ptype.view' },
        },
        {
          path: 'master/products', name: 'master-products',
          component: () => import('@/views/master/ProductView.vue'),
          meta: { title: '物料档案', perm: 'master.product.view' },
        },
        {
          path: 'master/uoms', name: 'master-uoms',
          component: () => import('@/views/master/UomView.vue'),
          meta: { title: '计量单位', perm: 'master.uom.view' },
        },
        {
          path: 'master/warehouses', name: 'master-warehouses',
          component: () => import('@/views/master/WarehouseView.vue'),
          meta: { title: '仓库', perm: 'master.wh.view' },
        },

        // ---- 资料库：权限主数据 ----
        {
          path: 'master/orgs', name: 'master-orgs',
          component: () => import('@/views/master/OrgView.vue'),
          meta: { title: '组织架构', perm: 'master.org.view' },
        },
        {
          path: 'master/roles', name: 'master-roles',
          component: () => import('@/views/master/RoleView.vue'),
          meta: { title: '角色管理', perm: 'master.role.view' },
        },
        {
          path: 'master/users', name: 'master-users',
          component: () => import('@/views/master/UserView.vue'),
          meta: { title: '账号管理', perm: 'master.user.view' },
        },

        // ---- 系统管理 ----
        {
          path: 'system', name: 'system',
          component: () => import('@/views/system/SystemView.vue'),
          meta: { title: '系统管理', perm: 'system.dict.view' },
        },
        { path: 'settings', redirect: '/system' },

        // ---- 采购管理（T-V2-24） ----
        {
          path: 'purchase/requests', name: 'purchase-requests',
          component: () => import('@/views/purchase/RequestList.vue'),
          meta: { title: '采购申请单', perm: 'purchase.request.view' },
        },
        {
          path: 'purchase/requests/new', name: 'purchase-request-form',
          component: () => import('@/views/purchase/RequestForm.vue'),
          meta: { title: '新增采购申请单', perm: 'purchase.request.create' },
        },
        {
          path: 'purchase/requests/:id/edit', name: 'purchase-request-edit',
          component: () => import('@/views/purchase/RequestForm.vue'),
          meta: { title: '编辑采购申请单', perm: 'purchase.request.edit' },
        },
        {
          path: 'purchase/requests/:id', name: 'purchase-request-detail',
          component: () => import('@/views/purchase/RequestForm.vue'),
          meta: { title: '采购申请单详情', perm: 'purchase.request.view' },
        },

        {
          path: 'purchase/orders', name: 'purchase-orders',
          component: () => import('@/views/purchase/OrderList.vue'),
          meta: { title: '采购单', perm: 'purchase.order.view' },
        },
        {
          path: 'purchase/orders/new', name: 'purchase-order-form',
          component: () => import('@/views/purchase/OrderForm.vue'),
          meta: { title: '新增采购单', perm: 'purchase.order.create' },
        },
        {
          path: 'purchase/orders/:id/edit', name: 'purchase-order-edit',
          component: () => import('@/views/purchase/OrderForm.vue'),
          meta: { title: '编辑采购单', perm: 'purchase.order.edit' },
        },
        {
          path: 'purchase/orders/:id', name: 'purchase-order-detail',
          component: () => import('@/views/purchase/OrderForm.vue'),
          meta: { title: '采购单详情', perm: 'purchase.order.view' },
        },

        // ---- 库存管理：入库单与库存明细（T-V2-25） ----
        {
          path: 'stock/in-orders', name: 'stock-in-orders',
          component: () => import('@/views/stock/InList.vue'),
          meta: { title: '入库单', perm: 'stock.in.view' },
        },
        {
          path: 'stock/in-orders/new', name: 'stock-in-form',
          component: () => import('@/views/stock/InForm.vue'),
          meta: { title: '新增入库单', perm: 'stock.in.create' },
        },
        {
          path: 'stock/in-orders/:id/edit', name: 'stock-in-edit',
          component: () => import('@/views/stock/InForm.vue'),
          meta: { title: '编辑入库单', perm: 'stock.in.edit' },
        },
        {
          path: 'stock/in-orders/:id', name: 'stock-in-detail',
          component: () => import('@/views/stock/InForm.vue'),
          meta: { title: '入库单详情', perm: 'stock.in.view' },
        },
        {
          path: 'stock/balances', name: 'stock-balances',
          component: () => import('@/views/stock/BalanceView.vue'),
          meta: { title: '库存明细', perm: 'stock.balance.view' },
        },
      ],
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
