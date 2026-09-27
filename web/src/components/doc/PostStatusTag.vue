<script setup lang="ts">
/**
 * 过账状态标签（T4-2）。
 *
 * 背景：入库单 / 出库单 / 调拨单 / 盘点单 四个列表页各写了一份**完全相同**的
 * `<el-tag :type="detail.posted ? 'success' : 'info'">`，共 4 份副本。
 * 审核即过账是库存线的核心语义，这类状态标签必须同源，否则改一处漏三处。
 */
defineProps<{
  /** 是否已过账（后端 `posted` 字段） */
  posted: boolean | null | undefined
}>()
</script>

<template>
  <el-tag :type="posted ? 'success' : 'info'" size="small">
    {{ posted ? '已过账' : '未过账' }}
  </el-tag>
</template>
