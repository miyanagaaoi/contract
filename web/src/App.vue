<script setup lang="ts">
import { useRoute } from 'vue-router'
import { ref } from 'vue'

const route = useRoute()
const activeMenu = ref(route.path)
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="brand">合同管理与跟踪系统</div>
      <el-menu :default-active="activeMenu" router background-color="#1f2d3d" text-color="#c0c4cc" active-text-color="#409eff">
        <el-menu-item index="/">
          <el-icon><Odometer /></el-icon><span>首页看板</span>
        </el-menu-item>
        <el-menu-item index="/contracts">
          <el-icon><Files /></el-icon><span>合同台账</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon><span>系统设置</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span class="hint">纯内网使用 · 免登录（原型）</span>
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
}
.hint { color: #909399; font-size: 13px; }
.main { padding: 16px; }
</style>
