<script setup lang="ts">
/** 顶栏（T-V2-15）：当前用户/组织、修改密码、退出登录。 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const roleText = computed(() => auth.roles.map((r) => r.name).join(' / ') || '无角色')

async function onCommand(command: string) {
  if (command === 'password') {
    router.push('/change-password')
    return
  }
  if (command !== 'logout') return
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '提示', {
      type: 'warning', confirmButtonText: '退出', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await auth.logout()
  router.replace('/login')
}
</script>

<template>
  <el-header class="header">
    <div class="left">
      <span class="org">{{ auth.user?.org_name || '未分配组织' }}</span>
      <el-tag size="small" type="info">{{ roleText }}</el-tag>
    </div>
    <el-dropdown @command="onCommand">
      <span class="user">
        <span class="avatar">{{ auth.displayName.slice(0, 1) }}</span>
        {{ auth.displayName }}
        <el-icon class="caret"><ArrowDown /></el-icon>
      </span>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item disabled>{{ auth.user?.username }}</el-dropdown-item>
          <el-dropdown-item command="password" divided>修改密码</el-dropdown-item>
          <el-dropdown-item command="logout">退出登录</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </el-header>
</template>

<style scoped>
.header {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.left { display: flex; align-items: center; gap: 10px; }
.org { color: #606266; font-size: 13px; }
.user {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  outline: none;
  color: #303133;
  font-size: 13.5px;
}
.avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #ecf5ff;
  border: 1px solid #d9ecff;
  color: #409eff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}
.caret { color: #909399; font-size: 12px; }
</style>
