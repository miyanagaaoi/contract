<script setup lang="ts">
/**
 * 应用外壳（V2.0 最小登录改造版）：
 * - /login、/change-password、/403 为独立页（不渲染侧栏与顶栏）
 * - 其余页面：侧栏菜单**按权限过滤**，顶栏显示当前用户与登出
 *
 * 说明：完整的多级菜单树（采购/销售/库存/资料库）在 T-V2-15 落地；
 * 本版先接入登录态与权限，保证 V1.0 三个页面在新认证体系下可用。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const BARE_PATHS = ['/login', '/change-password', '/403']
const bare = computed(() => BARE_PATHS.includes(route.path))
const activeMenu = computed(() => route.path)

// 现有页面与权限点映射（与后端 permissions.py 的菜单树一致）
const NAV = [
  { path: '/', title: '首页看板', icon: 'Odometer', perm: 'dashboard.view' },
  { path: '/contracts', title: '合同台账', icon: 'Files', perm: 'contract.view' },
  { path: '/settings', title: '系统设置', icon: 'Setting', perm: 'system.dict.view' },
]
const navItems = computed(() => NAV.filter((item) => auth.hasPerm(item.perm)))

async function onCommand(command: string) {
  if (command === 'password') {
    router.push('/change-password')
    return
  }
  if (command === 'logout') {
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
}
</script>

<template>
  <!-- 登录 / 改密 / 403：独立全屏页 -->
  <router-view v-if="bare" />

  <el-container v-else class="layout">
    <el-aside width="220px" class="aside">
      <div class="brand">CTMS ERP</div>
      <el-menu :default-active="activeMenu" router background-color="#1f2d3d" text-color="#c0c4cc"
               active-text-color="#409eff">
        <el-menu-item v-for="item in navItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <span class="org">{{ auth.user?.org_name || '未分配组织' }}</span>
        <el-dropdown @command="onCommand">
          <span class="user">
            <span class="avatar">{{ auth.displayName.slice(0, 1) }}</span>
            {{ auth.displayName }}
            <el-icon class="caret"><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                {{ auth.roles.map((r) => r.name).join(' / ') || '无角色' }}
              </el-dropdown-item>
              <el-dropdown-item command="password" divided>修改密码</el-dropdown-item>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout { height: 100%; }
.aside { background: #1f2d3d; }
.brand {
  color: #fff;
  font-weight: 600;
  padding: 18px 16px;
  font-size: 15px;
  line-height: 1.4;
}
.header {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
}
.org { color: #909399; font-size: 13px; }
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
.main { padding: 16px; }
</style>
