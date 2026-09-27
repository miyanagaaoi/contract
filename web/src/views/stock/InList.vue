<script setup lang="ts">
/**
 * 入库单列表（T-V2-25）：**审核即过账**，界面对 `posted` 给出提示。
 */
import DocListPage from '@/components/doc/DocListPage.vue'
import PostStatusTag from '@/components/doc/PostStatusTag.vue'
import { fmtDate } from '@/utils/format'
</script>

<template>
  <DocListPage title="入库单" api="/api/stock/in-orders"
               subtitle="审核即过账（写入库存流水）；入库类型：采购入库 / 退货入库 / 其他入库"
               perm-prefix="stock.in" kind-label="入库单"
               form-route="stock-in-form" edit-route="stock-in-edit" list-route="stock-in-orders"
               show-warehouse show-supplier
               export-path="/api/stock/in-orders/export.xlsx"
               :extra-cols="['received']">
    <template #detail-head="{ detail }">
      <el-descriptions-item label="入库类型">{{ detail.in_type || '—' }}</el-descriptions-item>
      <el-descriptions-item label="过账状态">
        <PostStatusTag :posted="detail.posted" />
      </el-descriptions-item>
      <el-descriptions-item label="来源采购单" :span="2">{{ detail.source_doc_no || '—' }}</el-descriptions-item>
      <el-descriptions-item label="审核时间" :span="2">
        {{ fmtDate(detail.approved_at) }}
      </el-descriptions-item>
    </template>
  </DocListPage>
</template>
