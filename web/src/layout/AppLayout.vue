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
import { useAuthStore, type MenuNode } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()

/**
 * 侧栏高亮（T2-4）。
 *
 * 原先直接拿 `route.path` 与菜单 index 精确比对，而菜单 index 是**列表路径**
 * （如 `/purchase/orders`），详情/编辑页却是 `/purchase/orders/:id`、
 * `/purchase/orders/new`、`/purchase/orders/:id/edit` —— 结果是**进入任何详情页或
 * 编辑页，侧栏高亮全部消失**，长会话中持续失去「我在哪」的定位感。
 *
 * 改为：收集全部菜单路径 → 精确命中优先 → 否则取最长的路径前缀匹配。
 */
const activeMenu = computed(() => {
  const path = route.path
  const paths: string[] = []
  const collect = (nodes: MenuNode[]): void => {
    for (const node of nodes) {
      if (node.path) paths.push(node.path)
      if (node.children?.length) collect(node.children)
    }
  }
  collect(auth.menus)

  if (paths.includes(path)) return path
  const hit = paths
    .filter((p) => p !== '/' && path.startsWith(`${p}/`))
    .sort((a, b) => b.length - a.length)[0]
  return hit || path
})
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="brand">CTMS ERP</div>
      <el-scrollbar class="menu-scroll">
        <!--
          T4-8：background-color / text-color / active-text-color 三个 props 在
          Element Plus 2.9 已 @deprecated，且 #1f2d3d 在此与 .aside 样式重复。
          改用下方 style 中的 --el-menu-* CSS 变量。
        -->
        <el-menu :default-active="activeMenu" router unique-opened>
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
.aside { background: var(--ctms-sidebar-bg); display: flex; flex-direction: column; }
.brand {
  color: #fff;
  font-weight: 600;
  padding: 18px 16px;
  font-size: var(--ctms-fs-md);
  line-height: 1.4;
}
.menu-scroll { flex: 1; }
.aside :deep(.el-menu) {
  border-right: none;
  /* T4-8：替代已弃用的 background-color / text-color / active-text-color props */
  --el-menu-bg-color: var(--ctms-sidebar-bg);
  --el-menu-text-color: #c0c4cc;
  --el-menu-active-color: var(--ctms-primary);
}
.main { padding: 16px; background: var(--ctms-bg); }
</style>
