<script setup lang="ts">
/**
 * 应用根组件（T-V2-15）：只承载路由出口与全局样式；
 * 侧栏/顶栏等布局职责已移交 `layout/AppLayout.vue`。
 */
</script>

<template>
  <router-view />
</template>

<!--
  T4-7：此处原有一段与 `src/style.css` 逐字重复的全局 reset（html / body / #app）。
  全局样式只保留 style.css 一处，避免"改了一处忘了另一处"。
-->
