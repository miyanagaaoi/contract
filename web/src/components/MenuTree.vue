<script setup lang="ts">
/**
 * 菜单树渲染（T-V2-15）：递归渲染后端 `GET /api/auth/me` 返回的 menus（已按权限裁剪）。
 * 前端不维护第二套菜单定义，避免与 `app/permissions.py` 漂移。
 */
import type { MenuNode } from '@/stores/auth'

defineProps<{ nodes: MenuNode[] }>()
</script>

<template>
  <template v-for="node in nodes" :key="node.key">
    <el-sub-menu v-if="node.children && node.children.length" :index="node.key">
      <template #title>
        <el-icon v-if="node.icon"><component :is="node.icon" /></el-icon>
        <span>{{ node.title }}</span>
      </template>
      <MenuTree :nodes="node.children" />
    </el-sub-menu>
    <el-menu-item v-else :index="node.path || node.key">
      <el-icon v-if="node.icon"><component :is="node.icon" /></el-icon>
      <template #title>{{ node.title }}</template>
    </el-menu-item>
  </template>
</template>
