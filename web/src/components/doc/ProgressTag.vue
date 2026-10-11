<script setup lang="ts">
/**
 * 进度标签（V2.5，AC-V2.5-12/13）。
 *
 * 口径（BR-V2.5-06，与后端 `finance_service.progress_of` 完全一致）：
 * - `pct === null`（分母为 0）→ 显示 `—`，不是 `0%`；
 * - `0%` 灰、`0 < p < 100` 蓝、`100%` 绿、`> 100%` 红（超额）；
 * - 保留 **1 位小数**，与导出的文本一致（AC-V2.5-16 要求页面与导出一致）；
 * - 悬浮提示给出分子/分母（"已付 3000.00 / 10000.00"），避免"进度是什么口径"的反复解释。
 */
import { computed } from 'vue'

import type { ProgressItem } from '@/types/doc'

const props = defineProps<{
  item?: ProgressItem | null
  label?: string
  /** 金额类进度的悬浮提示前缀（如「已付」）；数量类传「已入」 */
  numLabel?: string
  denLabel?: string
}>()

const text = computed(() => {
  const pct = props.item?.pct
  return pct === null || pct === undefined ? '—' : `${Number(pct).toFixed(1)}%`
})

const tagType = computed(() => {
  const pct = props.item?.pct
  if (pct === null || pct === undefined) return 'info'
  if (props.item?.over || pct > 100) return 'danger'
  if (pct >= 100) return 'success'
  if (pct > 0) return 'primary'
  return 'info'
})

const tip = computed(() => {
  const item = props.item
  if (!item) return ''
  const head = props.label ? `${props.label}：` : ''
  return `${head}${props.numLabel || ''} ${Number(item.num).toLocaleString('zh-CN',
    { minimumFractionDigits: 2, maximumFractionDigits: 2 })} / ${props.denLabel || ''} ${Number(item.den).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
})
</script>

<template>
  <el-tooltip v-if="item" :content="tip" placement="top">
    <el-tag :type="tagType" size="small" effect="light">{{ text }}</el-tag>
  </el-tooltip>
  <span v-else class="gray">—</span>
</template>

<style scoped>
.gray { color: var(--ctms-text-muted); }
</style>
