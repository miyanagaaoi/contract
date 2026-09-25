<script setup lang="ts">
/**
 * 盘点单列表（T-V2-28）：全盘 / 抽盘；审核时按差异自动生成盘盈入库 / 盘亏出库单。
 */
import DocListPage from '@/components/doc/DocListPage.vue'

const TAKE_TYPE_LABEL: Record<string, string> = { full: '全盘', partial: '抽盘' }
</script>

<template>
  <DocListPage title="盘点单" api="/api/stock/takes"
               subtitle="新建选仓库与全盘/抽盘 → 生成行项 → 录入实盘 → 审核自动生成盘盈/盘亏单"
               perm-prefix="stock.take" kind-label="盘点单"
               form-route="stock-take-form" edit-route="stock-take-edit" list-route="stock-takes"
               show-warehouse export-path="/api/stock/takes/export.xlsx"
               :extra-cols="['book', 'actual', 'diff']">
    <template #detail-head="{ detail }">
      <el-descriptions-item label="盘点方式">
        {{ TAKE_TYPE_LABEL[String(detail.take_type)] || '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="过账状态">
        <el-tag :type="detail.posted ? 'success' : 'info'" size="small">
          {{ detail.posted ? '已过账' : '未过账' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="盘盈入库单">{{ detail.generated_in_no || '—' }}</el-descriptions-item>
      <el-descriptions-item label="盘亏出库单">{{ detail.generated_out_no || '—' }}</el-descriptions-item>
      <el-descriptions-item label="盘点范围说明" :span="2">{{ detail.scope_note || '—' }}</el-descriptions-item>
    </template>
  </DocListPage>
</template>
