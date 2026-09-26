<script setup lang="ts">
/**
 * 应用主布局（T-V2-15）：侧边菜单（按权限裁剪，来自 `/api/auth/me`）+ 顶栏 + 主区。
 *
 * 独立页（登录 / 改密 / 403）不在本布局内，由路由分别渲染。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import MenuTree from '@/components/MenuTree.vue'
import TopBar from '@/components/TopBar.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const activeMenu = computed(() => route.path)
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="brand">CTMS ERP</div>
      <el-scrollbar class="menu-scroll">
        <el-menu :default-active="activeMenu" router unique-opened background-color="#1f2d3d"
                 text-color="#c0c4cc" active-text-color="#409eff">
          <MenuTree :nodes="auth.menus" />
        </el-menu>
      </el-scrollbar>
    </el-aside>

    <!--
      必须显式声明 direction="vertical"：
      el-container 只有在**直接子节点**的组件名是 ElHeader / ElFooter 时才自动纵向排列，
      而这里的顶栏封装在自定义组件 <TopBar /> 内部（它才是 <el-header>），
      自动判定会退化成 row —— 结果是顶栏只占内容宽度、缩在左上角，主区被挤到顶栏右侧。
    -->
    <el-container direction="vertical">
      <TopBar />
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout { height: 100%; }
.aside { background: #1f2d3d; display: flex; flex-direction: column; }
.brand {
  color: #fff;
  font-weight: 600;
  padding: 18px 16px;
  font-size: 15px;
  line-height: 1.4;
}
.menu-scroll { flex: 1; }
.aside :deep(.el-menu) { border-right: none; }
.main { padding: 16px; background: #f5f7fa; }
</style>
