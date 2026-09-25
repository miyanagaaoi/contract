<script setup lang="ts">
/** 登录页（AC-V2-01/02/08）：失败提示以表单下方红字呈现，不做弹窗。 */
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

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
          <el-input v-model="username" size="large" placeholder="请输入登录名" clearable
                    @keyup.enter="onSubmit" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" size="large" placeholder="请输入密码"
                    show-password @keyup.enter="onSubmit" />
        </el-form-item>
        <p v-if="error" class="err">{{ error }}</p>
        <el-button type="primary" size="large" class="full" :loading="loading" @click="onSubmit">
          登 录
        </el-button>
      </el-form>

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
.brand h1 { margin: 0; font-size: 18px; letter-spacing: 0.5px; }
.logo { width: 26px; height: 26px; border-radius: 6px; background: #409eff; display: inline-block; }
.sub { color: #909399; font-size: 12.5px; margin: 0 0 20px; }
.err { color: #f56c6c; font-size: 12.5px; margin: 0 0 10px; }
.full { width: 100%; margin-top: 4px; }
.foot { margin-top: 16px; font-size: 11.5px; color: #909399; text-align: center; }
</style>
