<script setup lang="ts">
/**
 * 单据状态标签（V2.0）：草稿灰 / 待审核橙 / 已审核蓝 / 已完成绿 / 已作废红。
 *
 * 状态码与后端 `app/models_doc.DOC_STATUS` 一致；未知状态按灰色兜底。
 */
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  /** 状态码：draft/submitted/approved/completed/voided */
  status?: string
  /** 后端返回的中文标签（优先展示） */
  label?: string
  size?: 'large' | 'default' | 'small'
}>(), { status: '', label: '', size: 'small' })

const MAP: Record<string, { text: string; type: 'info' | 'warning' | 'primary' | 'success' | 'danger' }> = {
  draft: { text: '草稿', type: 'info' },
  submitted: { text: '待审核', type: 'warning' },
  approved: { text: '已审核', type: 'primary' },
  completed: { text: '已完成', type: 'success' },
  voided: { text: '已作废', type: 'danger' },
}

const meta = computed(() => MAP[props.status] ?? { text: props.status || '—', type: 'info' as const })
const text = computed(() => props.label || meta.value.text)
</script>

<template>
  <el-tag :type="meta.type" :size="size" effect="light">{{ text }}</el-tag>
</template>
