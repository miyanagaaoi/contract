<script setup lang="ts">
/**
 * 修改密码（AC-V2-08）：首登强制改密时由路由守卫送到本页。
 * 改密成功后清除 must_change_pwd 标记并回首页。
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)

async function onSubmit() {
  if (!oldPassword.value || !newPassword.value) {
    ElMessage.warning('请填写原密码与新密码')
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  loading.value = true
  try {
    await auth.changePassword(oldPassword.value, newPassword.value)
    await auth.fetchMe(true)
    ElMessage.success('密码修改成功')
    router.replace('/')
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    if (detail) ElMessage.error(detail)
  } finally {
    loading.value = false
  }
}

async function onLogout() {
  await auth.logout()
  router.replace('/login')
}
</script>

<template>
  <div class="pwd-page">
    <div class="pwd-box">
      <h1>修改密码</h1>
      <p class="sub">
        密码需至少 8 位并同时包含字母与数字。
        <span v-if="auth.user?.must_change_pwd" class="warn">首次登录必须先修改初始密码。</span>
      </p>

      <el-form label-position="top" @submit.prevent="onSubmit">
        <el-form-item label="原密码">
          <el-input v-model="oldPassword" type="password" size="large" show-password
                    placeholder="请输入原密码" @keyup.enter="onSubmit" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="newPassword" type="password" size="large" show-password
                    placeholder="至少 8 位，含字母与数字" @keyup.enter="onSubmit" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="confirmPassword" type="password" size="large" show-password
                    placeholder="再次输入新密码" @keyup.enter="onSubmit" />
        </el-form-item>
        <div class="actions">
          <el-button type="primary" size="large" :loading="loading" @click="onSubmit">保存</el-button>
          <el-button size="large" @click="onLogout">退出登录</el-button>
        </div>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.pwd-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f2d3d 0%, #33475b 100%);
}
.pwd-box {
  width: 420px;
  background: #fff;
  border-radius: 8px;
  padding: 30px 34px;
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.25);
}
h1 { margin: 0 0 6px; font-size: 18px; }
.sub { color: #909399; font-size: 12.5px; margin: 0 0 18px; line-height: 1.7; }
.warn { color: #e6a23c; }
.actions { display: flex; gap: 10px; }
</style>
