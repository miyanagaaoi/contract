<script setup lang="ts">
/** 无权限页（403）：展示所需权限点，便于管理员排查。 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const perm = computed(() => (route.query.perm as string) || '')
</script>

<template>
  <div class="forbidden">
    <div class="code">403</div>
    <p class="msg">你没有访问该页面的权限</p>
    <p class="det">
      所需权限点：<code>{{ perm || '—' }}</code> · 如需开通请联系系统管理员
    </p>
    <div class="actions">
      <el-button type="primary" @click="router.replace('/')">返回首页</el-button>
      <el-button @click="router.back()">返回上一页</el-button>
    </div>
  </div>
</template>

<style scoped>
.forbidden {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--ctms-bg);
}
.code { font-size: 64px; font-weight: 800; color: #5a6b7d; line-height: 1; letter-spacing: 4px; }
.msg { font-size: var(--ctms-fs-base); margin: 14px 0 4px; color: var(--ctms-text); }
.det { font-size: var(--ctms-fs-sm); color: var(--ctms-text-muted); margin: 0 0 20px; }
.det code { background: #f2f6fc; border: 1px solid #e4edf7; border-radius: 4px; padding: 1px 6px; }
.actions { display: flex; gap: 10px; }
</style>
