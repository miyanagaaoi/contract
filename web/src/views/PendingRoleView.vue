<script setup lang="ts">
/**
 * 等待分配角色页（`/pending`）。
 *
 * ## 为什么需要这个页面
 *
 * 飞书扫码登录遇到未绑定的飞书账号时会**自动建号**（业务要求），新账号**没有任何角色**。
 * 本系统所有业务路由都带 `meta.perm`，没有角色 = 没有权限点 ⇒ 无论点哪里都会被踢到 403。
 * 用户只会看到一片「无权限」，既不知道发生了什么，也不知道该找谁。
 *
 * 因此：路由守卫把「已登录但无任何启用角色」的人统一送到这里 —— 页面说明"账号已创建、
 * 等管理员分配角色"，并每 10 秒静默复查一次，管理员一分配就自动进入系统，不用重新登录。
 *
 * 判定真源在后端 `/api/auth/me` 的 `pending_roles`（`permission_service.pending_role`），
 * 与登录接口的 `pending_roles` 同口径，前端不自行推断角色状态。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const checking = ref(false)

/** 轮询间隔：管理员刚分配完，用户无需手动刷新（读接口，压力可忽略） */
const POLL_MS = 10000
let timer: number | undefined

async function check(silent = true): Promise<void> {
  if (checking.value) return
  checking.value = true
  try {
    await auth.fetchMe(true)
    if (!auth.pendingRoles) {
      ElMessage.success('角色已分配，正在进入系统…')
      router.replace('/')
      return
    }
    if (!silent) ElMessage.info('仍未分配角色，请联系系统管理员')
  } catch {
    // 内网抖动 / 后端 5xx：留在本页，下一轮轮询自动重试（不能把用户踢回登录页）
  } finally {
    checking.value = false
  }
}

onMounted(() => {
  timer = window.setInterval(() => { void check() }, POLL_MS)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})

async function onLogout(): Promise<void> {
  await auth.logout()
  router.replace('/login')
}
</script>

<template>
  <div class="pending">
    <div class="box">
      <h1>账号已创建，等待分配角色</h1>
      <p class="user">
        {{ auth.displayName || '—' }}
        <span v-if="auth.user?.username" class="uname">（{{ auth.user.username }}）</span>
      </p>
      <p class="msg">
        你的账号已通过飞书扫码登录自动创建，但还<strong>没有分配任何角色</strong>，因此暂时看不到任何菜单。
        请联系系统管理员在「账号管理」中为你分配角色；分配完成后本页会自动进入系统，无需重新登录。
      </p>
      <div class="actions">
        <el-button type="primary" :loading="checking" @click="check(false)">我已联系管理员，立即检查</el-button>
        <el-button @click="onLogout">退出登录</el-button>
      </div>
      <p class="foot">每 10 秒自动检查一次，无需手动刷新页面。</p>
    </div>
  </div>
</template>

<style scoped>
.pending {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--ctms-bg);
}
.box {
  width: min(520px, 92vw);
  background: #fff;
  border-radius: 8px;
  padding: 28px 30px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
}
.box h1 { margin: 0 0 10px; font-size: var(--ctms-fs-lg); }
.user { margin: 0 0 14px; font-weight: 600; }
.uname { color: var(--ctms-text-muted); font-weight: 400; font-size: var(--ctms-fs-sm); }
.msg { color: var(--ctms-text); font-size: var(--ctms-fs-sm); line-height: 1.7; margin: 0 0 20px; }
.actions { display: flex; gap: 10px; }
.foot { margin: 16px 0 0; color: var(--ctms-text-muted); font-size: var(--ctms-fs-xs); }
</style>
