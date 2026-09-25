<script setup lang="ts">
/**
 * 应用根组件（T-V2-15）：只承载路由出口与全局样式；
 * 侧栏/顶栏等布局职责已移交 `layout/AppLayout.vue`。
 */
</script>

<template>
  <router-view />
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
}
</style>
