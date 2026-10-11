<script setup lang="ts">
/** 登录页（AC-V2-01/02/08）：失败提示以表单下方红字呈现，不做弹窗。 */
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { fetchFeishuAuthorizeUrl, fetchFeishuConfig } from '@/api'
import { useAuthStore } from '@/stores/auth'

/**
 * 回跳页地址的暂存键：飞书要求 `redirect_uri` 与后台登记地址**完全一致**，
 * 不能在 URL 上追加 `?redirect=`；丢了只会回首页，不影响正确性。
 * （"登录还是绑定"的场景签在 `state` 里，不依赖 sessionStorage。）
 */
const FEISHU_REDIRECT_KEY = 'ctms_feishu_redirect'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

const feishuEnabled = ref(false)
const feishuLoading = ref(false)

/** 飞书入口默认隐藏：只有后端明确返回 enabled 才显示（未启用时登录页零感知，AC-FS-09）。 */
onMounted(async () => {
  try {
    feishuEnabled.value = !!(await fetchFeishuConfig()).enabled
  } catch {
    feishuEnabled.value = false     // 接口异常也不能影响密码登录
  }
})

/** 发起飞书免登：整页跳转到飞书授权页 */
async function onFeishuLogin() {
  feishuLoading.value = true
  error.value = ''
  try {
    const { url } = await fetchFeishuAuthorizeUrl('login')
    sessionStorage.setItem(FEISHU_REDIRECT_KEY, (route.query.redirect as string) || '/')
    window.location.href = url
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = detail || '无法发起飞书登录，请联系管理员'
    feishuLoading.value = false
  }
}

async function onSubmit() {
  if (!username.value.trim() || !password.value) {
    error.value = '请输入登录名与密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await auth.login(username.value.trim(), password.value)
    if (data.must_change_pwd) {
      ElMessage.warning('首次登录请先修改密码')
      router.replace('/change-password')
      return
    }
    await auth.fetchMe(true)
    // 无任何角色（如飞书自动建号、管理员尚未分配）→ 送到「等待分配角色」页，
    // 否则会被路由守卫按 meta.perm 挡到 403，用户看不出发生了什么。
    if (auth.pendingRoles) {
      router.replace('/pending')
      return
    }
    const redirect = (route.query.redirect as string) || '/'
    router.replace(redirect)
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = detail || '登录失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-box">
      <div class="brand">
        <span class="logo"></span>
        <h1>CTMS ERP</h1>
      </div>
      <p class="sub">合同管理 · 进销存一体化（内网）</p>

      <el-form label-position="top" @submit.prevent="onSubmit">
        <el-form-item label="用户名">
          <el-input v-model="username" name="username" autocomplete="username" spellcheck="false"
                    size="large" placeholder="请输入登录名" clearable @keyup.enter="onSubmit" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" name="password" autocomplete="current-password"
                    size="large" placeholder="请输入密码" show-password @keyup.enter="onSubmit" />
        </el-form-item>
        <!-- role=alert + aria-live：内联错误必须被屏幕阅读器播报（T3-4） -->
        <p v-if="error" class="err" role="alert" aria-live="polite">{{ error }}</p>
        <el-button type="primary" size="large" class="full" :loading="loading" @click="onSubmit">
          登 录
        </el-button>
      </el-form>

      <!-- V2.4 飞书免登：后端未启用时整块不渲染，密码登录完全不受影响 -->
      <template v-if="feishuEnabled">
        <div class="divider"><span>或</span></div>
        <el-button size="large" class="full" :loading="feishuLoading" @click="onFeishuLogin">
          飞书登录
        </el-button>
      </template>

      <p class="foot">内网系统 · 忘记密码请联系系统管理员重置</p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f2d3d 0%, #33475b 100%);
}
.login-box {
  width: 400px;
  background: #fff;
  border-radius: 8px;
  padding: 32px 34px;
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.25);
}
.brand { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.brand h1 { margin: 0; font-size: var(--ctms-fs-lg); letter-spacing: 0.5px; }
.logo { width: 26px; height: 26px; border-radius: 6px; background: var(--ctms-primary); display: inline-block; }
.sub { color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); margin: 0 0 20px; }
.err { color: var(--ctms-danger-text); font-size: var(--ctms-fs-sm); margin: 0 0 10px; }
.full { width: 100%; margin-top: 4px; }
.divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 14px 0 2px;
  color: var(--ctms-text-muted);
  font-size: var(--ctms-fs-xs);
}
.divider::before,
.divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--ctms-border, #e5e7eb);
}
.foot { margin-top: 16px; font-size: var(--ctms-fs-xs); color: var(--ctms-text-muted); text-align: center; }
</style>
