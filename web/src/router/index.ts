import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '首页看板' } },
    { path: '/contracts', name: 'contracts', component: () => import('@/views/ContractsView.vue'), meta: { title: '合同台账' } },
  ],
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · CTMS` : 'CTMS'
})

export default router
